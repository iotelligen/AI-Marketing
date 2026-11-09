
import json
import logging
import os
import re

from litellm import completion
from pydantic import ValidationError

from app.schemas.video_planner import (
    VideoPlan,
    VideoPlanRequest,
)
from app.services.agent_config_service import (
    load_agent_config,
    get_agent_model,
)
from app.services.marketing_service import retrieve_knowledge


logger = logging.getLogger(__name__)

VIDEO_AGENT_ID = "video"

VIDEO_TOP_K = int(os.getenv("VIDEO_TOP_K", "5"))


def get_video_agent_config():
    return load_agent_config(VIDEO_AGENT_ID)


def parse_video_plan(raw_content: str) -> VideoPlan:
    if not raw_content:
        raise ValueError("Video Agent returned empty content")

    # Remove Markdown code fences if a provider ignores JSON mode.
    cleaned = raw_content.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.exception("Invalid JSON returned by Video Agent")
        raise ValueError(
            "Video Agent returned invalid JSON"
        ) from exc

    try:
        return VideoPlan.model_validate(data)
    except ValidationError as exc:
        logger.exception("Video storyboard validation failed")
        raise ValueError(
            f"Invalid storyboard returned by Video Agent: {exc}"
        ) from exc


def generate_video_plan(
    request: VideoPlanRequest,
    db,
) -> dict:
    config = get_video_agent_config()

    permissions = config.get("permissions", {})

    if not permissions.get("can_generate_scripts", False):
        raise PermissionError(
            "Video Agent is not permitted to generate scripts"
        )

    allowed_workspaces = permissions.get(
        "allowed_workspaces",
        [],
    )

    if request.workspace_slug not in allowed_workspaces:
        raise PermissionError(
            f"Video Agent cannot access workspace: "
            f"{request.workspace_slug}"
        )

    model = get_agent_model(config, "VIDEO_MODEL")

    temperature = config.get("model", {}).get(
        "temperature",
        0.5,
    )

    identity = config["identity"]

    knowledge, sources = retrieve_knowledge(
        db=db,
        workspace_slug=request.workspace_slug,
        query=request.topic,
    )

    knowledge_context = "\n\n---\n\n".join(knowledge)

    if not knowledge_context:
        knowledge_context = (
            "No relevant company documents were retrieved. "
            "Do not invent IoTelliGen product specifications, "
            "customer claims, certifications or performance figures."
        )

    system_prompt = f"""
You are {config['name']}.

Your role:
{identity['role']}

Company:
{identity['company']}

Company description:
{identity['description']}

Primary market:
{identity['primary_market']}

Primary language:
{identity['primary_language']}

VIDEO PLANNING RULES:

1. Create a professional industrial video storyboard.
2. Write clear and natural narration.
3. Make every scene visually meaningful.
4. Use concise on-screen text suitable for video.
5. Every scene must have a visual_prompt that can later
   be used by an image or video generation model.
6. Make the video engaging from the opening scene.
7. Include a suitable call to action.
8. Respect the requested duration exactly.
9. Scene durations must add up to the total video duration.
10. Scene numbers must start at 1 and be sequential.
11. Never invent IoTelliGen product specifications,
    customer names, results or certifications.
12. Distinguish verified company facts from general
    industrial knowledge.
13. Return valid JSON only. Do not use Markdown fences.

COMPANY KNOWLEDGE:
{knowledge_context}

Required JSON structure:

{{
  "concept": "Video concept",
  "title": "Video title",
  "duration_seconds": 30,
  "aspect_ratio": "9:16",
  "language": "English",
  "target_audience": "Factory owners",
  "objective": "Generate awareness",
  "cta": "Contact IoTelliGen",
  "scenes": [
    {{
      "scene_number": 1,
      "duration_seconds": 5,
      "purpose": "Hook",
      "narration": "Narration text",
      "visual_prompt": "Detailed visual description",
      "on_screen_text": "Short text",
      "transition": "fade"
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

ASPECT RATIO:
{request.aspect_ratio}

TONE:
{request.tone}

ADDITIONAL INSTRUCTIONS:
{request.additional_instructions or "None"}

Generate the complete storyboard.
"""

    response = completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content

    plan = parse_video_plan(raw_content)

    return {
        "plan": plan.model_dump(),
        "llm_model": model,
        "agent_id": VIDEO_AGENT_ID,
        "knowledge_sources": sources,
        "requires_human_approval": True,
    }


def revise_video_plan(
    plan: VideoPlan,
    instructions: str,
    workspace_slug: str,
    db,
) -> dict:
    config = get_video_agent_config()

    permissions = config.get("permissions", {})

    if not permissions.get("can_revise_scripts", False):
        raise PermissionError(
            "Video Agent is not permitted to revise scripts"
        )

    allowed_workspaces = permissions.get(
        "allowed_workspaces",
        [],
    )

    if workspace_slug not in allowed_workspaces:
        raise PermissionError(
            f"Video Agent cannot access workspace: {workspace_slug}"
        )

    model = get_agent_model(config, "VIDEO_MODEL")

    temperature = config.get("model", {}).get(
        "temperature",
        0.5,
    )

    knowledge, sources = retrieve_knowledge(
        db=db,
        workspace_slug=workspace_slug,
        query=plan.concept,
    )

    knowledge_context = "\n\n---\n\n".join(knowledge)

    if not knowledge_context:
        knowledge_context = (
            "No relevant company documents were retrieved. "
            "Do not invent company-specific claims."
        )

    system_prompt = """
You are an industrial video scriptwriter.

Revise the supplied storyboard according to the user's instructions.

Rules:
1. Preserve the original video duration.
2. Preserve the original aspect ratio.
3. Scene durations must add up exactly to the video duration.
4. Scene numbers must be sequential starting from 1.
5. Preserve verified company facts.
6. Never invent product specifications, customers, certifications
   or performance figures.
7. Return the complete revised storyboard as valid JSON only.
8. Follow the same JSON structure as the supplied storyboard.
"""

    user_prompt = f"""
EXISTING STORYBOARD:
{json.dumps(plan.model_dump(), ensure_ascii=False)}

VERIFIED COMPANY KNOWLEDGE:
{knowledge_context}

REVISION INSTRUCTIONS:
{instructions}

Return the complete revised storyboard.
"""

    response = completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    revised_plan = parse_video_plan(
        response.choices[0].message.content
    )

    if revised_plan.duration_seconds != plan.duration_seconds:
        raise ValueError(
            "Revised storyboard changed the original duration"
        )

    if revised_plan.aspect_ratio != plan.aspect_ratio:
        raise ValueError(
            "Revised storyboard changed the original aspect ratio"
        )

    return {
        "plan": revised_plan.model_dump(),
        "llm_model": model,
        "agent_id": VIDEO_AGENT_ID,
        "knowledge_sources": sources,
        "requires_human_approval": True,
    }
