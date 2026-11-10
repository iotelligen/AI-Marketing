import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.marketing_post import MarketingPost
from app.models.marketing_post_version import MarketingPostVersion

from app.services.marketing_service import (
    retrieve_knowledge,
    generate_marketing_post,
    revise_marketing_post,
)

from app.services.agent_config_service import (
    load_agent_config,
    validate_workspace_access,
    get_agent_platforms,
)
from app.services.marketing_publish_service import (
    TERMINAL_PUBLISH_STATUSES,
    approve_marketing_post,
    publish_marketing_post,
    serialize_marketing_post,
)
from app.services.publish_service import publish_dry_run_default


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/marketing",
    tags=["Marketing Agent"],
)

MARKETING_AGENT_ID = "marketing"

DEFAULT_WORKSPACE = os.getenv(
    "MARKETING_WORKSPACE",
    "iotelligen-marketing",
)


def get_marketing_config():
    return load_agent_config(MARKETING_AGENT_ID)


def get_default_workspace(config):
    return config.get(
        "defaults", {}
    ).get("workspace", DEFAULT_WORKSPACE)


def validate_workspace(config, workspace):
    if not validate_workspace_access(config, workspace):
        raise HTTPException(
            status_code=403,
            detail=f"Agent cannot access workspace: {workspace}",
        )


def validate_platform(config, platform):
    platform = platform.strip().lower()

    if platform not in get_agent_platforms(config):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform: {platform}",
        )

    return platform


def validate_generation_permission(config):
    permissions = config.get("permissions", {})

    if not permissions.get("can_generate_posts", False):
        raise HTTPException(
            status_code=403,
            detail="Agent is not allowed to generate posts",
        )


def validate_revision_permission(config):
    permissions = config.get("permissions", {})

    if not permissions.get("can_revise_posts", False):
        raise HTTPException(
            status_code=403,
            detail="Agent is not allowed to revise posts",
        )


def validate_publish_permission(config):
    permissions = config.get("permissions", {})

    if not permissions.get("can_publish_posts", False):
        raise HTTPException(
            status_code=403,
            detail="Agent is not allowed to publish posts",
        )


def get_post_or_404(db: Session, post_id: str) -> MarketingPost:
    post = (
        db.query(MarketingPost)
        .filter(MarketingPost.id == post_id)
        .first()
    )

    if not post:
        raise HTTPException(
            status_code=404,
            detail="Marketing post not found",
        )

    return post


def resolve_post_workspace(post: MarketingPost, config) -> str:
    return (
        getattr(post, "workspace_slug", None)
        or get_default_workspace(config)
    )


class GeneratePostRequest(BaseModel):
    topic: str = Field(
        min_length=3,
        max_length=500,
    )

    platform: str = Field(
        default="linkedin",
        max_length=50,
    )

    target_audience: str = Field(
        default="Factory owners and production managers",
        max_length=500,
    )

    objective: str = Field(
        default="Generate awareness and leads",
        max_length=250,
    )

    language: str = Field(
        default="English",
        max_length=50,
    )

    workspace: str = Field(
        default=DEFAULT_WORKSPACE,
        max_length=100,
    )


class GenerateAndPublishRequest(GeneratePostRequest):
    dry_run: bool | None = None
    requested_by: Literal["n8n", "api", "dashboard"] = "api"


class RevisePostRequest(BaseModel):
    instructions: str = Field(
        min_length=3,
        max_length=4000,
    )


class PublishPostRequest(BaseModel):
    dry_run: bool | None = None
    auto_approve: bool = True
    requested_by: Literal["n8n", "api", "dashboard"] = "api"


def _create_generated_post(
    *,
    db: Session,
    data: GeneratePostRequest,
    config,
) -> tuple[MarketingPost, MarketingPostVersion]:
    validate_generation_permission(config)

    platform = validate_platform(
        config,
        data.platform,
    )

    validate_workspace(
        config,
        data.workspace,
    )

    knowledge, sources = retrieve_knowledge(
        db=db,
        workspace_slug=data.workspace,
        query=data.topic,
    )

    generated = generate_marketing_post(
        topic=data.topic,
        platform=platform,
        target_audience=data.target_audience,
        objective=data.objective,
        language=data.language,
        knowledge=knowledge,
    )

    post = MarketingPost(
        workspace_slug=data.workspace,
        topic=data.topic,
        platform=platform,
        target_audience=data.target_audience,
        objective=data.objective,
        language=data.language,
        title=generated["title"],
        content=generated["content"],
        hashtags=generated["hashtags"],
        sources=sources,
        llm_model=generated["llm_model"],
        status="draft",
        publish_metadata={},
    )

    db.add(post)
    db.flush()

    version = MarketingPostVersion(
        post_id=post.id,
        version_number=1,
        instructions="Initial generation",
        title=generated["title"],
        content=generated["content"],
        hashtags=generated["hashtags"],
        sources=sources,
        skills_used=generated.get("skills_used", []),
        llm_model=generated["llm_model"],
    )

    db.add(version)
    db.commit()
    db.refresh(post)
    db.refresh(version)

    return post, version


@router.get("/posts")
def list_posts(
    workspace: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(MarketingPost)

    if workspace:
        query = query.filter(
            MarketingPost.workspace_slug == workspace
        )

    if status:
        query = query.filter(MarketingPost.status == status)

    posts = (
        query
        .order_by(MarketingPost.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "total": len(posts),
        "dry_run_default": publish_dry_run_default(),
        "posts": [
            serialize_marketing_post(post)
            for post in posts
        ],
    }


@router.post("/posts/generate", status_code=201)
def generate_post(
    data: GeneratePostRequest,
    db: Session = Depends(get_db),
):
    try:
        config = get_marketing_config()
        post, version = _create_generated_post(
            db=db,
            data=data,
            config=config,
        )

        return serialize_marketing_post(
            post,
            version_id=version.id,
            version_number=version.version_number,
            skills_used=version.skills_used,
        )

    except HTTPException:
        db.rollback()
        raise

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Marketing post generation failed"
        )

        raise HTTPException(
            status_code=502,
            detail="Marketing post generation failed. Check API logs.",
        )


@router.post("/posts/generate-and-publish", status_code=201)
def generate_and_publish_post(
    data: GenerateAndPublishRequest,
    db: Session = Depends(get_db),
):
    """
    Generate a draft, auto-approve it, then publish (dry-run by default).
    """
    try:
        config = get_marketing_config()
        validate_publish_permission(config)

        post, version = _create_generated_post(
            db=db,
            data=data,
            config=config,
        )

        published = publish_marketing_post(
            db,
            post,
            dry_run=data.dry_run,
            auto_approve=True,
            requested_by=data.requested_by,
        )

        payload = serialize_marketing_post(
            published,
            version_id=version.id,
            version_number=version.version_number,
            skills_used=version.skills_used,
        )
        payload["publish_status"] = published.status
        return payload

    except HTTPException:
        db.rollback()
        raise

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Marketing generate-and-publish failed"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Marketing generate-and-publish failed. "
                "Check API logs."
            ),
        )


@router.get("/posts/{post_id}")
def get_post(
    post_id: str,
    db: Session = Depends(get_db),
):
    post = get_post_or_404(db, post_id)
    return serialize_marketing_post(post)


@router.post("/posts/{post_id}/approve")
def approve_post(
    post_id: str,
    db: Session = Depends(get_db),
):
    post = get_post_or_404(db, post_id)

    try:
        approved = approve_marketing_post(db, post)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return serialize_marketing_post(approved)


@router.post("/posts/{post_id}/publish", status_code=202)
def publish_post(
    post_id: str,
    data: PublishPostRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = data or PublishPostRequest()
    post = get_post_or_404(db, post_id)

    try:
        config = get_marketing_config()
        validate_publish_permission(config)

        published = publish_marketing_post(
            db,
            post,
            dry_run=payload.dry_run,
            auto_approve=payload.auto_approve,
            requested_by=payload.requested_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = serialize_marketing_post(published)
    result["publish_status"] = published.status
    return result


@router.post("/posts/{post_id}/revise")
def revise_post(
    post_id: str,
    data: RevisePostRequest,
    db: Session = Depends(get_db),
):
    post = get_post_or_404(db, post_id)

    if post.status in ("approved", *TERMINAL_PUBLISH_STATUSES):
        raise HTTPException(
            status_code=409,
            detail=(
                "Approved or published posts cannot be revised. "
                "Create a new draft instead."
            ),
        )

    try:
        config = get_marketing_config()

        validate_revision_permission(config)

        platform = validate_platform(
            config,
            post.platform,
        )

        workspace = resolve_post_workspace(post, config)

        validate_workspace(
            config,
            workspace,
        )

        knowledge, sources = retrieve_knowledge(
            db=db,
            workspace_slug=workspace,
            query=f"{post.topic}\n{data.instructions}",
        )

        latest_version = (
            db.query(MarketingPostVersion)
            .filter(
                MarketingPostVersion.post_id == post.id
            )
            .order_by(
                MarketingPostVersion.version_number.desc()
            )
            .first()
        )

        # Backfill version 1 for older posts.
        if latest_version is None:
            db.add(
                MarketingPostVersion(
                    post_id=post.id,
                    version_number=1,
                    instructions="Initial generation",
                    title=post.title,
                    content=post.content,
                    hashtags=post.hashtags or [],
                    sources=post.sources or [],
                    skills_used=[],
                    llm_model=post.llm_model,
                )
            )

            previous_version_number = 1

        else:
            previous_version_number = (
                latest_version.version_number
            )

        generated = revise_marketing_post(
            topic=post.topic,
            previous_title=post.title,
            previous_content=post.content,
            previous_hashtags=post.hashtags or [],
            instructions=data.instructions,
            platform=platform,
            target_audience=post.target_audience or "",
            objective=post.objective or "",
            language=post.language or "English",
            knowledge=knowledge,
        )

        new_version_number = previous_version_number + 1

        version = MarketingPostVersion(
            post_id=post.id,
            version_number=new_version_number,
            instructions=data.instructions,
            title=generated["title"],
            content=generated["content"],
            hashtags=generated["hashtags"],
            sources=sources,
            skills_used=generated.get("skills_used", []),
            llm_model=generated["llm_model"],
        )

        db.add(version)

        post.title = generated["title"]
        post.content = generated["content"]
        post.hashtags = generated["hashtags"]
        post.sources = sources
        post.llm_model = generated["llm_model"]
        post.status = "draft"
        post.publish_error = None

        db.commit()
        db.refresh(version)

        return {
            "post_id": post.id,
            "version_id": version.id,
            "version_number": new_version_number,
            "topic": post.topic,
            "title": version.title,
            "content": version.content,
            "hashtags": version.hashtags,
            "status": post.status,
            "instructions": version.instructions,
            "skills_used": version.skills_used,
            "llm_model": version.llm_model,
            "sources": version.sources,
            "created_at": version.created_at,
        }

    except HTTPException:
        db.rollback()
        raise

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        db.rollback()

        logger.exception("Post revision failed")

        raise HTTPException(
            status_code=502,
            detail="Post revision failed. Check API logs.",
        )


@router.get("/posts/{post_id}/versions")
def get_post_versions(
    post_id: str,
    db: Session = Depends(get_db),
):
    post = get_post_or_404(db, post_id)

    versions = (
        db.query(MarketingPostVersion)
        .filter(
            MarketingPostVersion.post_id == post.id
        )
        .order_by(
            MarketingPostVersion.version_number.asc()
        )
        .all()
    )

    return {
        "post_id": post.id,
        "total_versions": len(versions),
        "versions": [
            {
                "version_id": version.id,
                "version_number": version.version_number,
                "title": version.title,
                "content": version.content,
                "hashtags": version.hashtags,
                "instructions": version.instructions,
                "skills_used": version.skills_used,
                "llm_model": version.llm_model,
                "created_at": version.created_at,
            }
            for version in versions
        ],
    }
