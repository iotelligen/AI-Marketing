import uuid

from sqlalchemy import String, DateTime, JSON, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PublishAccount(Base):
    """
    Platform credentials used by the FastAPI publishers.

    Tokens are stored in JSON for local development. This is not a
    production-grade secrets store; encrypt at rest before exposing
    the API outside a trusted machine.
    """

    __tablename__ = "publish_accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
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

    display_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # active, disabled
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        server_default="active",
    )

    credentials: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    last_verified_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
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
        Index(
            "ix_publish_accounts_workspace_platform",
            "workspace_slug",
            "platform",
        ),
    )
