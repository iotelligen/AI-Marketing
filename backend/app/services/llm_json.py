import logging
import re

from typing import Callable, TypeVar

from litellm import completion


logger = logging.getLogger(__name__)

T = TypeVar("T")


def strip_code_fences(raw_content: str) -> str:
    """Remove Markdown code fences if a provider ignores JSON mode."""
    cleaned = (raw_content or "").strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    return re.sub(r"\s*```$", "", cleaned)


def complete_json(
    *,
    model: str,
    temperature: float,
    system_prompt: str,
    user_prompt: str,
    parse: Callable[[str], T],
    max_attempts: int = 2,
    agent_label: str = "Agent",
) -> T:
    """
    Ask a model for a JSON object and validate it with `parse`.

    `parse` raises ValueError when the answer is unusable. The error is
    sent back to the model so it can correct itself, which matters when
    nobody is watching the run. The last error is raised if every
    attempt fails.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error: ValueError | None = None

    for attempt in range(1, max_attempts + 1):
        response = completion(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or ""

        try:
            return parse(raw_content)
        except ValueError as exc:
            last_error = exc

            logger.warning(
                "%s returned an unusable answer (attempt %s of %s): %s",
                agent_label,
                attempt,
                max_attempts,
                exc,
            )

            messages.append({
                "role": "assistant",
                "content": raw_content,
            })
            messages.append({
                "role": "user",
                "content": (
                    "Your previous answer was rejected for this reason:\n"
                    f"{exc}\n\n"
                    "Return the corrected, complete JSON object only."
                ),
            })

    raise last_error
