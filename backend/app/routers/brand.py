import logging
import uuid

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_profile import BrandProfile
from app.models.workspace import Workspace
from app.services.brand_service import (
    BRAND_STORAGE,
    DEFAULT_ACCENT_COLOR,
    DEFAULT_BRAND_NAME,
    get_brand_profile,
    resolve_logo_path,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Brand"])

MAX_LOGO_SIZE = 5 * 1024 * 1024


class BrandProfileUpdate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=150)
    tagline: str | None = Field(default=None, max_length=200)
    accent_color: str = Field(
        default=DEFAULT_ACCENT_COLOR,
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    website: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("brand_name", mode="before")
    @classmethod
    def strip_brand_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "tagline",
        "website",
        "email",
        "phone",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None

        return value


def detect_image_type(header: bytes) -> tuple[str, str] | None:
    """
    Identify the image by its leading bytes rather than by the
    filename or the content type the client claims.
    """
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"

    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"

    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp", "image/webp"

    return None


def require_workspace(db: Session, workspace_slug: str) -> Workspace:
    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise HTTPException(404, "Workspace not found")

    return workspace


def serialize_brand(
    workspace_slug: str,
    profile: BrandProfile | None,
) -> dict:
    logo_path = resolve_logo_path(profile)

    return {
        "workspace": workspace_slug,
        "configured": profile is not None,
        "brand_name": (
            profile.brand_name if profile else DEFAULT_BRAND_NAME
        ),
        "tagline": profile.tagline if profile else None,
        "accent_color": (
            profile.accent_color if profile else DEFAULT_ACCENT_COLOR
        ),
        "website": profile.website if profile else None,
        "email": profile.email if profile else None,
        "phone": profile.phone if profile else None,
        "has_logo": logo_path is not None,
        "logo_filename": (
            profile.logo_filename if profile and logo_path else None
        ),
        # The stored filename changes on every upload, so it doubles
        # as a cache key for the browser.
        "logo_url": (
            f"/workspaces/{workspace_slug}/brand/logo?v={logo_path.stem}"
            if logo_path
            else None
        ),
        "updated_at": profile.updated_at if profile else None,
    }


def remove_logo_file(profile: BrandProfile) -> None:
    logo_path = resolve_logo_path(profile)

    if logo_path:
        logo_path.unlink(missing_ok=True)


@router.get("/{workspace_slug}/brand")
def get_brand(
    workspace_slug: str,
    db: Session = Depends(get_db),
):
    require_workspace(db, workspace_slug)

    return serialize_brand(
        workspace_slug,
        get_brand_profile(db, workspace_slug),
    )


@router.put("/{workspace_slug}/brand")
def update_brand(
    workspace_slug: str,
    data: BrandProfileUpdate,
    db: Session = Depends(get_db),
):
    require_workspace(db, workspace_slug)

    profile = get_brand_profile(db, workspace_slug)

    if not profile:
        profile = BrandProfile(workspace_slug=workspace_slug)
        db.add(profile)

    profile.brand_name = data.brand_name
    profile.tagline = data.tagline
    profile.accent_color = data.accent_color.upper()
    profile.website = data.website
    profile.email = data.email
    profile.phone = data.phone

    db.commit()
    db.refresh(profile)

    return serialize_brand(workspace_slug, profile)


@router.post("/{workspace_slug}/brand/logo")
def upload_brand_logo(
    workspace_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    require_workspace(db, workspace_slug)

    try:
        content = file.file.read(MAX_LOGO_SIZE + 1)
    finally:
        file.file.close()

    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(413, "Logo exceeds the 5 MB upload limit")

    image_type = detect_image_type(content[:16])

    if not image_type:
        raise HTTPException(
            400,
            "Logo must be a PNG, JPEG or WebP image",
        )

    extension, mime_type = image_type

    profile = get_brand_profile(db, workspace_slug)

    if not profile:
        # Allow the logo to be uploaded before the text fields are saved.
        profile = BrandProfile(
            workspace_slug=workspace_slug,
            brand_name=DEFAULT_BRAND_NAME,
            accent_color=DEFAULT_ACCENT_COLOR,
        )
        db.add(profile)
        db.flush()

    # The directory is named after the profile ID, not the workspace
    # slug, because slugs are not restricted to path-safe characters.
    logo_dir = BRAND_STORAGE / profile.id
    logo_dir.mkdir(parents=True, exist_ok=True)

    logo_path = logo_dir / f"logo_{uuid.uuid4().hex}{extension}"
    previous_logo = resolve_logo_path(profile)

    try:
        logo_path.write_bytes(content)

        profile.logo_filename = (
            Path(file.filename or "").name[:500] or logo_path.name
        )
        profile.logo_storage_path = str(logo_path)
        profile.logo_mime_type = mime_type

        db.commit()
        db.refresh(profile)
    except Exception:
        db.rollback()
        logo_path.unlink(missing_ok=True)
        logger.exception("Brand logo upload failed")
        raise HTTPException(500, "Unable to store the logo")

    if previous_logo and previous_logo != logo_path:
        previous_logo.unlink(missing_ok=True)

    return serialize_brand(workspace_slug, profile)


@router.get("/{workspace_slug}/brand/logo")
def get_brand_logo(
    workspace_slug: str,
    db: Session = Depends(get_db),
):
    require_workspace(db, workspace_slug)

    profile = get_brand_profile(db, workspace_slug)
    logo_path = resolve_logo_path(profile)

    if not logo_path:
        raise HTTPException(404, "No logo has been uploaded")

    return FileResponse(
        path=logo_path,
        media_type=profile.logo_mime_type or "application/octet-stream",
        content_disposition_type="inline",
    )


@router.delete("/{workspace_slug}/brand/logo")
def delete_brand_logo(
    workspace_slug: str,
    db: Session = Depends(get_db),
):
    require_workspace(db, workspace_slug)

    profile = get_brand_profile(db, workspace_slug)

    if not profile or not profile.logo_storage_path:
        raise HTTPException(404, "No logo has been uploaded")

    remove_logo_file(profile)

    profile.logo_filename = None
    profile.logo_storage_path = None
    profile.logo_mime_type = None

    db.commit()
    db.refresh(profile)

    return serialize_brand(workspace_slug, profile)
