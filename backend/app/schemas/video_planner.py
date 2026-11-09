
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VideoPlanRequest(BaseModel):
    topic: str = Field(min_length=5, max_length=2000)

    workspace_slug: str = "iotelligen-marketing"

    platform: Literal[
        "linkedin",
        "facebook",
        "instagram",
        "youtube",
        "tiktok",
    ] = "linkedin"

    target_audience: str = Field(
        default="Factory owners and production managers",
        max_length=500,
    )

    objective: str = Field(
        default="Generate awareness and leads",
        max_length=500,
    )

    language: str = "English"

    duration_seconds: int = Field(
        default=30,
        ge=10,
        le=180,
    )

    aspect_ratio: Literal[
        "9:16",
        "16:9",
        "1:1",
    ] = "9:16"

    tone: str = Field(
        default="Professional and engaging",
        max_length=200,
    )

    additional_instructions: str | None = None


class VideoScene(BaseModel):
    scene_number: int = Field(ge=1)

    duration_seconds: int = Field(ge=1, le=60)

    purpose: str

    narration: str

    visual_prompt: str

    on_screen_text: str

    transition: Literal[
        "cut",
        "fade",
        "slide",
        "zoom",
        "dissolve",
    ] = "cut"


class VideoPlan(BaseModel):
    concept: str

    title: str

    duration_seconds: int

    aspect_ratio: Literal[
        "9:16",
        "16:9",
        "1:1",
    ]

    language: str

    target_audience: str

    objective: str

    cta: str

    scenes: list[VideoScene] = Field(
        min_length=1,
        max_length=30,
    )

    @model_validator(mode="after")
    def validate_scene_timing(self):
        total_duration = sum(
            scene.duration_seconds
            for scene in self.scenes
        )

        if total_duration != self.duration_seconds:
            raise ValueError(
                f"Scene durations total {total_duration}s, "
                f"but video duration is {self.duration_seconds}s"
            )

        expected_numbers = list(
            range(1, len(self.scenes) + 1)
        )

        actual_numbers = [
            scene.scene_number
            for scene in self.scenes
        ]

        if actual_numbers != expected_numbers:
            raise ValueError(
                "Scene numbers must be sequential starting from 1"
            )

        return self


class VideoPlanRevisionRequest(BaseModel):
    workspace_slug: str = "iotelligen-marketing"

    plan: VideoPlan

    instructions: str = Field(
        min_length=5,
        max_length=2000,
    )

