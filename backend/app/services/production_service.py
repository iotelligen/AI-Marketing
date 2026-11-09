import json
import logging
import os
import urllib.error
import urllib.request

from pathlib import Path

from app.database import SessionLocal
from app.models.video_asset import VideoAsset
from app.models.video_job import VideoJob
from app.schemas.video_planner import VideoPlan


logger = logging.getLogger(__name__)

VIDEO_RENDERER_URL = os.getenv(
    "VIDEO_RENDERER_URL",
    "http://video-renderer:8100",
).rstrip("/")

ASSET_STORAGE = Path(
    os.getenv("ASSET_STORAGE", "/data/assets")
).resolve()

ASPECT_RATIO_DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


class ProductionRenderError(ValueError):
    pass


def renderer_request(
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    url = f"{VIDEO_RENDERER_URL}{path}"
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProductionRenderError(
            f"Video renderer error: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProductionRenderError(
            f"Cannot connect to video renderer: {exc}"
        ) from exc


def build_render_manifest(job: VideoJob, db) -> dict:
    plan_data = (job.input_data or {}).get("video_plan")

    if not plan_data:
        raise ProductionRenderError(
            "Video job does not contain a storyboard"
        )

    plan = VideoPlan.model_validate(plan_data)
    width, height = ASPECT_RATIO_DIMENSIONS[plan.aspect_ratio]
    scenes = []

    for scene in plan.scenes:
        video_asset = db.query(VideoAsset).filter(
            VideoAsset.job_id == job.id,
            VideoAsset.scene_number == scene.scene_number,
            VideoAsset.asset_type == "video",
            VideoAsset.status == "completed",
            VideoAsset.review_status == "approved",
        ).order_by(
            VideoAsset.created_at.desc()
        ).first()

        asset = video_asset or db.query(VideoAsset).filter(
            VideoAsset.job_id == job.id,
            VideoAsset.scene_number == scene.scene_number,
            VideoAsset.asset_type == "image",
            VideoAsset.status == "completed",
            VideoAsset.review_status == "approved",
        ).order_by(
            VideoAsset.created_at.desc()
        ).first()

        if not asset or not asset.storage_path:
            raise ProductionRenderError(
                f"Scene {scene.scene_number} is not ready to render"
            )

        asset_path = Path(asset.storage_path).resolve()

        try:
            asset_path.relative_to(ASSET_STORAGE)
        except ValueError as exc:
            raise ProductionRenderError(
                f"Invalid asset path for scene {scene.scene_number}"
            ) from exc

        if not asset_path.is_file():
            raise ProductionRenderError(
                f"Asset file is missing for scene {scene.scene_number}"
            )

        scenes.append({
            "scene_number": scene.scene_number,
            "duration_seconds": scene.duration_seconds,
            "visual_type": asset.asset_type,
            "asset_path": str(asset_path),
            "narration": scene.narration,
            "on_screen_text": scene.on_screen_text,
            "transition": scene.transition,
            "animation": {
                "type": "slow_zoom_in",
            },
        })

    return {
        "composition_id": "DynamicVideo",
        "title": plan.title,
        "brand_name": "IoTelliGen",
        "accent_color": "#16C79A",
        "fps": 30,
        "width": width,
        "height": height,
        "duration_seconds": plan.duration_seconds,
        "scenes": scenes,
    }


def advance_autonomous_production(job_id: str) -> None:
    db = SessionLocal()

    try:
        job = db.query(VideoJob).filter(
            VideoJob.id == job_id
        ).first()

        if not job:
            return

        if (job.input_data or {}).get("production_mode") != "autonomous":
            return

        if job.status != "assets_pending":
            return

        plan_data = (job.input_data or {}).get("video_plan")

        if not plan_data:
            job.status = "failed"
            job.error_message = "Video job does not contain a storyboard"
            db.commit()
            return

        plan = VideoPlan.model_validate(plan_data)
        assets = []

        for scene in plan.scenes:
            asset = db.query(VideoAsset).filter(
                VideoAsset.job_id == job.id,
                VideoAsset.scene_number == scene.scene_number,
                VideoAsset.asset_type == "image",
            ).order_by(
                VideoAsset.created_at.desc()
            ).first()

            if not asset or asset.status in ("pending", "generating"):
                return

            if asset.status != "completed":
                job.status = "failed"
                job.error_message = (
                    "At least one scene asset could not be generated"
                )
                db.commit()
                return

            assets.append(asset)

        for asset in assets:
            if asset.review_status != "approved":
                asset.review_status = "approved"

        db.commit()

        claimed = db.query(VideoJob).filter(
            VideoJob.id == job.id,
            VideoJob.status == "assets_pending",
        ).update(
            {
                "status": "submitting",
                "progress": 0,
                "error_message": None,
            },
            synchronize_session=False,
        )
        db.commit()

        if claimed != 1:
            return

        db.refresh(job)
        manifest = build_render_manifest(job, db)
        renderer_response = renderer_request(
            "POST",
            "/render",
            manifest,
        )

        job.renderer_job_id = str(renderer_response["job_id"])
        job.status = "queued"
        db.commit()
    except Exception as exc:
        db.rollback()

        job = db.query(VideoJob).filter(
            VideoJob.id == job_id
        ).first()

        if job and job.status == "submitting":
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()

        logger.exception(
            "Autonomous production failed for video job %s",
            job_id,
        )
    finally:
        db.close()
