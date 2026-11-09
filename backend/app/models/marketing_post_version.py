import uuid

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    JSON,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketingPostVersion(Base):
    __tablename__ = "marketing_post_versions"

    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "version_number",
            name="uq_marketing_post_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    post_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("marketing_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    instructions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    skills_used: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    llm_model: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
