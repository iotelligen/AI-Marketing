import uuid

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    JSON,
    ForeignKey,
    func,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    workspace_slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="iotelligen-marketing",
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    template_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="IndustrialPromo",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="queued",
    )

    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    renderer_job_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    input_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    output_file: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
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

    __table_args__ = (
        Index("ix_video_jobs_workspace_created", "workspace_slug", "created_at"),
        Index("ix_video_jobs_status", "status"),
    )
