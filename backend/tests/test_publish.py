import unittest
from datetime import datetime, timezone
from unittest import mock

from tests import _env

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.video_job import VideoJob
from app.models.video_version import VideoVersion
from app.routers import publish as publish_router
from app.services import publish_service


SLUG = _env.WORKSPACE_SLUG


class PublishApiTests(unittest.TestCase):
    def setUp(self):
        self.session_factory = _env.new_session_factory()

        app = FastAPI()
        app.include_router(publish_router.router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def create_approved_version(self, *, title="Motor monitoring") -> tuple[str, str]:
        with self.session_factory() as db:
            job = VideoJob(
                title=title,
                workspace_slug=SLUG,
                template_id="DynamicVideo",
                status="completed",
                renderer_job_id="renderer-1",
                output_file="renderer-1.mp4",
                input_data={
                    "video_plan": {
                        "title": title,
                        "concept": "Monitor motors before they fail.",
                        "cta": "Book a plant assessment",
                    }
                },
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            version = VideoVersion(
                job_id=job.id,
                version_number=1,
                status="completed",
                approval_status="approved",
                reviewed_at=datetime.now(timezone.utc),
                filename="renderer-1.mp4",
                storage_path="/data/videos/renderer-1.mp4",
                duration_seconds=15,
                width=1080,
                height=1920,
                fps=30,
                render_metadata={"renderer_job_id": "renderer-1"},
            )
            db.add(version)
            db.commit()
            db.refresh(version)

            return job.id, version.id

    def test_platforms_endpoint_lists_linkedin_as_live(self):
        body = self.client.get("/publish/platforms").json()

        self.assertIn("linkedin", body["platforms"])
        self.assertEqual(body["live"], ["linkedin"])

    def test_ready_queue_only_returns_approved_unpublished_versions(self):
        _, version_id = self.create_approved_version()

        with self.session_factory() as db:
            pending_job = VideoJob(
                title="Pending",
                workspace_slug=SLUG,
                template_id="DynamicVideo",
                status="completed",
                renderer_job_id="renderer-2",
                input_data={"video_plan": {"title": "Pending", "cta": "CTA"}},
            )
            db.add(pending_job)
            db.commit()
            db.refresh(pending_job)
            db.add(VideoVersion(
                job_id=pending_job.id,
                version_number=1,
                status="completed",
                approval_status="pending",
                filename="pending.mp4",
                storage_path="/data/videos/pending.mp4",
            ))
            db.commit()

        ready = self.client.get("/publish/ready?platforms=linkedin").json()

        self.assertEqual(ready["total"], 1)
        self.assertEqual(ready["items"][0]["version_id"], version_id)
        self.assertIn("Book a plant assessment", ready["items"][0]["caption"])

    def test_dry_run_publish_does_not_call_linkedin(self):
        _, version_id = self.create_approved_version()

        with mock.patch.object(
            publish_service,
            "fetch_video_bytes",
            return_value=b"fake-mp4-bytes",
        ) as fetch_video, mock.patch(
            "app.providers.linkedin.publish_provider.LinkedInPublishProvider"
        ) as provider_cls:
            response = self.client.post(
                "/publish/jobs",
                json={
                    "version_id": version_id,
                    "platforms": ["linkedin"],
                    "dry_run": True,
                    "requested_by": "n8n",
                },
            )

        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(len(body["jobs"]), 1)
        self.assertEqual(body["jobs"][0]["status"], "dry_run")
        self.assertTrue(body["jobs"][0]["remote_post_id"].startswith("dry-run-"))
        fetch_video.assert_called_once()
        provider_cls.assert_not_called()

    def test_second_publish_is_idempotent(self):
        _, version_id = self.create_approved_version()

        with mock.patch.object(
            publish_service,
            "fetch_video_bytes",
            return_value=b"fake-mp4-bytes",
        ):
            first = self.client.post(
                "/publish/jobs",
                json={
                    "version_id": version_id,
                    "platforms": ["linkedin"],
                    "dry_run": True,
                },
            ).json()
            second = self.client.post(
                "/publish/jobs",
                json={
                    "version_id": version_id,
                    "platforms": ["linkedin"],
                    "dry_run": True,
                },
            ).json()

        self.assertEqual(first["jobs"][0]["publish_job_id"], second["jobs"][0]["publish_job_id"])
        self.assertEqual(second["jobs"][0]["status"], "dry_run")

        ready = self.client.get("/publish/ready?platforms=linkedin").json()
        self.assertEqual(ready["total"], 0)

    def test_missing_linkedin_account_fails_in_live_mode(self):
        _, version_id = self.create_approved_version()

        with mock.patch.object(
            publish_service,
            "fetch_video_bytes",
            return_value=b"fake-mp4-bytes",
        ):
            response = self.client.post(
                "/publish/jobs",
                json={
                    "version_id": version_id,
                    "platforms": ["linkedin"],
                    "dry_run": False,
                },
            )

        self.assertEqual(response.status_code, 202)
        job = response.json()["jobs"][0]
        self.assertEqual(job["status"], "failed")
        self.assertIn("No active LinkedIn publish account", job["error_message"])

    def test_stub_platform_fails_as_not_configured(self):
        _, version_id = self.create_approved_version()

        response = self.client.post(
            "/publish/jobs",
            json={
                "version_id": version_id,
                "platforms": ["tiktok"],
                "dry_run": False,
            },
        )

        self.assertEqual(response.status_code, 202)
        job = response.json()["jobs"][0]
        self.assertEqual(job["status"], "failed")
        self.assertIn("not configured", job["error_message"].lower())

    def test_register_account_hides_access_token(self):
        response = self.client.post(
            "/publish/accounts",
            json={
                "workspace_slug": SLUG,
                "platform": "linkedin",
                "display_name": "Company page",
                "access_token": "secret-token-value",
                "author_urn": "urn:li:organization:123",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["has_access_token"])
        self.assertEqual(body["author_urn"], "urn:li:organization:123")
        self.assertNotIn("access_token", body)
        self.assertNotIn("secret-token-value", str(body))


if __name__ == "__main__":
    unittest.main()
