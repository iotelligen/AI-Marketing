import uuid

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    JSON,
    ForeignKey,
    Text,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scene_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    asset_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    model: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # pending, generating, completed, failed
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    # pending, approved, rejected
    review_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    reviewed_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    storage_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    source_url: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    mime_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    asset_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_video_assets_job_scene",
            "job_id",
            "scene_number",
        ),
        Index(
            "ix_video_assets_status",
            "status",
        ),
        Index(
            "ix_video_assets_review_status",
            "review_status",
        ),
    )
