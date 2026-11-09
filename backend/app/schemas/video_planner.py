
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# The beat vocabulary the format agent may choose from. The renderer
# uses "cta" to draw the branded end card.
BeatType = Literal[
    "hook",
    "pain_point",
    "consequence",
    "solution",
    "benefit",
    "cta",
]

# A beat never runs longer than the longest AI clip the image-to-video
# step can produce (15 seconds), so one clip can always cover a scene.
BEAT_MIN_SECONDS = 2
BEAT_MAX_SECONDS = 15


def validate_beat_order(beats: list[str]) -> None:
    if not beats:
        raise ValueError("At least one beat is required")

    if beats[0] != "hook":
        raise ValueError("The first beat must be 'hook'")

    if beats[-1] != "cta":
        raise ValueError("The last beat must be 'cta'")

    if beats.count("hook") != 1:
        raise ValueError("Exactly one 'hook' beat is allowed")

    if beats.count("cta") != 1:
        raise ValueError("Exactly one 'cta' beat is allowed")


class FormatBeat(BaseModel):
    beat: BeatType

    duration_seconds: int = Field(
        ge=BEAT_MIN_SECONDS,
        le=BEAT_MAX_SECONDS,
    )

    # What this beat has to achieve for the viewer.
    goal: str = Field(min_length=3, max_length=500)


class VideoFormat(BaseModel):
    """Beat sheet produced by the format agent."""

    format_name: str = Field(min_length=2, max_length=200)

    rationale: str = Field(default="", max_length=1000)

    duration_seconds: int = Field(ge=10, le=180)

    beats: list[FormatBeat] = Field(
        min_length=3,
        max_length=30,
    )

    @model_validator(mode="after")
    def validate_beats(self):
        total_duration = sum(
            beat.duration_seconds
            for beat in self.beats
        )

        if total_duration != self.duration_seconds:
            raise ValueError(
                f"Beat durations total {total_duration}s, "
                f"but video duration is {self.duration_seconds}s"
            )

        validate_beat_order([beat.beat for beat in self.beats])

        return self


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

    # Optional beat sheet. When omitted, the format agent creates one.
    video_format: VideoFormat | None = None


class VideoScene(BaseModel):
    scene_number: int = Field(ge=1)

    duration_seconds: int = Field(ge=1, le=60)

    # Optional so storyboards saved before beats existed still load.
    beat: BeatType | None = None

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

        beats = [
            scene.beat
            for scene in self.scenes
        ]

        if any(beat is not None for beat in beats):
            if any(beat is None for beat in beats):
                raise ValueError(
                    "Every scene must have a beat when any scene has one"
                )

            validate_beat_order(beats)

        return self


class VideoPlanRevisionRequest(BaseModel):
    workspace_slug: str = "iotelligen-marketing"

    plan: VideoPlan

    instructions: str = Field(
        min_length=5,
        max_length=2000,
    )

