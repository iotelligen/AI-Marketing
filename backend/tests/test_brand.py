import unittest

from pathlib import Path
from unittest import mock

from tests import _env

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob
from app.routers import brand as brand_router
from app.routers import videos as videos_router
from app.services import production_service
from app.services.brand_service import (
    BRAND_STORAGE,
    brand_facts_for_prompt,
    build_render_brand,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SLUG = _env.WORKSPACE_SLUG


def plan_with_beats() -> dict:
    return {
        "concept": "Concept",
        "title": "Motor monitoring",
        "duration_seconds": 10,
        "aspect_ratio": "9:16",
        "language": "English",
        "target_audience": "Factory owners",
        "objective": "Awareness",
        "cta": "Talk to us",
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 6,
                "beat": "hook",
                "purpose": "Stop the scroll",
                "narration": "Motors fail without warning.",
                "visual_prompt": "A factory motor",
                "on_screen_text": "Motors fail",
                "transition": "fade",
            },
            {
                "scene_number": 2,
                "duration_seconds": 4,
                "beat": "cta",
                "purpose": "Invite contact",
                "narration": "Talk to us.",
                "visual_prompt": "A calm dark background",
                "on_screen_text": "Talk to us",
                "transition": "fade",
            },
        ],
    }


class BrandTestCase(unittest.TestCase):
    def setUp(self):
        self.session_factory = _env.new_session_factory()

        app = FastAPI()
        app.include_router(brand_router.router)
        app.include_router(videos_router.router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        self.client = TestClient(app)

    def save_brand(self, **overrides):
        payload = {
            "brand_name": "IoTelliGen",
            "tagline": "Smarter factories",
            "accent_color": "#0a84ff",
            "website": "iotelligen.example",
            "email": "sales@iotelligen.example",
            "phone": "+880 1700 000000",
        }
        payload.update(overrides)

        return self.client.put(f"/workspaces/{SLUG}/brand", json=payload)

    def upload_logo(self, content=PNG, filename="logo.png"):
        return self.client.post(
            f"/workspaces/{SLUG}/brand/logo",
            files={"file": (filename, content, "application/octet-stream")},
        )


class BrandApiTests(BrandTestCase):
    def test_unknown_workspace_is_not_found(self):
        response = self.client.get("/workspaces/nope/brand")

        self.assertEqual(response.status_code, 404)

    def test_defaults_are_returned_before_anything_is_saved(self):
        body = self.client.get(f"/workspaces/{SLUG}/brand").json()

        self.assertFalse(body["configured"])
        self.assertEqual(body["brand_name"], "IoTelliGen")
        self.assertEqual(body["accent_color"], "#16C79A")
        self.assertFalse(body["has_logo"])
        self.assertIsNone(body["logo_url"])

    def test_profile_is_saved_and_blank_fields_become_null(self):
        response = self.save_brand(tagline="   ", phone="")

        self.assertEqual(response.status_code, 200)

        body = self.client.get(f"/workspaces/{SLUG}/brand").json()

        self.assertTrue(body["configured"])
        self.assertEqual(body["accent_color"], "#0A84FF")
        self.assertEqual(body["website"], "iotelligen.example")
        self.assertIsNone(body["tagline"])
        self.assertIsNone(body["phone"])

    def test_invalid_accent_color_is_rejected(self):
        response = self.save_brand(accent_color="green")

        self.assertEqual(response.status_code, 422)

    def test_logo_upload_stores_the_file_inside_brand_storage(self):
        response = self.upload_logo()

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertTrue(body["has_logo"])
        self.assertEqual(body["logo_filename"], "logo.png")

        with self.session_factory() as db:
            brand = build_render_brand(db, SLUG)

        logo_path = Path(brand["logo_path"])

        self.assertTrue(logo_path.is_file())
        self.assertTrue(logo_path.is_relative_to(BRAND_STORAGE))

        logo = self.client.get(body["logo_url"])

        self.assertEqual(logo.status_code, 200)
        self.assertEqual(logo.headers["content-type"], "image/png")
        self.assertEqual(logo.content, PNG)

    def test_new_logo_replaces_the_old_file(self):
        self.upload_logo()

        with self.session_factory() as db:
            first = Path(build_render_brand(db, SLUG)["logo_path"])

        self.upload_logo(content=JPEG, filename="logo.jpg")

        with self.session_factory() as db:
            second = Path(build_render_brand(db, SLUG)["logo_path"])

        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        self.assertEqual(second.suffix, ".jpg")

    def test_file_type_is_decided_by_content_not_by_name(self):
        response = self.upload_logo(
            content=b"<svg onload=alert(1)></svg>",
            filename="logo.png",
        )

        self.assertEqual(response.status_code, 400)

    def test_oversized_logo_is_rejected(self):
        with mock.patch.object(brand_router, "MAX_LOGO_SIZE", 32):
            response = self.upload_logo()

        self.assertEqual(response.status_code, 413)

    def test_logo_can_be_deleted(self):
        self.upload_logo()

        with self.session_factory() as db:
            logo_path = Path(build_render_brand(db, SLUG)["logo_path"])

        response = self.client.delete(f"/workspaces/{SLUG}/brand/logo")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_logo"])
        self.assertFalse(logo_path.exists())

        missing = self.client.get(f"/workspaces/{SLUG}/brand/logo")

        self.assertEqual(missing.status_code, 404)

    def test_logo_path_outside_brand_storage_is_ignored(self):
        self.upload_logo()

        outside = _env.ASSET_DIR.parent / "outside-logo.png"
        outside.write_bytes(PNG)
        self.addCleanup(outside.unlink, missing_ok=True)

        with self.session_factory() as db:
            profile = db.query(brand_router.BrandProfile).one()
            profile.logo_storage_path = str(outside)
            db.commit()

            brand = build_render_brand(db, SLUG)

        self.assertNotIn("logo_path", brand)


class BrandServiceTests(BrandTestCase):
    def test_render_brand_falls_back_to_defaults(self):
        with self.session_factory() as db:
            brand = build_render_brand(db, SLUG)

        self.assertEqual(
            brand,
            {"name": "IoTelliGen", "accent_color": "#16C79A"},
        )

    def test_render_brand_carries_contact_details(self):
        self.save_brand()

        with self.session_factory() as db:
            brand = build_render_brand(db, SLUG)

        self.assertEqual(brand["accent_color"], "#0A84FF")
        self.assertEqual(brand["website"], "iotelligen.example")
        self.assertEqual(brand["phone"], "+880 1700 000000")
        self.assertNotIn("logo_path", brand)

    def test_prompt_facts_never_include_contact_details(self):
        self.save_brand()

        with self.session_factory() as db:
            facts = brand_facts_for_prompt(db, SLUG)

        self.assertIn("IoTelliGen", facts)
        self.assertIn("Smarter factories", facts)
        self.assertNotIn("1700", facts)
        self.assertNotIn("sales@", facts)
        self.assertNotIn("iotelligen.example", facts)


class RenderManifestTests(BrandTestCase):
    """Both render paths must send the brand and each scene's beat."""

    def create_job_with_approved_images(self) -> str:
        with self.session_factory() as db:
            job = VideoJob(
                title="Motor monitoring",
                workspace_slug=SLUG,
                template_id="DynamicVideo",
                status="draft",
                input_data={"video_plan": plan_with_beats()},
            )
            db.add(job)
            db.commit()

            for scene_number in (1, 2):
                scene_dir = (
                    _env.ASSET_DIR / job.id / f"scene_{scene_number:02d}"
                )
                scene_dir.mkdir(parents=True)

                image_path = scene_dir / "image.png"
                image_path.write_bytes(PNG)

                db.add(VideoAsset(
                    job_id=job.id,
                    scene_number=scene_number,
                    asset_type="image",
                    status="completed",
                    review_status="approved",
                    filename="image.png",
                    storage_path=str(image_path),
                ))

            db.commit()

            return job.id

    def assert_manifest_is_branded(self, manifest: dict):
        self.assertEqual(manifest["brand_name"], "IoTelliGen")
        self.assertEqual(manifest["accent_color"], "#0A84FF")
        self.assertEqual(manifest["brand"]["phone"], "+880 1700 000000")
        self.assertTrue(Path(manifest["brand"]["logo_path"]).is_file())
        self.assertEqual(
            [scene["beat"] for scene in manifest["scenes"]],
            ["hook", "cta"],
        )

    def test_manual_render_sends_brand_and_beats(self):
        self.save_brand()
        self.upload_logo()
        job_id = self.create_job_with_approved_images()

        with mock.patch.object(
            videos_router,
            "renderer_request",
            return_value={"job_id": "42"},
        ) as renderer_request:
            response = self.client.post(f"/videos/jobs/{job_id}/render")

        self.assertEqual(response.status_code, 202, response.text)

        manifest = renderer_request.call_args.args[2]

        self.assert_manifest_is_branded(manifest)

    def test_autonomous_render_sends_brand_and_beats(self):
        self.save_brand()
        self.upload_logo()
        job_id = self.create_job_with_approved_images()

        with self.session_factory() as db:
            job = db.query(VideoJob).filter(VideoJob.id == job_id).one()
            manifest = production_service.build_render_manifest(job, db)

        self.assert_manifest_is_branded(manifest)

    def test_storyboards_saved_before_beats_still_render(self):
        job_id = self.create_job_with_approved_images()

        with self.session_factory() as db:
            job = db.query(VideoJob).filter(VideoJob.id == job_id).one()

            plan = plan_with_beats()

            for scene in plan["scenes"]:
                del scene["beat"]

            job.input_data = {"video_plan": plan}
            db.commit()

            manifest = production_service.build_render_manifest(job, db)

        self.assertEqual(
            [scene["beat"] for scene in manifest["scenes"]],
            [None, None],
        )
        self.assertEqual(manifest["brand_name"], "IoTelliGen")


if __name__ == "__main__":
    unittest.main()
