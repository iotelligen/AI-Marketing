import uuid

from sqlalchemy import (
    String,
    Text,
    DateTime,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketingPost(Base):
    __tablename__ = "marketing_posts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    workspace_slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="iotelligen",
        index=True,
    )

    topic: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="linkedin",
    )

    target_audience: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    objective: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    language: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="English",
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    hashtags: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    sources: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    llm_model: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    # draft | approved | published | dry_run
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
    )

    remote_post_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    remote_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    publish_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    publish_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    published_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
