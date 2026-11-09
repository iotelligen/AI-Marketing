import os

from pathlib import Path

from sqlalchemy.orm import Session

from app.models.brand_profile import BrandProfile


DEFAULT_BRAND_NAME = "IoTelliGen"
DEFAULT_ACCENT_COLOR = "#16C79A"

ASSET_STORAGE = Path(
    os.getenv("ASSET_STORAGE", "/data/assets")
).resolve()

# Logos live inside the asset directory so the renderer, which mounts
# that directory read-only, can load them the same way as scene images.
BRAND_STORAGE = ASSET_STORAGE / "brand"


def get_brand_profile(
    db: Session,
    workspace_slug: str,
) -> BrandProfile | None:
    return db.query(BrandProfile).filter(
        BrandProfile.workspace_slug == workspace_slug
    ).first()


def resolve_logo_path(profile: BrandProfile | None) -> Path | None:
    """
    Return the stored logo file, or None when it is missing or
    points outside the brand storage directory.
    """
    if not profile or not profile.logo_storage_path:
        return None

    try:
        logo_path = Path(profile.logo_storage_path).resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None

    if not logo_path.is_relative_to(BRAND_STORAGE):
        return None

    if not logo_path.is_file():
        return None

    return logo_path


def build_render_brand(db: Session, workspace_slug: str) -> dict:
    """
    Brand block for the renderer manifest.

    Falls back to the built-in defaults when the workspace has no
    brand profile, so existing jobs keep rendering as before.
    """
    profile = get_brand_profile(db, workspace_slug)

    brand = {
        "name": DEFAULT_BRAND_NAME,
        "accent_color": DEFAULT_ACCENT_COLOR,
    }

    if not profile:
        return brand

    brand["name"] = profile.brand_name
    brand["accent_color"] = profile.accent_color

    for field in ("tagline", "website", "email", "phone"):
        value = getattr(profile, field)

        if value:
            brand[field] = value

    logo_path = resolve_logo_path(profile)

    if logo_path:
        brand["logo_path"] = str(logo_path)

    return brand


def brand_facts_for_prompt(db: Session, workspace_slug: str) -> str:
    """
    Brand facts a writing agent may rely on.

    Contact details are deliberately left out: the renderer adds them
    to the end card, so an agent never needs to write them.
    """
    profile = get_brand_profile(db, workspace_slug)

    if not profile:
        return f"Brand name: {DEFAULT_BRAND_NAME}"

    lines = [f"Brand name: {profile.brand_name}"]

    if profile.tagline:
        lines.append(f"Tagline: {profile.tagline}")

    return "\n".join(lines)
