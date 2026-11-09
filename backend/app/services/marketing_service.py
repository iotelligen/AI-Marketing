
import json
import logging
import os

from litellm import completion
from sqlalchemy.orm import Session

from app.models.workspace import Workspace
from app.models.document import Document
from app.models.document_chunk import DocumentChunk

from app.services.embedding_service import generate_embeddings
from app.services.skill_service import load_marketing_skills
from app.services.agent_config_service import (
    load_agent_config,
    get_agent_model,
)


logger = logging.getLogger(__name__)


MARKETING_AGENT_ID = "marketing"

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "openai/text-embedding-3-small",
)

MARKETING_TOP_K = int(
    os.getenv("MARKETING_TOP_K", "5")
)


def get_marketing_agent_config():
    """Load Marketing Agent configuration."""
    return load_agent_config(MARKETING_AGENT_ID)


def _get_llm_settings(config: dict):
    """Get model and temperature from agent configuration."""
    model = get_agent_model(config)
    temperature = config.get("model", {}).get(
        "temperature", 0.7
    )

    return model, temperature


def retrieve_knowledge(
    db: Session,
    workspace_slug: str,
    query: str,
):
    """Retrieve relevant company knowledge using vector search."""

    workspace = db.query(Workspace).filter(
        Workspace.slug == workspace_slug
    ).first()

    if not workspace:
        raise ValueError(
            f"Workspace not found: {workspace_slug}"
        )

    query_embedding = generate_embeddings([query])[0]
    dimensions = len(query_embedding)

    distance = DocumentChunk.embedding.cosine_distance(
        query_embedding
    )

    results = (
        db.query(
            DocumentChunk,
            Document,
            distance.label("distance"),
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id,
        )
        .filter(
            Document.workspace_id == workspace.id,
            DocumentChunk.embedding.isnot(None),
            DocumentChunk.embedding_model == EMBEDDING_MODEL,
            DocumentChunk.embedding_dimensions == dimensions,
        )
        .order_by(distance)
        .limit(MARKETING_TOP_K)
        .all()
    )

    knowledge = []
    sources = []

    for chunk, document, distance_value in results:
        similarity = 1.0 - float(distance_value)

        knowledge.append(
            f"Source: {document.original_filename}\n"
            f"Content:\n{chunk.content}"
        )

        sources.append({
            "document_id": document.id,
            "filename": document.original_filename,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "similarity": round(similarity, 4),
        })

    return knowledge, sources


def _load_skill_context(platform: str):
    """Load marketing skills for the selected platform."""

    skills = load_marketing_skills(platform)

    skill_context = "\n\n".join(
        f"### {name.replace('_', ' ').title()}\n{content}"
        for name, content in skills.items()
    )

    return skill_context, list(skills.keys())


def _parse_llm_json(raw_content: str) -> dict:
    """Parse and validate JSON returned by the LLM."""

    if not raw_content:
        raise ValueError("LLM returned empty content")

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.exception("Invalid JSON returned by LLM")
        raise ValueError(
            "LLM returned invalid JSON"
        ) from exc

    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object")

    title = result.get("title")
    content = result.get("content")
    hashtags = result.get("hashtags", [])

    if not isinstance(title, str) or not title.strip():
        raise ValueError("LLM response is missing a valid title")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response is missing valid content")

    if not isinstance(hashtags, list) or not all(
        isinstance(tag, str) for tag in hashtags
    ):
        raise ValueError("Invalid hashtags format")

    return {
        "title": title.strip(),
        "content": content.strip(),
        "hashtags": hashtags,
    }


def generate_marketing_post(
    topic: str,
    platform: str,
    target_audience: str,
    objective: str,
    language: str,
    knowledge: list[str],
):
    """Generate a new marketing post."""

    knowledge_context = "\n\n---\n\n".join(knowledge)

    if not knowledge_context:
        knowledge_context = (
            "No relevant company documents were retrieved. "
            "Do not invent IoTelliGen product specifications, "
            "customer claims, certifications or performance figures."
        )

    config = get_marketing_agent_config()

    model, temperature = _get_llm_settings(config)

    identity = config["identity"]

    skill_context, skills_used = _load_skill_context(platform)

    system_prompt = f"""
You are {config['name']}, an {identity['role']}
for {identity['company']}.

Company description:
{identity['description']}

Primary market:
{identity['primary_market']}

Primary language:
{identity['primary_language']}

Follow the marketing skills below.

MARKETING SKILLS:
{skill_context}

COMPANY KNOWLEDGE RULES:
1. Use supplied company knowledge as the source of truth.
2. Never invent product specifications, customer names, results,
   certifications or performance figures.
3. Distinguish general industry knowledge from verified company facts.
4. Write for the specified target audience.
5. Avoid exaggerated claims and generic AI-sounding language.
6. Return valid JSON only, without Markdown code fences.

Required JSON structure:
{{
  "title": "Post title",
  "content": "Complete post content",
  "hashtags": ["#Example1", "#Example2"]
}}
"""

    user_prompt = f"""
TOPIC:
{topic}

PLATFORM:
{platform}

TARGET AUDIENCE:
{target_audience}

MARKETING OBJECTIVE:
{objective}

LANGUAGE:
{language}

COMPANY KNOWLEDGE:
{knowledge_context}

Create the marketing post.
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
    )

    raw_content = response.choices[0].message.content
    result = _parse_llm_json(raw_content)

    return {
        **result,
        "llm_model": model,
        "skills_used": skills_used,
    }


def revise_marketing_post(
    topic: str,
    previous_title: str,
    previous_content: str,
    previous_hashtags: list[str],
    instructions: str,
    platform: str,
    target_audience: str,
    objective: str,
    language: str,
    knowledge: list[str],
):
    """Revise an existing marketing post."""

    knowledge_context = "\n\n---\n\n".join(knowledge)

    if not knowledge_context:
        knowledge_context = (
            "No relevant company knowledge was retrieved. "
            "Do not invent company-specific capabilities, "
            "specifications, certifications or results."
        )

    config = get_marketing_agent_config()

    model, temperature = _get_llm_settings(config)

    identity = config["identity"]

    skill_context, skills_used = _load_skill_context(platform)

    system_prompt = f"""
You are {config['name']}, an {identity['role']}
for {identity['company']}.

Company description:
{identity['description']}

Primary market:
{identity['primary_market']}

Your task is to revise an existing marketing post based on
the user's instructions.

Follow the marketing skills below when revising the content.

MARKETING SKILLS:
{skill_context}

REVISION RULES:
1. Preserve correct information from the existing draft.
2. Follow the new user instructions carefully.
3. Use retrieved company knowledge as the source of truth
   for company-specific claims.
4. Never treat the previous draft as verified evidence.
5. Never invent product capabilities, customers, results,
   certifications or performance figures.
6. Keep the writing natural and appropriate for the platform.
7. Return valid JSON only, without Markdown code fences.

Required JSON structure:
{{
  "title": "Revised title",
  "content": "Complete revised post",
  "hashtags": ["#Example1", "#Example2"]
}}
"""

    user_prompt = f"""
TOPIC:
{topic}

PLATFORM:
{platform}

TARGET AUDIENCE:
{target_audience}

OBJECTIVE:
{objective}

LANGUAGE:
{language}

PREVIOUS TITLE:
{previous_title}

PREVIOUS CONTENT:
{previous_content}

PREVIOUS HASHTAGS:
{json.dumps(previous_hashtags)}

USER MODIFICATION INSTRUCTIONS:
{instructions}

VERIFIED COMPANY KNOWLEDGE:
{knowledge_context}

Revise the post. Return the complete new version,
not just the changes.
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
    )

    raw_content = response.choices[0].message.content
    result = _parse_llm_json(raw_content)

    return {
        **result,
        "llm_model": model,
        "skills_used": skills_used,
    }
