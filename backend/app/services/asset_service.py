
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


def enqueue_video_generation(
    source_asset_id: str,
    motion_prompt: str,
    duration_seconds: int,
) -> dict:
    db = SessionLocal()

    try:
        source_asset = db.query(VideoAsset).filter(
            VideoAsset.id == source_asset_id
        ).first()

        if not source_asset:
            raise ValueError("Source image asset not found")

        if source_asset.asset_type != "image":
            raise ValueError("Source asset must be an image")

        if source_asset.status != "completed" or not source_asset.source_url:
            raise ValueError("Source image asset is not ready")

        if duration_seconds < 4 or duration_seconds > 15:
            raise ValueError(
                "Video duration must be between 4 and 15 seconds"
            )

        metadata = source_asset.asset_metadata or {}
        aspect_ratio = metadata.get("aspect_ratio", "9:16")

        if aspect_ratio not in ("9:16", "16:9", "1:1"):
            raise ValueError("Unsupported source image aspect ratio")

        asset_id = str(uuid.uuid4())
        asset = VideoAsset(
            id=asset_id,
            job_id=source_asset.job_id,
            scene_number=source_asset.scene_number,
            asset_type="video",
            provider="fal",
            model=os.getenv(
                "FAL_VIDEO_MODEL",
                "bytedance/seedance-2.0/fast/image-to-video",
            ),
            status="pending",
            prompt=motion_prompt,
            filename=f"pending_{asset_id}.mp4",
            duration_seconds=duration_seconds,
            asset_metadata={
                "aspect_ratio": aspect_ratio,
                "generation_type": "image_to_video",
                "source_asset_id": source_asset.id,
                "source_image_url": source_asset.source_url,
            },
        )

        db.add(asset)
        db.commit()

        try:
            queue = Queue(
                "asset-generation",
                connection=get_redis_connection(),
                default_timeout=1500,
            )
            queue.enqueue(
                "app.workers.asset_worker.generate_video_asset",
                asset_id,
                job_timeout=1500,
                result_ttl=86400,
                failure_ttl=604800,
            )
        except Exception:
            asset.status = "failed"
            asset.error_message = "Unable to enqueue video generation task"
            db.commit()
            raise

        return {
            "asset_id": asset_id,
            "job_id": asset.job_id,
            "scene_number": asset.scene_number,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "duration_seconds": asset.duration_seconds,
        }
    finally:
        db.close()


def enqueue_audio_generation(
    job_id: str,
    scene_number: int,
    narration: str,
) -> dict:
    """
    Queue ElevenLabs narration audio for one storyboard scene.
    """
    cleaned = (narration or "").strip()

    if not cleaned:
        raise ValueError("Narration text cannot be empty")

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
            asset_type="audio",
            provider="elevenlabs",
            model=os.getenv(
                "ELEVENLABS_MODEL_ID",
                "eleven_flash_v2_5",
            ),
            status="pending",
            prompt=cleaned,
            filename=f"pending_{asset_id}.mp3",
            review_status="approved",
            asset_metadata={
                "generation_type": "text_to_speech",
                "voice_id": os.getenv(
                    "ELEVENLABS_VOICE_ID",
                    "JBFqnCBsd6RMkjVDRZzb",
                ),
            },
        )

        db.add(asset)
        db.commit()

        try:
            queue = Queue(
                "asset-generation",
                connection=get_redis_connection(),
                default_timeout=300,
            )
            queue.enqueue(
                "app.workers.asset_worker.generate_audio_asset",
                asset_id,
                job_timeout=300,
                result_ttl=86400,
                failure_ttl=604800,
            )
        except Exception:
            asset.status = "failed"
            asset.error_message = "Unable to enqueue audio generation task"
            db.commit()
            raise

        return {
            "asset_id": asset_id,
            "job_id": job_id,
            "scene_number": scene_number,
            "asset_type": "audio",
            "status": "pending",
            "text_length": len(cleaned),
        }
    finally:
        db.close()
