
import logging
import os
import re

from pathlib import Path

import requests


logger = logging.getLogger(__name__)

DOCLING_URL = os.getenv(
    "DOCLING_URL",
    "http://docling:5001",
)

DOCLING_TIMEOUT = int(
    os.getenv("DOCLING_TIMEOUT", "600")
)


def extract_document(path: Path, extension: str):
    """
    Extract a document using the self-hosted Docling Serve API.

    Returns extracted Markdown and parser metadata.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Document not found: {path}")

    url = f"{DOCLING_URL.rstrip('/')}/v1/convert/file"

    logger.info("Sending document to Docling: %s", path.name)

    with path.open("rb") as file:
        response = requests.post(
            url,
            files={
                "files": (
                    path.name,
                    file,
                    "application/octet-stream",
                )
            },
            timeout=DOCLING_TIMEOUT,
        )

    response.raise_for_status()

    result = response.json()

    if result.get("status") != "success":
        raise RuntimeError(
            f"Docling processing failed: {result.get('errors')}"
        )

    document = result.get("document") or {}
    markdown = document.get("md_content")

    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Docling returned empty Markdown content")

    logger.info(
        "Docling extracted %d characters from %s",
        len(markdown),
        path.name,
    )

    return {
        "page_number": None,
        "text": markdown,
        "processing_time": result.get("processing_time"),
        "confidence": result.get("confidence"),
    }


def chunk_text(
    text: str,
    chunk_size: int = 1800,
    overlap: int = 250,
):
    """
    Split Markdown into context-preserving chunks.

    Preserves paragraph boundaries where possible.
    """

    if chunk_size <= overlap:
        raise ValueError("Chunk size must exceed overlap")

    text = text.strip()

    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)

    chunks = []
    current = ""

    def split_long_paragraph(paragraph):
        sentences = re.split(
            r"(?<=[.!?])\s+",
            paragraph.strip(),
        )

        parts = []
        buffer = ""

        for sentence in sentences:
            words = sentence.split()

            for word in words:
                candidate = f"{buffer} {word}".strip()

                if len(candidate) > chunk_size and buffer:
                    parts.append(buffer)
                    buffer = word
                else:
                    buffer = candidate

        if buffer:
            parts.append(buffer)

        return parts

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""

            chunks.extend(split_long_paragraph(paragraph))
            continue

        candidate = f"{current}\n\n{paragraph}".strip()

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)

            current = paragraph

    if current:
        chunks.append(current)

    final_chunks = []

    for index, chunk in enumerate(chunks):
        if index == 0:
            final_chunks.append(chunk)
            continue

        previous = chunks[index - 1]
        overlap_text = previous[-overlap:]

        final_chunks.append(
            f"{overlap_text}\n\n{chunk}"
        )

    return final_chunks


def process_document(path: Path, extension: str):
    """
    Parse a document with Docling and return database-ready chunks.

    Compatible with the existing documents.py processing endpoint.
    """

    extracted = extract_document(path, extension)

    chunks = chunk_text(extracted["text"])

    result = []

    for chunk_index, chunk in enumerate(chunks):
        result.append({
            "chunk_index": chunk_index,
            "page_number": extracted["page_number"],
            "content": chunk,
        })

    if not result:
        raise ValueError("No extractable text found")

    return result
