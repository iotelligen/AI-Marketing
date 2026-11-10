from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PublishResult:
    status: str
    remote_post_id: str | None = None
    remote_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


SUPPORTED_PLATFORMS = (
    "linkedin",
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
)


def supported_platforms() -> tuple[str, ...]:
    return SUPPORTED_PLATFORMS


def publish_stub(platform: str) -> Callable[..., PublishResult]:
    def _run(**_kwargs) -> PublishResult:
        return PublishResult(
            status="failed",
            error_message=(
                f"Platform '{platform}' is not configured yet. "
                "Only LinkedIn publishing is implemented in this release."
            ),
            metadata={"provider": platform, "reason": "not_configured"},
        )

    return _run


def get_publisher(platform: str):
    platform = platform.lower().strip()

    if platform == "linkedin":
        from app.providers.linkedin.publish_provider import (
            LinkedInPublishProvider,
        )

        return LinkedInPublishProvider

    if platform in SUPPORTED_PLATFORMS:
        return publish_stub(platform)

    raise ValueError(f"Unsupported platform: {platform}")
