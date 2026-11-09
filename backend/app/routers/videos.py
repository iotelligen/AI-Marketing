
import json
import os
import urllib.error
import urllib.request

import logging

logger = logging.getLogger(__name__)

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.video_job import VideoJob
from app.models.video_version import VideoVersion

from app.schemas.video_planner import (
    VideoPlanRequest,
    VideoPlanRevisionRequest,
)

from app.services.video_planner_service import (
    generate_video_plan,
    revise_video_plan,
)

from pathlib import Path

from app.models.video_asset import VideoAsset

from app.schemas.video_planner import (
    VideoPlan,
    VideoPlanRequest,
    VideoPlanRevisionRequest,
)

from app.services.asset_service import enqueue_image_generation

router = APIRouter(prefix="/videos", tags=["Videos"])

VIDEO_RENDERER_URL = os.getenv(
    "VIDEO_RENDERER_URL",
    "http://video-renderer:8100",
).rstrip("/")


class VideoJobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    prompt: str | None = None
    workspace_slug: str = Field(
        default="iotelligen_marketing",
        min_length=2,
        max_length=100,
    )
    template_id: str = Field(
        default="IndustrialPromo",
        max_length=100,
    )
    input_data: dict[str, Any] = Field(default_factory=dict)

class VideoJobFromPlan(BaseModel):
    plan: VideoPlan

    workspace_slug: str = Field(
        default="iotelligen-marketing",
        min_length=2,
        max_length=100,
    )

    prompt: str | None = None


ASSET_STORAGE = Path(
    os.getenv("ASSET_STORAGE", "/data/assets")
).resolve()

ASPECT_RATIO_DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

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
        raise HTTPException(
            status_code=502,
            detail=f"Video renderer error: {detail}",
        )

    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to video renderer: {exc}",
        )


@router.post("/jobs", status_code=202)
def create_video_job(
    data: VideoJobCreate,
    db: Session = Depends(get_db),
):
    if data.template_id != "IndustrialPromo":
        raise HTTPException(
            status_code=400,
            detail="Currently only IndustrialPromo is supported",
        )

    input_data = dict(data.input_data)
    input_data.setdefault("title", data.title)

    job = VideoJob(
        title=data.title,
        prompt=data.prompt,
        workspace_slug=data.workspace_slug,
        template_id=data.template_id,
        input_data=input_data,
        status="submitting",
        progress=0,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        renderer_response = renderer_request(
            "POST",
            "/render",
            input_data,
        )

        job.renderer_job_id = str(renderer_response["job_id"])
        job.status = "queued"

        db.commit()
        db.refresh(job)

    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise

    return {
        "job_id": job.id,
        "renderer_job_id": job.renderer_job_id,
        "title": job.title,
        "status": job.status,
        "progress": job.progress,
    }

@router.post("/jobs/from-plan", status_code=201)
def create_video_job_from_plan(
    data: VideoJobFromPlan,
    db: Session = Depends(get_db),
):
    plan = data.plan

    input_data = {
        "composition_id": "DynamicVideo",
        "title": plan.title,
        "brand_name": "IoTelliGen",
        "accent_color": "#16C79A",
        "fps": 30,
        "duration_seconds": plan.duration_seconds,
        "aspect_ratio": plan.aspect_ratio,
        "video_plan": plan.model_dump(),
    }

    job = VideoJob(
        title=plan.title,
        prompt=data.prompt or plan.concept,
        workspace_slug=data.workspace_slug,
        template_id="DynamicVideo",
        input_data=input_data,
        status="draft",
        progress=0,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "job_id": job.id,
        "title": job.title,
        "status": job.status,
        "scene_count": len(plan.scenes),
        "duration_seconds": plan.duration_seconds,
        "aspect_ratio": plan.aspect_ratio,
    }

@router.post("/jobs/{job_id}/assets/generate-from-plan", status_code=202)
def generate_assets_from_plan(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    if job.status not in ("draft", "assets_pending", "assets_ready"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate assets in status: {job.status}",
        )

    plan_data = (job.input_data or {}).get("video_plan")

    if not plan_data:
        raise HTTPException(
            status_code=422,
            detail="Video job does not contain a storyboard",
        )

    plan = VideoPlan.model_validate(plan_data)

    results = []

    for scene in plan.scenes:
        latest_asset = db.query(VideoAsset).filter(
            VideoAsset.job_id == job.id,
            VideoAsset.scene_number == scene.scene_number,
            VideoAsset.asset_type == "image",
        ).order_by(
            VideoAsset.created_at.desc()
        ).first()

        # Avoid duplicating work for assets already being generated
        # or completed and not rejected.
        if latest_asset:
            if latest_asset.status in ("pending", "generating"):
                results.append({
                    "scene_number": scene.scene_number,
                    "asset_id": latest_asset.id,
                    "status": latest_asset.status,
                    "action": "skipped",
                })
                continue

            if (
                latest_asset.status == "completed"
                and latest_asset.review_status != "rejected"
            ):
                results.append({
                    "scene_number": scene.scene_number,
                    "asset_id": latest_asset.id,
                    "status": latest_asset.status,
                    "review_status": latest_asset.review_status,
                    "action": "skipped",
                })
                continue

        try:
            enqueue_image_generation(
                job_id=job.id,
                scene_number=scene.scene_number,
                prompt=scene.visual_prompt,
                aspect_ratio=plan.aspect_ratio,
            )

            # Retrieve the asset created by the enqueue operation.
            asset = db.query(VideoAsset).filter(
                VideoAsset.job_id == job.id,
                VideoAsset.scene_number == scene.scene_number,
                VideoAsset.asset_type == "image",
                VideoAsset.prompt == scene.visual_prompt,
            ).order_by(
                VideoAsset.created_at.desc()
            ).first()

            results.append({
                "scene_number": scene.scene_number,
                "asset_id": asset.id if asset else None,
                "status": asset.status if asset else "queued",
                "action": "queued",
            })

        except Exception as exc:
            logger.exception(
                "Failed to enqueue image generation for scene %s",
                scene.scene_number,
            )

            results.append({
                "scene_number": scene.scene_number,
                "status": "failed",
                "error": str(exc),
            })

    if any(item["status"] in ("pending", "generating", "queued")
           for item in results):
        job.status = "assets_pending"

    db.commit()

    return {
        "job_id": job.id,
        "scene_count": len(plan.scenes),
        "results": results,
    }

@router.post("/jobs/{job_id}/render", status_code=202)
def render_video_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    if job.status in ("submitting", "queued", "rendering"):
        raise HTTPException(
            status_code=409,
            detail="Video job is already being rendered",
        )

    plan_data = (job.input_data or {}).get("video_plan")

    if not plan_data:
        raise HTTPException(
            status_code=422,
            detail="Video job does not contain a storyboard",
        )

    plan = VideoPlan.model_validate(plan_data)

    width, height = ASPECT_RATIO_DIMENSIONS[plan.aspect_ratio]

    scenes = []

    missing_scenes = []

    for scene in plan.scenes:
        asset = db.query(VideoAsset).filter(
            VideoAsset.job_id == job.id,
            VideoAsset.scene_number == scene.scene_number,
            VideoAsset.asset_type == "image",
            VideoAsset.status == "completed",
            VideoAsset.review_status == "approved",
        ).order_by(
            VideoAsset.created_at.desc()
        ).first()

        if not asset or not asset.storage_path:
            missing_scenes.append(scene.scene_number)
            continue

        asset_path = Path(asset.storage_path).resolve()

        # Ensure that the file belongs to the configured asset directory.
        try:
            asset_path.relative_to(ASSET_STORAGE)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid asset path for scene {scene.scene_number}",
            )

        if not asset_path.is_file():
            missing_scenes.append(scene.scene_number)
            continue

        scenes.append({
            "scene_number": scene.scene_number,
            "duration_seconds": scene.duration_seconds,
            "visual_type": "image",
            "asset_path": str(asset_path),
            "narration": scene.narration,
            "on_screen_text": scene.on_screen_text,
            "transition": scene.transition,
            "animation": {
                "type": "slow_zoom_in",
            },
        })

    if missing_scenes:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Every scene must have a completed, approved image "
                    "before rendering."
                ),
                "missing_or_unapproved_scenes": missing_scenes,
            },
        )

    manifest = {
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

    job.status = "submitting"
    job.progress = 0
    job.error_message = None
    db.commit()

    try:
        renderer_response = renderer_request(
            "POST",
            "/render",
            manifest,
        )

        job.renderer_job_id = str(
            renderer_response["job_id"]
        )
        job.status = "queued"

        db.commit()
        db.refresh(job)

    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise

    return {
        "job_id": job.id,
        "renderer_job_id": job.renderer_job_id,
        "status": job.status,
        "scene_count": len(scenes),
        "duration_seconds": plan.duration_seconds,
        "resolution": f"{width}x{height}",
    }

# ---------------------------------------------------------
# AI Video Planner
# ---------------------------------------------------------

@router.post("/plan")
def create_video_plan(
    data: VideoPlanRequest,
    db: Session = Depends(get_db),
):
    try:
        return generate_video_plan(
            request=data,
            db=db,
        )

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    except Exception:
        logger.exception("Video planning failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to generate video storyboard",
        )


@router.post("/plan/revise")
def revise_video_storyboard(
    data: VideoPlanRevisionRequest,
    db: Session = Depends(get_db),
):
    try:
        return revise_video_plan(
            plan=data.plan,
            instructions=data.instructions,
            workspace_slug=data.workspace_slug,
            db=db,
        )

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    except Exception:
        logger.exception("Video storyboard revision failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to revise video storyboard",
        )

def synchronize_video_job(
    job: VideoJob,
    db: Session,
):
    if not job.renderer_job_id:
        return job

    if job.status == "completed":
        if job.progress != 100:
            job.progress = 100
            db.commit()
            db.refresh(job)
        return job

    if job.status == "failed":
        return job

    renderer_response = renderer_request(
        "GET",
        f"/jobs/{job.renderer_job_id}",
    )

    renderer_status = renderer_response.get("status", "unknown")

    status_mapping = {
        "waiting": "queued",
        "delayed": "queued",
        "active": "rendering",
        "completed": "completed",
        "failed": "failed",
    }

    job.status = status_mapping.get(
        renderer_status,
        job.status,
    )

    if renderer_status == "completed":
        job.progress = 100

        result = renderer_response.get("result") or {}
        result["renderer_job_id"] = job.renderer_job_id

        job.output_file = result.get("output_file")

        existing_version = db.query(VideoVersion).filter(
            VideoVersion.job_id == job.id,
            VideoVersion.render_metadata["renderer_job_id"].as_string()
            == job.renderer_job_id,
        ).first()

        if job.output_file and not existing_version:
            max_version = db.query(
                func.max(VideoVersion.version_number)
            ).filter(
                VideoVersion.job_id == job.id
            ).scalar()

            version = VideoVersion(
                job_id=job.id,
                version_number=(max_version or 0) + 1,
                status="completed",
                filename=job.output_file,
                storage_path=f"/data/videos/{job.output_file}",
                duration_seconds=float(
                    result.get("duration_seconds", 30)
                ),
                width=int(result.get("width", 1080)),
                height=int(result.get("height", 1920)),
                fps=int(result.get("fps", 30)),
                render_metadata=result,
            )

            db.add(version)

    elif renderer_status == "failed":
        job.error_message = renderer_response.get(
            "error",
            "Video rendering failed",
        )

    else:
        job.progress = int(
            renderer_response.get("progress", 0)
        )

    db.commit()
    db.refresh(job)

    return job

@router.get("/jobs")
def list_video_jobs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 100))

    return db.query(VideoJob).order_by(
        VideoJob.created_at.desc()
    ).limit(limit).all()


@router.get("/jobs/{job_id}")
def get_video_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    return synchronize_video_job(job, db)


@router.get("/jobs/{job_id}/versions")
def list_video_versions(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    return db.query(VideoVersion).filter(
        VideoVersion.job_id == job_id
    ).order_by(
        VideoVersion.version_number.desc()
    ).all()


@router.get("/jobs/{job_id}/video")
def stream_video(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    job = synchronize_video_job(job, db)

    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Video is not ready. Current status: {job.status}",
        )

    if not job.renderer_job_id:
        raise HTTPException(
            status_code=404,
            detail="Renderer job ID not found",
        )

    request = urllib.request.Request(
        f"{VIDEO_RENDERER_URL}/videos/{job.renderer_job_id}",
        method="GET",
    )

    try:
        response = urllib.request.urlopen(request, timeout=30)

    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Renderer video error: {exc.code}",
        )

    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot retrieve rendered video: {exc}",
        )

    def video_iterator():
        try:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()

    headers = {
        "Content-Disposition": (
            f'inline; filename="{job.output_file or "video.mp4"}"'
        ),
    }

    content_length = response.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length

    return StreamingResponse(
        video_iterator(),
        media_type="video/mp4",
        headers=headers,
    )
