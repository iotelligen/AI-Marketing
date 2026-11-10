import unittest
import uuid

from pathlib import Path
from unittest import mock

from tests import _env

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob
from app.providers.elevenlabs.tts_provider import (
    ElevenLabsTTSError,
    ElevenLabsTTSProvider,
)
from app.routers import asset_generation as asset_router
from app.routers import videos as videos_router
from app.services import production_service


SLUG = _env.WORKSPACE_SLUG


def sample_plan() -> dict:
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
                "narration": "",
                "visual_prompt": "A calm dark background",
                "on_screen_text": "Talk to us",
                "transition": "fade",
            },
        ],
    }


class ElevenLabsAudioTestCase(unittest.TestCase):
    def setUp(self):
        self.session_factory = _env.new_session_factory()

        app = FastAPI()
        app.include_router(videos_router.router)
        app.include_router(asset_router.router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def create_draft_job(self) -> str:
        job_id = str(uuid.uuid4())

        with self.session_factory() as db:
            db.add(
                VideoJob(
                    id=job_id,
                    title="Motor monitoring",
                    prompt="Motors",
                    workspace_slug=SLUG,
                    template_id="DynamicVideo",
                    input_data={"video_plan": sample_plan()},
                    status="draft",
                    progress=0,
                )
            )
            db.commit()

        return job_id

    def test_provider_writes_mp3_under_asset_storage(self):
        job_id = str(uuid.uuid4())
        fake_audio = b"ID3fake-mp3-bytes"

        with mock.patch.dict(
            "os.environ",
            {
                "ELEVENLABS_API_KEY": "test-key",
                "ASSET_STORAGE": str(_env.ASSET_DIR),
            },
            clear=False,
        ):
            provider = ElevenLabsTTSProvider()

            response = mock.Mock()
            response.status_code = 200
            response.content = fake_audio
            response.headers = {
                "character-cost": "12",
                "request-id": "req-1",
            }
            response.text = ""

            with mock.patch.object(
                provider.session,
                "post",
                return_value=response,
            ) as post:
                result = provider.synthesize(
                    text="Motors fail without warning.",
                    job_id=job_id,
                    scene_number=1,
                )

        self.assertEqual(result["mime_type"], "audio/mpeg")
        self.assertEqual(result["file_size_bytes"], len(fake_audio))
        self.assertTrue(Path(result["storage_path"]).is_file())
        self.assertEqual(
            Path(result["storage_path"]).read_bytes(),
            fake_audio,
        )
        self.assertIn(job_id, result["storage_path"])

        post.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["xi-api-key"], "test-key")
        self.assertEqual(
            kwargs["json"]["model_id"],
            "eleven_flash_v2_5",
        )

    def test_provider_requires_api_key(self):
        with mock.patch.dict(
            "os.environ",
            {"ELEVENLABS_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(ElevenLabsTTSError):
                ElevenLabsTTSProvider()

    def test_generate_audio_from_plan_queues_narrated_scenes(self):
        job_id = self.create_draft_job()

        with mock.patch(
            "app.routers.videos.enqueue_audio_generation",
            return_value={
                "asset_id": "audio-1",
                "status": "pending",
                "text_length": 28,
            },
        ) as enqueue:
            response = self.client.post(
                f"/videos/jobs/{job_id}/assets/generate-audio-from-plan"
            )

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()

        self.assertEqual(payload["queued_count"], 1)
        self.assertEqual(payload["results"][0]["action"], "queued")
        self.assertEqual(payload["results"][1]["action"], "skipped")
        self.assertEqual(
            payload["results"][1]["reason"],
            "empty_narration",
        )
        enqueue.assert_called_once_with(
            job_id=job_id,
            scene_number=1,
            narration="Motors fail without warning.",
        )

    def test_manifest_includes_optional_audio_path(self):
        job_id = self.create_draft_job()
        image_path = _env.ASSET_DIR / job_id / "scene_01" / "image.png"
        audio_path = _env.ASSET_DIR / job_id / "scene_01" / "voice.mp3"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        audio_path.write_bytes(b"ID3audio")

        with self.session_factory() as db:
            db.add(
                VideoAsset(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    scene_number=1,
                    asset_type="image",
                    provider="fal",
                    model="flux",
                    status="completed",
                    filename="image.png",
                    storage_path=str(image_path),
                    review_status="approved",
                )
            )
            db.add(
                VideoAsset(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    scene_number=2,
                    asset_type="image",
                    provider="fal",
                    model="flux",
                    status="completed",
                    filename="image.png",
                    storage_path=str(image_path),
                    review_status="approved",
                )
            )
            db.add(
                VideoAsset(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    scene_number=1,
                    asset_type="audio",
                    provider="elevenlabs",
                    model="eleven_flash_v2_5",
                    status="completed",
                    filename="voice.mp3",
                    storage_path=str(audio_path),
                    review_status="approved",
                )
            )
            db.commit()

            job = db.query(VideoJob).filter(VideoJob.id == job_id).one()
            manifest = production_service.build_render_manifest(job, db)

        self.assertEqual(
            manifest["scenes"][0]["audio_path"],
            str(audio_path.resolve()),
        )
        self.assertNotIn("audio_path", manifest["scenes"][1])


if __name__ == "__main__":
    unittest.main()
