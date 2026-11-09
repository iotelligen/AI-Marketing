
import os
import uuid

from redis import Redis
from rq import Queue

from app.database import SessionLocal
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob


def get_redis_connection():
    return Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


def enqueue_image_generation(
    job_id: str,
    scene_number: int,
    prompt: str,
    aspect_ratio: str,
) -> dict:
    db = SessionLocal()

    try:
        video_job = db.query(VideoJob).filter(
            VideoJob.id == job_id
        ).first()

        if not video_job:
            raise ValueError("Video job not found")

        asset_id = str(uuid.uuid4())

        asset = VideoAsset(
            id=asset_id,
            job_id=job_id,
            scene_number=scene_number,
            asset_type="image",
            provider="fal",
            model=os.getenv(
                "FAL_IMAGE_MODEL",
                "fal-ai/flux/dev",
            ),
            status="pending",
            prompt=prompt,
            filename=f"pending_{asset_id}.jpg",
            asset_metadata={
                "aspect_ratio": aspect_ratio,
                "generation_type": "text_to_image",
            },
        )

        db.add(asset)
        db.commit()

        try:
            queue = Queue(
                "asset-generation",
                connection=get_redis_connection(),
                default_timeout=900,
            )

            queue.enqueue(
                "app.workers.asset_worker.generate_image_asset",
                asset_id,
                job_timeout=900,
                result_ttl=86400,
                failure_ttl=604800,
            )

        except Exception:
            asset.status = "failed"
            asset.error_message = "Unable to enqueue generation task"
            db.commit()
            raise

        return {
            "asset_id": asset_id,
            "job_id": job_id,
            "scene_number": scene_number,
            "asset_type": "image",
            "status": "pending",
        }

    finally:
        db.close()
