import os
import logging
import requests

logger = logging.getLogger(__name__)

DOCLING_URL = os.getenv(
    "DOCLING_URL",
    "http://docling:5001",
)


def parse_document(file_path: str) -> dict:
    url = f"{DOCLING_URL}/v1/convert/file"

    with open(file_path, "rb") as file:
        response = requests.post(
            url,
            files={
                "files": (
                    os.path.basename(file_path),
                    file,
                    "application/octet-stream",
                )
            },
            timeout=600,
        )

    response.raise_for_status()

    result = response.json()

    if result.get("status") != "success":
        raise RuntimeError(
            f"Docling processing failed: {result.get('errors')}"
        )

    document = result.get("document", {})
    markdown = document.get("md_content")

    if not markdown:
        raise RuntimeError("Docling returned empty Markdown content")

    return {
        "filename": document.get("filename"),
        "markdown": markdown,
        "processing_time": result.get("processing_time"),
        "confidence": result.get("confidence"),
        "status": result.get("status"),
    }
