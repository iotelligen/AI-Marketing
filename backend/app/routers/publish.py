import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.publish_account import PublishAccount
from app.models.publish_job import PublishJob
from app.providers.publish.base import supported_platforms
from app.services.publish_service import (
    create_account,
    create_and_run_publish_jobs,
    list_ready_versions,
    normalize_platforms,
    publish_dry_run_default,
    retry_publish_job,
    serialize_account,
    serialize_publish_job,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publish", tags=["Publish"])


class PublishAccountCreate(BaseModel):
    workspace_slug: str = Field(min_length=2, max_length=100)
    platform: Literal[
        "linkedin",
        "facebook",
        "instagram",
        "youtube",
        "tiktok",
    ] = "linkedin"
    display_name: str = Field(min_length=1, max_length=200)
    access_token: str = Field(min_length=10, max_length=4000)
    author_urn: str = Field(
        min_length=5,
        max_length=200,
        description="urn:li:person:... or urn:li:organization:...",
    )


class PublishJobsCreate(BaseModel):
    version_id: str = Field(min_length=36, max_length=36)
    platforms: list[str] = Field(default_factory=lambda: ["linkedin"])
    caption: str | None = Field(default=None, max_length=3000)
    dry_run: bool | None = None
    requested_by: Literal["n8n", "api", "dashboard"] = "api"


class PublishRetryRequest(BaseModel):
    dry_run: bool | None = None


@router.get("/platforms")
def list_platforms():
    return {
        "platforms": list(supported_platforms()),
        "live": ["linkedin"],
        "dry_run_default": publish_dry_run_default(),
    }


@router.get("/ready")
def get_ready_to_publish(
    workspace_slug: str | None = Query(default=None),
    platforms: str | None = Query(
        default="linkedin",
        description="Comma-separated platforms, e.g. linkedin",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    platform_list = [
        item.strip()
        for item in (platforms or "linkedin").split(",")
        if item.strip()
    ]

    try:
        items = list_ready_versions(
            db,
            workspace_slug=workspace_slug,
            platforms=platform_list,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "total": len(items),
        "dry_run_default": publish_dry_run_default(),
        "items": items,
    }


@router.get("/accounts")
def list_accounts(
    workspace_slug: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(PublishAccount)

    if workspace_slug:
        query = query.filter(
            PublishAccount.workspace_slug == workspace_slug
        )

    if platform:
        query = query.filter(
            PublishAccount.platform == platform.strip().lower()
        )

    accounts = query.order_by(
        PublishAccount.created_at.desc()
    ).all()

    return {
        "total": len(accounts),
        "accounts": [serialize_account(account) for account in accounts],
    }


@router.post("/accounts", status_code=201)
def register_account(
    data: PublishAccountCreate,
    db: Session = Depends(get_db),
):
    try:
        account = create_account(
            db,
            workspace_slug=data.workspace_slug,
            platform=data.platform,
            display_name=data.display_name,
            credentials={
                "access_token": data.access_token,
                "author_urn": data.author_urn,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return serialize_account(account)


@router.delete("/accounts/{account_id}")
def disable_account(
    account_id: str,
    db: Session = Depends(get_db),
):
    account = db.query(PublishAccount).filter(
        PublishAccount.id == account_id
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Publish account not found")

    account.status = "disabled"
    db.commit()
    db.refresh(account)

    return serialize_account(account)


@router.post("/jobs", status_code=202)
def create_publish_jobs(
    data: PublishJobsCreate,
    db: Session = Depends(get_db),
):
    try:
        normalize_platforms(data.platforms)
        jobs = create_and_run_publish_jobs(
            db,
            version_id=data.version_id,
            platforms=data.platforms,
            caption=data.caption,
            dry_run=data.dry_run,
            requested_by=data.requested_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to create publish jobs")
        raise HTTPException(
            status_code=500,
            detail="Unable to create publish jobs",
        )

    return {
        "total": len(jobs),
        "dry_run_default": publish_dry_run_default(),
        "jobs": [serialize_publish_job(job) for job in jobs],
    }


@router.get("/jobs")
def list_publish_jobs(
    workspace_slug: str | None = Query(default=None),
    version_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(PublishJob)

    if workspace_slug:
        query = query.filter(PublishJob.workspace_slug == workspace_slug)

    if version_id:
        query = query.filter(PublishJob.version_id == version_id)

    if status:
        query = query.filter(PublishJob.status == status)

    jobs = (
        query
        .order_by(PublishJob.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "total": len(jobs),
        "jobs": [serialize_publish_job(job) for job in jobs],
    }


@router.get("/jobs/{publish_job_id}")
def get_publish_job(
    publish_job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(PublishJob).filter(
        PublishJob.id == publish_job_id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Publish job not found")

    return serialize_publish_job(job)


@router.post("/jobs/{publish_job_id}/retry", status_code=202)
def retry_job(
    publish_job_id: str,
    data: PublishRetryRequest | None = None,
    db: Session = Depends(get_db),
):
    dry_run = data.dry_run if data else None

    try:
        job = retry_publish_job(
            db,
            publish_job_id,
            dry_run=dry_run,
        )
    except ValueError as exc:
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message)

        raise HTTPException(status_code=409, detail=message)

    return serialize_publish_job(job)
