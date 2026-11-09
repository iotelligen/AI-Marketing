
import json
import os

from pathlib import Path
from typing import Any


AGENTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "agents"
)


def load_agent_config(agent_id: str) -> dict[str, Any]:
    """
    Load configuration for an agent.
    """

    config_path = (
        AGENTS_DIR / agent_id / "agent.json"
    ).resolve()

    if not config_path.is_relative_to(AGENTS_DIR.resolve()):
        raise ValueError("Invalid agent ID")

    if not config_path.is_file():
        raise FileNotFoundError(
            f"Agent configuration not found: {agent_id}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if config.get("agent_id") != agent_id:
        raise ValueError("Agent ID mismatch in configuration")

    return config



def get_agent_model(
    config: dict,
    environment_variable: str = "MARKETING_MODEL",
) -> str:
    """
    Environment variable overrides the configured model.
    """

    return os.getenv(
        environment_variable,
        config["model"]["model"],
    )


def validate_workspace_access(
    config: dict,
    workspace_slug: str,
) -> bool:
    """
    Check whether the agent is allowed to access a workspace.
    """

    allowed_workspaces = config.get(
        "permissions", {}
    ).get("allowed_workspaces", [])

    return workspace_slug in allowed_workspaces


def get_agent_platforms(config: dict) -> list[str]:
    return config.get("platforms", [])
