import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.marketing_post import MarketingPost
from app.providers.linkedin.publish_provider import (
    LinkedInPublishError,
    LinkedInPublishProvider,
)
from app.services.publish_service import (
    get_active_account,
    publish_dry_run_default,
)


logger = logging.getLogger(__name__)


TERMINAL_PUBLISH_STATUSES = ("published", "dry_run")


def build_post_caption(post: MarketingPost) -> str:
    parts: list[str] = []

    title = (post.title or "").strip()
    content = (post.content or "").strip()
    hashtags = [
        tag.strip()
        for tag in (post.hashtags or [])
        if isinstance(tag, str) and tag.strip()
    ]

    if title:
        parts.append(title)

    if content:
        parts.append(content)

    if hashtags:
        parts.append(" ".join(hashtags))

    return "\n\n".join(parts).strip()


def serialize_marketing_post(
    post: MarketingPost,
    *,
    version_id: str | None = None,
    version_number: int | None = None,
    skills_used: list | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": post.id,
        "workspace_slug": post.workspace_slug,
        "topic": post.topic,
        "platform": post.platform,
        "target_audience": post.target_audience,
        "objective": post.objective,
        "language": post.language,
        "title": post.title,
        "content": post.content,
        "hashtags": post.hashtags or [],
        "status": post.status,
        "llm_model": post.llm_model,
        "sources": post.sources or [],
        "caption_preview": build_post_caption(post)[:500],
        "remote_post_id": post.remote_post_id,
        "remote_url": post.remote_url,
        "publish_error": post.publish_error,
        "publish_metadata": post.publish_metadata or {},
        "published_at": post.published_at,
        "created_at": post.created_at,
        "dry_run_default": publish_dry_run_default(),
    }

    if version_id is not None:
        payload["version_id"] = version_id

    if version_number is not None:
        payload["version_number"] = version_number

    if skills_used is not None:
        payload["skills_used"] = skills_used

    return payload


def approve_marketing_post(
    db: Session,
    post: MarketingPost,
) -> MarketingPost:
    if post.status in TERMINAL_PUBLISH_STATUSES:
        raise ValueError(
            f"Post is already {post.status} and cannot be re-approved"
        )

    post.status = "approved"
    post.publish_error = None
    db.commit()
    db.refresh(post)
    return post


def publish_marketing_post(
    db: Session,
    post: MarketingPost,
    *,
    dry_run: bool | None = None,
    auto_approve: bool = False,
    requested_by: str = "api",
) -> MarketingPost:
    if dry_run is None:
        dry_run = publish_dry_run_default()

    if post.status in TERMINAL_PUBLISH_STATUSES:
        return post

    if post.status == "draft":
        if not auto_approve:
            raise ValueError(
                "Post must be approved before publishing"
            )
        post.status = "approved"

    if post.status != "approved":
        raise ValueError(
            f"Cannot publish post in status '{post.status}'"
        )

    caption = build_post_caption(post)

    if not caption:
        raise ValueError("Post caption is empty")

    platform = (post.platform or "").strip().lower()
    account = get_active_account(
        db,
        workspace_slug=post.workspace_slug,
        platform=platform,
    )

    try:
        if dry_run:
            post.status = "dry_run"
            post.remote_post_id = f"dry-run-{uuid.uuid4().hex[:12]}"
            post.remote_url = None
            post.publish_error = None
            post.published_at = datetime.now(timezone.utc)
            post.publish_metadata = {
                "dry_run": True,
                "platform": platform,
                "account_id": account.id if account else None,
                "requested_by": requested_by,
                "caption_preview": caption[:280],
                "content_type": "text",
            }
            db.commit()
            db.refresh(post)
            return post

        if platform != "linkedin":
            raise ValueError(
                f"Live publishing is not configured for platform '{platform}'"
            )

        if not account:
            raise ValueError(
                "No active LinkedIn publish account is configured "
                f"for workspace '{post.workspace_slug}'"
            )

        provider = LinkedInPublishProvider(account.credentials or {})
        result = provider.publish_text(text=caption)

        post.status = "published"
        post.remote_post_id = result.get("remote_post_id")
        post.remote_url = result.get("remote_url")
        post.publish_error = None
        post.published_at = datetime.now(timezone.utc)
        post.publish_metadata = {
            **(result or {}),
            "account_id": account.id,
            "requested_by": requested_by,
            "dry_run": False,
        }
        db.commit()
        db.refresh(post)
        return post

    except (LinkedInPublishError, ValueError) as exc:
        logger.warning(
            "Marketing post %s publish failed: %s",
            post.id,
            exc,
        )
        post.publish_error = str(exc)[:4000]
        # Keep approved so the user can fix credentials and retry.
        post.status = "approved"
        db.commit()
        db.refresh(post)
        return post

    except Exception as exc:
        logger.exception(
            "Unexpected marketing publish failure for post %s",
            post.id,
        )
        post.publish_error = str(exc)[:4000]
        post.status = "approved"
        db.commit()
        db.refresh(post)
        return post
