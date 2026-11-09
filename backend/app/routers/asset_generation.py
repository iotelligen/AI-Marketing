import os

import logging
from datetime import datetime, timezone
from pathlib import Path
import os

from pydantic import BaseModel, Field

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.video_job import VideoJob
from app.models.video_asset import VideoAsset
from app.services.asset_service import enqueue_image_generation


router = APIRouter(
    prefix="/videos",
    tags=["Video Assets"],
)


class ImageGenerationRequest(BaseModel):
    scene_number: int = Field(ge=1)
    prompt: str = Field(min_length=5, max_length=5000)
    aspect_ratio: str = Field(default="9:16")

class AssetReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=2000)


def serialize_asset(asset: VideoAsset) -> dict:
    """Return public asset metadata without exposing filesystem paths."""
    return {
        "asset_id": asset.id,
        "job_id": asset.job_id,
        "scene_number": asset.scene_number,
        "asset_type": asset.asset_type,
        "provider": asset.provider,
        "model": asset.model,
        "status": asset.status,
        "filename": asset.filename,
        "mime_type": asset.mime_type,
        "error_message": asset.error_message,
        "metadata": asset.asset_metadata,
        "review_status": asset.review_status,
	"reviewed_at": asset.reviewed_at,
	"review_note": asset.review_note,
	"created_at": asset.created_at,
        "file_url": (
            f"/videos/assets/{asset.id}/file"
            if asset.status == "completed" and asset.storage_path
            else None
        ),
    }


def resolve_asset_file(asset: VideoAsset) -> Path:
    """
    Resolve an asset file and ensure it remains inside ASSET_STORAGE.
    """
    if asset.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Asset is not completed. Current status: {asset.status}",
        )

    if not asset.storage_path:
        raise HTTPException(
            status_code=404,
            detail="Asset file path is not available",
        )

    storage_root = Path(
        os.getenv("ASSET_STORAGE", "/data/assets")
    ).resolve()

    try:
        file_path = Path(asset.storage_path).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(
            status_code=404,
            detail="Asset file not found on storage",
        )

    if not file_path.is_relative_to(storage_root):
        raise HTTPException(
            status_code=403,
            detail="Invalid asset storage path",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Asset file not found",
        )

    return file_path


@router.post(
    "/jobs/{job_id}/assets/images",
    status_code=202,
)
def create_image_asset(
    job_id: str,
    data: ImageGenerationRequest,
    db: Session = Depends(get_db),
):
    allowed_ratios = ("9:16", "16:9", "1:1")

    if data.aspect_ratio not in allowed_ratios:
        raise HTTPException(
            status_code=422,
            detail=f"Aspect ratio must be one of {allowed_ratios}",
        )

    video_job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not video_job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    try:
        return enqueue_image_generation(
            job_id=job_id,
            scene_number=data.scene_number,
            prompt=data.prompt,
            aspect_ratio=data.aspect_ratio,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to enqueue image generation",
        )


@router.get("/jobs/{job_id}/assets")
def list_video_assets(
    job_id: str,
    scene_number: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    video_job = db.query(VideoJob).filter(
        VideoJob.id == job_id
    ).first()

    if not video_job:
        raise HTTPException(
            status_code=404,
            detail="Video job not found",
        )

    query = db.query(VideoAsset).filter(
        VideoAsset.job_id == job_id
    )

    if scene_number is not None:
        query = query.filter(
            VideoAsset.scene_number == scene_number
        )

    if status is not None:
        allowed_statuses = (
            "pending",
            "generating",
            "completed",
            "failed",
        )

        if status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Status must be one of {allowed_statuses}",
            )

        query = query.filter(
            VideoAsset.status == status
        )

    total = query.count()

    assets = (
        query
        .order_by(
            VideoAsset.scene_number.asc().nullslast(),
            VideoAsset.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "job_id": job_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "assets": [
            serialize_asset(asset)
            for asset in assets
        ],
    }


@router.get("/assets/{asset_id}/file")
def get_video_asset_file(
    asset_id: str,
    db: Session = Depends(get_db),
):
    asset = db.query(VideoAsset).filter(
        VideoAsset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Video asset not found",
        )

    file_path = resolve_asset_file(asset)

    return FileResponse(
        path=file_path,
        media_type=asset.mime_type or "application/octet-stream",
        filename=asset.filename,
        content_disposition_type="inline",
    )


@router.get("/assets/{asset_id}")
def get_video_asset(
    asset_id: str,
    db: Session = Depends(get_db),
):
    asset = db.query(VideoAsset).filter(
        VideoAsset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Video asset not found",
        )

    return serialize_asset(asset)

@router.post("/assets/{asset_id}/regenerate", status_code=202)
def regenerate_video_asset(
    asset_id: str,
    db: Session = Depends(get_db),
):
    asset = db.query(VideoAsset).filter(
        VideoAsset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(404, "Video asset not found")

    if asset.asset_type != "image":
        raise HTTPException(422, "Only image assets can be regenerated")

    if asset.status in ("pending", "generating"):
        raise HTTPException(
            409,
            "Asset generation is already in progress",
        )

    if not asset.prompt:
        raise HTTPException(
            422,
            "Original generation prompt is unavailable",
        )

    metadata = asset.asset_metadata or {}
    aspect_ratio = metadata.get("aspect_ratio", "9:16")

    try:
        result = enqueue_image_generation(
            job_id=asset.job_id,
            scene_number=asset.scene_number,
            prompt=asset.prompt,
            aspect_ratio=aspect_ratio,
        )

        return {
            **result,
            "source_asset_id": asset.id,
            "message": "New generation queued",
        }

    except Exception:
        logging.exception("Asset regeneration enqueue failed")
        raise HTTPException(
            503,
            "Unable to enqueue asset regeneration",
        )

@router.patch("/assets/{asset_id}/review")
def review_video_asset(
    asset_id: str,
    data: AssetReviewRequest,
    db: Session = Depends(get_db),
):
    asset = db.query(VideoAsset).filter(
        VideoAsset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(404, "Video asset not found")

    if asset.status != "completed":
        raise HTTPException(
            409,
            "Only completed assets can be reviewed",
        )

    asset.review_status = data.decision
    asset.reviewed_at = datetime.now(timezone.utc)
    asset.review_note = data.note

    db.commit()
    db.refresh(asset)

    return serialize_asset(asset)

@router.delete("/assets/{asset_id}", status_code=200)
def delete_video_asset(
    asset_id: str,
    db: Session = Depends(get_db),
):
    asset = db.query(VideoAsset).filter(
        VideoAsset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(404, "Video asset not found")

    if asset.status in ("pending", "generating"):
        raise HTTPException(
            409,
            "Cannot delete an asset while generation is active",
        )

    file_path = None

    if asset.storage_path:
        storage_root = Path(
            os.getenv("ASSET_STORAGE", "/data/assets")
        ).resolve()

        candidate = Path(asset.storage_path).resolve()

        if not candidate.is_relative_to(storage_root):
            raise HTTPException(
                403,
                "Invalid asset storage path",
            )

        file_path = candidate

    db.delete(asset)
    db.commit()

    file_deleted = False

    if file_path and file_path.is_file():
        try:
            file_path.unlink()
            file_deleted = True
        except OSError:
            logging.exception(
                "Database asset deleted but physical file cleanup failed"
            )

    return {
        "asset_id": asset_id,
        "deleted": True,
        "file_deleted": file_deleted,
    }
