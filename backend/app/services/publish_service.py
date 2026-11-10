import logging
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, exists
from sqlalchemy.orm import Session

from app.models.publish_account import PublishAccount
from app.models.publish_job import PublishJob
from app.models.video_job import VideoJob
from app.models.video_version import VideoVersion
from app.providers.linkedin.publish_provider import (
    LinkedInPublishError,
    LinkedInPublishProvider,
)
from app.providers.publish.base import (
    PublishResult,
    get_publisher,
    supported_platforms,
)
from app.services.brand_service import get_brand_profile


logger = logging.getLogger(__name__)

VIDEO_RENDERER_URL = os.getenv(
    "VIDEO_RENDERER_URL",
    "http://video-renderer:8100",
).rstrip("/")

PUBLIC_API_BASE_URL = os.getenv(
    "PUBLIC_API_BASE_URL",
    "http://localhost:8000",
).rstrip("/")


def publish_dry_run_default() -> bool:
    return os.getenv("PUBLISH_DRY_RUN", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def normalize_platforms(platforms: list[str] | None) -> list[str]:
    if not platforms:
        return ["linkedin"]

    normalized = []

    for platform in platforms:
        value = platform.strip().lower()

        if value not in supported_platforms():
            raise ValueError(f"Unsupported platform: {platform}")

        if value not in normalized:
            normalized.append(value)

    return normalized


def build_caption(video_job: VideoJob, db: Session) -> str:
    plan = (video_job.input_data or {}).get("video_plan") or {}
    title = plan.get("title") or video_job.title or "New video"
    concept = (plan.get("concept") or "").strip()
    cta = (plan.get("cta") or "").strip()

    lines = [title]

    if concept:
        lines.append("")
        lines.append(concept[:500])

    if cta:
        lines.append("")
        lines.append(cta)

    brand = get_brand_profile(db, video_job.workspace_slug)

    if brand and brand.website:
        lines.append("")
        lines.append(brand.website)

    return "\n".join(lines).strip()


def serialize_account(account: PublishAccount) -> dict[str, Any]:
    credentials = account.credentials or {}

    return {
        "account_id": account.id,
        "workspace_slug": account.workspace_slug,
        "platform": account.platform,
        "display_name": account.display_name,
        "status": account.status,
        "has_access_token": bool(credentials.get("access_token")),
        "has_author_urn": bool(credentials.get("author_urn")),
        "author_urn": credentials.get("author_urn"),
        "last_verified_at": account.last_verified_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def serialize_publish_job(job: PublishJob) -> dict[str, Any]:
    return {
        "publish_job_id": job.id,
        "version_id": job.version_id,
        "video_job_id": job.video_job_id,
        "workspace_slug": job.workspace_slug,
        "platform": job.platform,
        "account_id": job.account_id,
        "status": job.status,
        "caption": job.caption,
        "idempotency_key": job.idempotency_key,
        "remote_post_id": job.remote_post_id,
        "remote_url": job.remote_url,
        "error_message": job.error_message,
        "attempt_count": job.attempt_count,
        "requested_by": job.requested_by,
        "result_metadata": job.result_metadata,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "published_at": job.published_at,
    }


def _successful_publish_exists(
    db: Session,
    version_id: str,
    platform: str,
) -> bool:
    return db.query(
        exists().where(
            and_(
                PublishJob.version_id == version_id,
                PublishJob.platform == platform,
                PublishJob.status.in_(("published", "dry_run")),
            )
        )
    ).scalar()


def list_ready_versions(
    db: Session,
    *,
    workspace_slug: str | None = None,
    platforms: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    platforms = normalize_platforms(platforms)
    limit = max(1, min(limit, 50))

    query = (
        db.query(VideoVersion, VideoJob)
        .join(VideoJob, VideoJob.id == VideoVersion.job_id)
        .filter(
            VideoVersion.approval_status == "approved",
            VideoJob.status == "completed",
        )
        .order_by(VideoVersion.created_at.asc())
    )

    if workspace_slug:
        query = query.filter(VideoJob.workspace_slug == workspace_slug)

    rows = query.limit(limit * 5).all()
    ready = []

    for version, video_job in rows:
        missing_platforms = [
            platform
            for platform in platforms
            if not _successful_publish_exists(db, version.id, platform)
        ]

        if not missing_platforms:
            continue

        plan = (video_job.input_data or {}).get("video_plan") or {}
        brand = get_brand_profile(db, video_job.workspace_slug)

        ready.append({
            "version_id": version.id,
            "version_number": version.version_number,
            "video_job_id": video_job.id,
            "workspace_slug": video_job.workspace_slug,
            "title": plan.get("title") or video_job.title,
            "caption": build_caption(video_job, db),
            "platforms": missing_platforms,
            "video_url": (
                f"{PUBLIC_API_BASE_URL}/videos/jobs/{video_job.id}/video"
            ),
            "duration_seconds": version.duration_seconds,
            "width": version.width,
            "height": version.height,
            "approved_at": version.reviewed_at,
            "brand": {
                "name": brand.brand_name if brand else None,
                "website": brand.website if brand else None,
            },
        })

        if len(ready) >= limit:
            break

    return ready


def get_active_account(
    db: Session,
    *,
    workspace_slug: str,
    platform: str,
) -> PublishAccount | None:
    return (
        db.query(PublishAccount)
        .filter(
            PublishAccount.workspace_slug == workspace_slug,
            PublishAccount.platform == platform,
            PublishAccount.status == "active",
        )
        .order_by(PublishAccount.created_at.desc())
        .first()
    )


def create_account(
    db: Session,
    *,
    workspace_slug: str,
    platform: str,
    display_name: str,
    credentials: dict[str, Any],
) -> PublishAccount:
    platform = platform.strip().lower()

    if platform not in supported_platforms():
        raise ValueError(f"Unsupported platform: {platform}")

    account = PublishAccount(
        workspace_slug=workspace_slug,
        platform=platform,
        display_name=display_name.strip(),
        status="active",
        credentials=credentials or {},
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def fetch_video_bytes(video_job: VideoJob) -> bytes:
    if not video_job.renderer_job_id:
        raise ValueError("Rendered video is not available for this job")

    url = f"{VIDEO_RENDERER_URL}/videos/{video_job.renderer_job_id}"
    request = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"Unable to download rendered video: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ValueError(
            f"Unable to download rendered video: {exc}"
        ) from exc

    if not data:
        raise ValueError("Downloaded video file is empty")

    return data


def _idempotency_key(version_id: str, platform: str) -> str:
    return f"{version_id}:{platform}"


def _find_existing_success(
    db: Session,
    version_id: str,
    platform: str,
) -> PublishJob | None:
    return (
        db.query(PublishJob)
        .filter(
            PublishJob.version_id == version_id,
            PublishJob.platform == platform,
            PublishJob.status.in_(("published", "dry_run")),
        )
        .order_by(PublishJob.created_at.desc())
        .first()
    )


def _run_linkedin_live(
    *,
    account: PublishAccount,
    video_bytes: bytes,
    caption: str,
    title: str,
    filename: str,
) -> PublishResult:
    provider = LinkedInPublishProvider(account.credentials or {})
    result = provider.publish_video(
        video_bytes=video_bytes,
        caption=caption,
        title=title,
        filename=filename,
    )

    return PublishResult(
        status="published",
        remote_post_id=result.get("remote_post_id"),
        remote_url=result.get("remote_url"),
        metadata=result,
    )


def run_publish_job(
    db: Session,
    publish_job: PublishJob,
    *,
    dry_run: bool,
) -> PublishJob:
    video_job = db.query(VideoJob).filter(
        VideoJob.id == publish_job.video_job_id
    ).first()

    version = db.query(VideoVersion).filter(
        VideoVersion.id == publish_job.version_id
    ).first()

    if not video_job or not version:
        publish_job.status = "failed"
        publish_job.error_message = "Video job or version no longer exists"
        db.commit()
        db.refresh(publish_job)
        return publish_job

    if version.approval_status != "approved":
        publish_job.status = "failed"
        publish_job.error_message = (
            "Only approved video versions can be published"
        )
        db.commit()
        db.refresh(publish_job)
        return publish_job

    publish_job.status = "publishing"
    publish_job.attempt_count = (publish_job.attempt_count or 0) + 1
    publish_job.error_message = None
    db.commit()

    account = None

    if publish_job.account_id:
        account = db.query(PublishAccount).filter(
            PublishAccount.id == publish_job.account_id
        ).first()
    else:
        account = get_active_account(
            db,
            workspace_slug=publish_job.workspace_slug,
            platform=publish_job.platform,
        )
        if account:
            publish_job.account_id = account.id

    try:
        if dry_run:
            video_bytes = fetch_video_bytes(video_job)
            publish_job.status = "dry_run"
            publish_job.remote_post_id = f"dry-run-{uuid.uuid4().hex[:12]}"
            publish_job.published_at = datetime.now(timezone.utc)
            publish_job.result_metadata = {
                "dry_run": True,
                "platform": publish_job.platform,
                "byte_size": len(video_bytes),
                "account_id": account.id if account else None,
                "caption_preview": publish_job.caption[:280],
                "title": video_job.title,
            }
            db.commit()
            db.refresh(publish_job)
            return publish_job

        if publish_job.platform != "linkedin":
            publisher = get_publisher(publish_job.platform)
            # Stub platforms are callables, not provider classes.
            result = publisher()
            publish_job.status = "failed"
            publish_job.error_message = result.error_message
            publish_job.result_metadata = result.metadata
            db.commit()
            db.refresh(publish_job)
            return publish_job

        if not account:
            raise ValueError(
                "No active LinkedIn publish account is configured "
                f"for workspace '{publish_job.workspace_slug}'"
            )

        video_bytes = fetch_video_bytes(video_job)
        plan = (video_job.input_data or {}).get("video_plan") or {}
        title = plan.get("title") or video_job.title or "Video"
        filename = version.filename or f"{video_job.id}.mp4"

        result = _run_linkedin_live(
            account=account,
            video_bytes=video_bytes,
            caption=publish_job.caption,
            title=title,
            filename=filename,
        )

        publish_job.status = "published"
        publish_job.remote_post_id = result.remote_post_id
        publish_job.remote_url = result.remote_url
        publish_job.result_metadata = result.metadata
        publish_job.published_at = datetime.now(timezone.utc)
        publish_job.error_message = None
        db.commit()
        db.refresh(publish_job)
        return publish_job

    except (LinkedInPublishError, ValueError) as exc:
        logger.warning(
            "Publish job %s failed for platform %s: %s",
            publish_job.id,
            publish_job.platform,
            exc,
        )
        publish_job.status = "failed"
        publish_job.error_message = str(exc)[:4000]
        db.commit()
        db.refresh(publish_job)
        return publish_job

    except Exception as exc:
        logger.exception(
            "Unexpected publish failure for job %s",
            publish_job.id,
        )
        publish_job.status = "failed"
        publish_job.error_message = str(exc)[:4000]
        db.commit()
        db.refresh(publish_job)
        return publish_job


def create_and_run_publish_jobs(
    db: Session,
    *,
    version_id: str,
    platforms: list[str] | None = None,
    caption: str | None = None,
    dry_run: bool | None = None,
    requested_by: str = "api",
) -> list[PublishJob]:
    platforms = normalize_platforms(platforms)

    if dry_run is None:
        dry_run = publish_dry_run_default()

    version = db.query(VideoVersion).filter(
        VideoVersion.id == version_id
    ).first()

    if not version:
        raise ValueError("Video version not found")

    if version.approval_status != "approved":
        raise ValueError(
            "Only approved video versions can be published"
        )

    video_job = db.query(VideoJob).filter(
        VideoJob.id == version.job_id
    ).first()

    if not video_job:
        raise ValueError("Video job not found")

    if video_job.status != "completed":
        raise ValueError(
            f"Video job is not completed (status={video_job.status})"
        )

    final_caption = (caption or "").strip() or build_caption(video_job, db)
    results: list[PublishJob] = []

    for platform in platforms:
        existing = _find_existing_success(db, version.id, platform)

        if existing:
            results.append(existing)
            continue

        account = get_active_account(
            db,
            workspace_slug=video_job.workspace_slug,
            platform=platform,
        )

        publish_job = PublishJob(
            version_id=version.id,
            video_job_id=video_job.id,
            workspace_slug=video_job.workspace_slug,
            platform=platform,
            account_id=account.id if account else None,
            status="queued",
            caption=final_caption,
            idempotency_key=_idempotency_key(version.id, platform),
            requested_by=requested_by,
            result_metadata={},
        )

        # Handle a race where another worker already inserted the same key.
        existing_by_key = db.query(PublishJob).filter(
            PublishJob.idempotency_key == publish_job.idempotency_key
        ).first()

        if existing_by_key and existing_by_key.status in (
            "published",
            "dry_run",
        ):
            results.append(existing_by_key)
            continue

        if existing_by_key and existing_by_key.status == "failed":
            publish_job = existing_by_key
            publish_job.caption = final_caption
            publish_job.requested_by = requested_by
            publish_job.account_id = account.id if account else None
        elif existing_by_key:
            results.append(existing_by_key)
            continue
        else:
            db.add(publish_job)

        db.commit()
        db.refresh(publish_job)

        results.append(
            run_publish_job(db, publish_job, dry_run=dry_run)
        )

    return results


def retry_publish_job(
    db: Session,
    publish_job_id: str,
    *,
    dry_run: bool | None = None,
) -> PublishJob:
    publish_job = db.query(PublishJob).filter(
        PublishJob.id == publish_job_id
    ).first()

    if not publish_job:
        raise ValueError("Publish job not found")

    if publish_job.status in ("published", "dry_run"):
        return publish_job

    if publish_job.status == "publishing":
        raise ValueError("Publish job is already running")

    if dry_run is None:
        dry_run = publish_dry_run_default()

    return run_publish_job(db, publish_job, dry_run=dry_run)
