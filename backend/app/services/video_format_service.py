import json
import logging

from pydantic import ValidationError

from app.schemas.video_planner import (
    BEAT_MAX_SECONDS,
    BEAT_MIN_SECONDS,
    VideoFormat,
    VideoPlanRequest,
)
from app.services.agent_config_service import (
    get_agent_model,
    load_agent_config,
)
from app.services.llm_json import complete_json, strip_code_fences
from app.services.skill_service import load_marketing_skills


logger = logging.getLogger(__name__)

VIDEO_FORMAT_AGENT_ID = "video_format"

# The format agent decides structure, so it only needs the skills
# that describe pacing and narrative shape.
FORMAT_SKILLS = (
    "platform",
    "storytelling",
    "marketing_funnel",
)


def get_video_format_agent_config():
    return load_agent_config(VIDEO_FORMAT_AGENT_ID)


def parse_video_format(
    raw_content: str,
    duration_seconds: int,
) -> VideoFormat:
    if not raw_content:
        raise ValueError("Video Format Agent returned empty content")

    try:
        data = json.loads(strip_code_fences(raw_content))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Video Format Agent returned invalid JSON"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Video Format Agent must return a JSON object"
        )

    # The requested duration is not the agent's to change, so the beat
    # durations are always checked against the request.
    data["duration_seconds"] = duration_seconds

    try:
        return VideoFormat.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid video format returned by Video Format Agent: {exc}"
        ) from exc


def generate_video_format(request: VideoPlanRequest) -> dict:
    config = get_video_format_agent_config()

    permissions = config.get("permissions", {})

    if not permissions.get("can_generate_formats", False):
        raise PermissionError(
            "Video Format Agent is not permitted to generate formats"
        )

    if request.workspace_slug not in permissions.get(
        "allowed_workspaces",
        [],
    ):
        raise PermissionError(
            f"Video Format Agent cannot access workspace: "
            f"{request.workspace_slug}"
        )

    model = get_agent_model(config, "VIDEO_FORMAT_MODEL")

    temperature = config.get("model", {}).get(
        "temperature",
        0.4,
    )

    identity = config["identity"]

    skills = load_marketing_skills(request.platform)

    skill_context = "\n\n".join(
        f"### {name.replace('_', ' ').title()}\n{skills[name]}"
        for name in FORMAT_SKILLS
    )

    system_prompt = f"""
You are {config['name']}.

Your role:
{identity['role']}

Company:
{identity['company']}

Primary market:
{identity['primary_market']}

You decide the structure of a promotional video before any script
is written. You do not write narration, on-screen text or visuals.
A separate scriptwriter fills in each beat you define.

FORMAT RULES:

1. Build the video only from these beats:
   - hook: stop the viewer scrolling in the opening seconds
   - pain_point: the industrial problem the audience recognises
   - consequence: what that problem costs if it is ignored
   - solution: how the company's offering addresses the problem
   - benefit: what improves for the audience
   - cta: what the viewer should do next
2. The first beat must be "hook" and the last beat must be "cta".
   Each of those two appears exactly once.
3. The other beats may be repeated or left out when the duration
   or the objective calls for it.
4. Every beat lasts between {BEAT_MIN_SECONDS} and {BEAT_MAX_SECONDS}
   whole seconds.
5. Beat durations must add up exactly to the requested duration.
6. Keep the hook short. Give the cta at least 3 seconds: it is
   rendered as an end card with the company logo and contact
   details, which the viewer needs time to read.
7. Follow the platform guidance below for pacing.
8. Write each goal as one sentence describing what the viewer
   should understand or feel in that beat. Do not write script.
9. Never invent product specifications, customers or results.
10. Return valid JSON only. Do not use Markdown fences.

SKILLS:
{skill_context}

Required JSON structure:

{{
  "format_name": "Short name of the structure",
  "rationale": "Why this structure fits the brief",
  "duration_seconds": 30,
  "beats": [
    {{
      "beat": "hook",
      "duration_seconds": 3,
      "goal": "What this beat must achieve"
    }}
  ]
}}
"""

    user_prompt = f"""
VIDEO TOPIC:
{request.topic}

PLATFORM:
{request.platform}

TARGET AUDIENCE:
{request.target_audience}

OBJECTIVE:
{request.objective}

LANGUAGE:
{request.language}

DURATION:
{request.duration_seconds} seconds

TONE:
{request.tone}

ADDITIONAL INSTRUCTIONS:
{request.additional_instructions or "None"}

Decide the video format.
"""

    video_format = complete_json(
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        parse=lambda raw: parse_video_format(
            raw,
            request.duration_seconds,
        ),
        agent_label="Video Format Agent",
    )

    return {
        "format": video_format.model_dump(),
        "llm_model": model,
        "agent_id": VIDEO_FORMAT_AGENT_ID,
        "skills_used": list(FORMAT_SKILLS),
    }
