
import json
import logging
import os
import re

from litellm import completion
from pydantic import ValidationError

from app.schemas.video_planner import (
    VideoFormat,
    VideoPlan,
    VideoPlanRequest,
)
from app.services.agent_config_service import (
    load_agent_config,
    get_agent_model,
)
from app.services.brand_service import brand_facts_for_prompt
from app.services.llm_json import complete_json, strip_code_fences
from app.services.marketing_service import retrieve_knowledge
from app.services.skill_service import load_marketing_skills
from app.services.video_format_service import generate_video_format


logger = logging.getLogger(__name__)

VIDEO_AGENT_ID = "video"

VIDEO_TOP_K = int(os.getenv("VIDEO_TOP_K", "5"))

# The scriptwriter needs the skills that govern wording and accuracy.
# Structure is the format agent's job.
SCRIPT_SKILLS = (
    "brand_guidelines",
    "platform",
    "technical_content",
    "storytelling",
)


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


def parse_script(
    raw_content: str,
    video_format: VideoFormat,
    request: VideoPlanRequest,
) -> VideoPlan:
    """
    Turn the scriptwriter's answer into a storyboard.

    Everything the format agent or the user already decided (scene
    order, beat, timing, duration, aspect ratio) is written from those
    sources rather than trusted from the scriptwriter's answer.
    """
    if not raw_content:
        raise ValueError("Video Agent returned empty content")

    try:
        data = json.loads(strip_code_fences(raw_content))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Video Agent returned invalid JSON"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError("Video Agent must return a JSON object")

    scenes = data.get("scenes")
    beats = video_format.beats

    if not isinstance(scenes, list) or len(scenes) != len(beats):
        found = len(scenes) if isinstance(scenes, list) else 0

        raise ValueError(
            f"The storyboard must contain exactly {len(beats)} scenes, "
            f"one per beat and in beat order. It contained {found}."
        )

    for index, (scene, beat) in enumerate(zip(scenes, beats), start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {index} must be a JSON object")

        scene["scene_number"] = index
        scene["beat"] = beat.beat
        scene["duration_seconds"] = beat.duration_seconds
        scene["purpose"] = beat.goal

    data["duration_seconds"] = request.duration_seconds
    data["aspect_ratio"] = request.aspect_ratio
    data["language"] = request.language
    data["target_audience"] = request.target_audience
    data["objective"] = request.objective

    try:
        return VideoPlan.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid storyboard returned by Video Agent: {exc}"
        ) from exc


def generate_video_plan(
    request: VideoPlanRequest,
    db,
) -> dict:
    """
    Plan a video in two steps: the format agent decides the beat
    sheet, then the video agent writes a scene for every beat.
    """
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

    # Step 1: structure. A caller may supply its own beat sheet.
    if request.video_format is not None:
        video_format = request.video_format

        if video_format.duration_seconds != request.duration_seconds:
            raise ValueError(
                "The supplied video format lasts "
                f"{video_format.duration_seconds}s, but the requested "
                f"duration is {request.duration_seconds}s"
            )

        format_agent = None
    else:
        format_result = generate_video_format(request)

        video_format = VideoFormat.model_validate(
            format_result["format"]
        )

        format_agent = {
            "agent_id": format_result["agent_id"],
            "llm_model": format_result["llm_model"],
        }

    beat_sheet = "\n".join(
        f"{index}. {beat.beat} ({beat.duration_seconds}s): {beat.goal}"
        for index, beat in enumerate(video_format.beats, start=1)
    )

    # Step 2: script and visuals for each beat.
    skills = load_marketing_skills(request.platform)

    skill_context = "\n\n".join(
        f"### {name.replace('_', ' ').title()}\n{skills[name]}"
        for name in SCRIPT_SKILLS
    )

    brand_facts = brand_facts_for_prompt(db, request.workspace_slug)

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

A format strategist has already decided the structure of this video.
Your job is to write the script and the visuals for each beat. You
cannot add, remove, reorder or retime beats.

BEAT SHEET ({video_format.format_name}):
{beat_sheet}

SCRIPT RULES:

1. Write exactly one scene per beat, in the order of the beat sheet.
2. Each scene must achieve the goal of its beat.
3. Write clear and natural narration that can be spoken within the
   beat's duration: at most about 2.5 words per second.
4. Keep on_screen_text to 8 words or fewer.
5. Make the opening scene engaging.
6. Every visual_prompt describes one photorealistic scene for an
   image generation model, and may later drive a video model.
   Never ask for text, captions, numbers, logos, brand names,
   watermarks or software screenshots in the image. Image models
   draw them badly, and the renderer adds the logo and text itself.
7. The "cta" scene is rendered as a branded end card. The logo and
   the contact details are added automatically from the company's
   stored brand profile. For that scene, write a short call to
   action as on_screen_text, and a visual_prompt for a calm, dark,
   uncluttered background.
8. Never write phone numbers, email addresses, web addresses or
   street addresses anywhere in the storyboard.
9. Never invent {identity['company']} product specifications,
   customer names, results or certifications.
10. Distinguish verified company facts from general
    industrial knowledge.
11. transition must be one of: cut, fade, slide, zoom, dissolve.
12. Return valid JSON only. Do not use Markdown fences.

BRAND:
{brand_facts}

SKILLS:
{skill_context}

COMPANY KNOWLEDGE:
{knowledge_context}

Required JSON structure:

{{
  "concept": "Video concept",
  "title": "Video title",
  "cta": "Short call to action",
  "scenes": [
    {{
      "beat": "hook",
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

Write the storyboard for the beat sheet.
"""

    plan = complete_json(
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        parse=lambda raw: parse_script(raw, video_format, request),
        agent_label="Video Agent",
    )

    return {
        "plan": plan.model_dump(),
        "format": video_format.model_dump(),
        "llm_model": model,
        "agent_id": VIDEO_AGENT_ID,
        "format_agent": format_agent,
        "skills_used": list(SCRIPT_SKILLS),
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
9. When scenes carry a "beat" value, every scene must keep one.
   Allowed beats are hook, pain_point, consequence, solution,
   benefit and cta. The first scene must be the only "hook" and
   the last scene must be the only "cta".
10. Never write phone numbers, email addresses or web addresses.
    The renderer adds contact details to the "cta" scene.
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
