from pathlib import Path

SKILLS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "marketing"
)


def load_skill(relative_path: str) -> str:
    """
    Load a marketing skill from the local skills directory.
    """

    skill_path = (SKILLS_DIR / relative_path).resolve()

    if not skill_path.is_relative_to(SKILLS_DIR.resolve()):
        raise ValueError("Invalid skill path")

    if not skill_path.is_file():
        raise FileNotFoundError(
            f"Skill not found: {relative_path}"
        )

    return skill_path.read_text(encoding="utf-8")


def load_marketing_skills(platform: str) -> dict[str, str]:
    """
    Load common and platform-specific marketing skills.
    """

    platform = platform.lower()

    allowed_platforms = {
        "linkedin",
        "facebook",
        "instagram",
        "youtube",
        "tiktok",
    }

    if platform not in allowed_platforms:
        raise ValueError(f"Unsupported platform: {platform}")

    return {
        "brand_guidelines": load_skill(
            "brand-guidelines/skill.md"
        ),
        "platform": load_skill(
            f"platforms/{platform}.md"
        ),
        "technical_content": load_skill(
            "content/technical-content.md"
        ),
        "storytelling": load_skill(
            "content/storytelling.md"
        ),
        "marketing_funnel": load_skill(
            "strategy/marketing-funnel.md"
        ),
    }
