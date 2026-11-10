
import logging
import os
from datetime import datetime, timezone

from redis import Redis
from rq import Queue, Worker

from app.database import SessionLocal
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob
from app.providers.elevenlabs.tts_provider import ElevenLabsTTSProvider
from app.providers.fal.image_provider import FalImageProvider
from app.providers.fal.video_provider import FalVideoProvider
from app.services.production_service import advance_autonomous_production


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asset-worker")


def generate_image_asset(asset_id: str):
    db = SessionLocal()

    try:
        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if not asset:
            raise ValueError(f"Asset not found: {asset_id}")

        if asset.asset_type != "image":
            raise ValueError("Unsupported asset type")

        asset.status = "generating"
        asset.error_message = None
        db.commit()

        logger.info("Generating image asset %s", asset_id)

        provider = FalImageProvider()

        metadata = asset.asset_metadata or {}
        aspect_ratio = metadata.get("aspect_ratio", "9:16")

        result = provider.generate_image(
            prompt=asset.prompt or "",
            job_id=asset.job_id,
            scene_number=asset.scene_number,
            aspect_ratio=aspect_ratio,
            max_wait_seconds=600,
        )

        asset.provider = result["provider"]
        asset.model = result["model"]
        asset.filename = result["filename"]
        asset.storage_path = result["storage_path"]
        asset.source_url = result["source_url"]
        asset.mime_type = result["mime_type"]
        asset.status = "completed"
        asset.error_message = None

        metadata.update({
            "provider_request_id": result["request_id"],
            "file_size_bytes": result["file_size_bytes"],
            "generation_status": "completed",
        })

        asset.asset_metadata = metadata

        video_job = db.query(VideoJob).filter(
            VideoJob.id == asset.job_id
        ).first()

        is_autonomous = bool(
            video_job
            and (video_job.input_data or {}).get("production_mode")
            == "autonomous"
        )

        if is_autonomous:
            asset.review_status = "approved"
            asset.reviewed_at = datetime.now(timezone.utc)
            asset.review_note = (
                "Automatically approved for autonomous production. "
                "Final video approval is still required."
            )

        db.commit()

        logger.info("Asset generation completed: %s", asset_id)

        if is_autonomous:
            advance_autonomous_production(asset.job_id)

        return {
            "asset_id": asset_id,
            "status": "completed",
            "filename": asset.filename,
        }

    except Exception as exc:
        db.rollback()

        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if asset:
            asset.status = "failed"
            asset.error_message = str(exc)[:4000]
            db.commit()

            video_job = db.query(VideoJob).filter(
                VideoJob.id == asset.job_id
            ).first()

            if (
                video_job
                and (video_job.input_data or {}).get("production_mode")
                == "autonomous"
            ):
                advance_autonomous_production(asset.job_id)

        logger.exception("Asset generation failed: %s", asset_id)
        raise

    finally:
        db.close()


def generate_audio_asset(asset_id: str):
    db = SessionLocal()

    try:
        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if not asset:
            raise ValueError(f"Asset not found: {asset_id}")

        if asset.asset_type != "audio":
            raise ValueError("Unsupported asset type")

        if not asset.prompt:
            raise ValueError("Narration text is unavailable")

        asset.status = "generating"
        asset.error_message = None
        db.commit()

        logger.info("Generating audio asset %s", asset_id)

        provider = ElevenLabsTTSProvider()
        result = provider.synthesize(
            text=asset.prompt,
            job_id=asset.job_id,
            scene_number=asset.scene_number or 1,
        )

        asset.provider = result["provider"]
        asset.model = result["model"]
        asset.filename = result["filename"]
        asset.storage_path = result["storage_path"]
        asset.mime_type = result["mime_type"]
        asset.status = "completed"
        asset.error_message = None
        asset.review_status = "approved"
        asset.reviewed_at = datetime.now(timezone.utc)
        asset.review_note = (
            "Automatically approved narration for final-video assembly. "
            "Final video approval is still required."
        )

        metadata = asset.asset_metadata or {}
        metadata.update({
            "provider_request_id": result.get("request_id"),
            "character_cost": result.get("character_cost"),
            "file_size_bytes": result["file_size_bytes"],
            "text_length": result["text_length"],
            "voice_id": result["voice_id"],
            "generation_status": "completed",
            "generation_type": "text_to_speech",
        })
        asset.asset_metadata = metadata
        db.commit()

        return {
            "asset_id": asset_id,
            "status": "completed",
            "filename": asset.filename,
        }
    except Exception as exc:
        db.rollback()
        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if asset:
            asset.status = "failed"
            asset.error_message = str(exc)[:4000]
            db.commit()

        logger.exception("Audio asset generation failed: %s", asset_id)
        raise
    finally:
        db.close()


def generate_video_asset(asset_id: str):
    db = SessionLocal()

    try:
        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if not asset:
            raise ValueError(f"Asset not found: {asset_id}")

        if asset.asset_type != "video":
            raise ValueError("Unsupported asset type")

        metadata = asset.asset_metadata or {}
        source_image_url = metadata.get("source_image_url")
        aspect_ratio = metadata.get("aspect_ratio", "9:16")

        if not source_image_url:
            raise ValueError("Source image URL is unavailable")

        if not asset.duration_seconds:
            raise ValueError("Video duration is unavailable")

        asset.status = "generating"
        asset.error_message = None
        db.commit()

        provider = FalVideoProvider()
        result = provider.generate_video(
            prompt=asset.prompt or "",
            image_url=source_image_url,
            job_id=asset.job_id,
            scene_number=asset.scene_number or 1,
            aspect_ratio=aspect_ratio,
            duration_seconds=asset.duration_seconds,
        )

        asset.provider = result["provider"]
        asset.model = result["model"]
        asset.filename = result["filename"]
        asset.storage_path = result["storage_path"]
        asset.source_url = result["source_url"]
        asset.mime_type = result["mime_type"]
        asset.status = "completed"
        asset.error_message = None
        asset.review_status = "approved"
        asset.reviewed_at = datetime.now(timezone.utc)
        asset.review_note = (
            "Automatically approved for final-video assembly. "
            "Final video approval is still required."
        )

        metadata.update({
            "provider_request_id": result["request_id"],
            "file_size_bytes": result["file_size_bytes"],
            "generation_status": "completed",
        })
        asset.asset_metadata = metadata
        db.commit()

        return {
            "asset_id": asset_id,
            "status": "completed",
            "filename": asset.filename,
        }
    except Exception as exc:
        db.rollback()
        asset = db.query(VideoAsset).filter(
            VideoAsset.id == asset_id
        ).first()

        if asset:
            asset.status = "failed"
            asset.error_message = str(exc)[:4000]
            db.commit()

        logger.exception("Video asset generation failed: %s", asset_id)
        raise
    finally:
        db.close()


def main():
    redis_connection = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=False,
    )

    queue = Queue(
        "asset-generation",
        connection=redis_connection,
        default_timeout=900,
    )

    worker = Worker(
        [queue],
        connection=redis_connection,
    )

    logger.info("Asset generation worker starting")
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
