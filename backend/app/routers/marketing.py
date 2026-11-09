
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
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


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/marketing",
    tags=["Marketing Agent"],
)

MARKETING_AGENT_ID = "marketing"

DEFAULT_WORKSPACE = os.getenv(
    "MARKETING_WORKSPACE",
    "iotelligen",
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


class RevisePostRequest(BaseModel):
    instructions: str = Field(
        min_length=3,
        max_length=4000,
    )


@router.post("/posts/generate", status_code=201)
def generate_post(
    data: GeneratePostRequest,
    db: Session = Depends(get_db),
):
    try:
        config = get_marketing_config()

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
        )

        db.add(post)
        db.flush()

        # Save initial generation as version 1.
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

        return {
            "id": post.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "topic": post.topic,
            "platform": post.platform,
            "title": post.title,
            "content": post.content,
            "hashtags": post.hashtags,
            "status": post.status,
            "llm_model": post.llm_model,
            "skills_used": version.skills_used,
            "sources": post.sources,
            "created_at": post.created_at,
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

        logger.exception(
            "Marketing post generation failed"
        )

        raise HTTPException(
            status_code=502,
            detail="Marketing post generation failed. Check API logs.",
        )


@router.post("/posts/{post_id}/revise")
def revise_post(
    post_id: str,
    data: RevisePostRequest,
    db: Session = Depends(get_db),
):
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

    if post.status == "approved":
        raise HTTPException(
            status_code=409,
            detail=(
                "Approved posts cannot be revised. "
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

        # The current MarketingPost model does not store
        # its originating workspace, so use the agent default.
        workspace = get_default_workspace(config)

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

        # Save the new version.
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

        # Update the current post.
        post.title = generated["title"]
        post.content = generated["content"]
        post.hashtags = generated["hashtags"]
        post.sources = sources
        post.llm_model = generated["llm_model"]
        post.status = "draft"

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
