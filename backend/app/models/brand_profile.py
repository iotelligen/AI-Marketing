import uuid

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BrandProfile(Base):
    """
    Verified brand facts for one workspace.

    The renderer draws the logo and contact details from this record,
    so they are never written by an LLM or drawn by an image model.
    """

    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    workspace_slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    brand_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    tagline: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    accent_color: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default="#16C79A",
        server_default="#16C79A",
    )

    website: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # Name of the file as the user uploaded it.
    logo_filename: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    logo_storage_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    logo_mime_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
