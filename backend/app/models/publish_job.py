import uuid

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    JSON,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PublishJob(Base):
    """
    One attempt to publish a specific VideoVersion to one platform.
    """

    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    video_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    workspace_slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("publish_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # queued, publishing, published, failed, dry_run
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )

    caption: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
    )

    remote_post_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    remote_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # n8n, api, dashboard
    requested_by: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="api",
        server_default="api",
    )

    result_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
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

    published_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_publish_jobs_version_platform",
            "version_id",
            "platform",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_publish_jobs_idempotency_key",
        ),
    )
