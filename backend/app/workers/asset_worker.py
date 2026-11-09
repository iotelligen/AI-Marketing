
import logging
import os
from datetime import datetime, timezone

from redis import Redis
from rq import Queue, Worker

from app.database import SessionLocal
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob
from app.providers.fal.image_provider import FalImageProvider
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
