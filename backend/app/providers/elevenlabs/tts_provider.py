import os
import re
import uuid
from pathlib import Path

import requests


class ElevenLabsTTSError(Exception):
    """Raised when ElevenLabs text-to-speech fails."""


class ElevenLabsTTSProvider:
    """
    Generate narration audio with the ElevenLabs TTS API.

    Free-plan friendly defaults:
      - model: eleven_flash_v2_5 (0.5 credit/character via API)
      - output: mp3_44100_128
      - voice: configurable; default is a built-in English voice
    """

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = os.getenv(
            "ELEVENLABS_VOICE_ID",
            "JBFqnCBsd6RMkjVDRZzb",
        )
        self.model_id = os.getenv(
            "ELEVENLABS_MODEL_ID",
            "eleven_flash_v2_5",
        )
        self.storage_root = Path(
            os.getenv("ASSET_STORAGE", "/data/assets")
        )

        if not self.api_key:
            raise ElevenLabsTTSError(
                "ELEVENLABS_API_KEY environment variable is not configured"
            )

        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.voice_id):
            raise ElevenLabsTTSError("Invalid ElevenLabs voice id")

        self.headers = {
            "xi-api-key": self.api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        self.session = requests.Session()

    def synthesize(
        self,
        *,
        text: str,
        job_id: str,
        scene_number: int,
    ) -> dict:
        cleaned = (text or "").strip()

        if not cleaned:
            raise ValueError("Narration text cannot be empty")

        if len(cleaned) > 2500:
            raise ValueError(
                "Narration is too long for one scene (max 2500 characters)"
            )

        if not re.fullmatch(r"[a-fA-F0-9-]{36}", job_id):
            raise ValueError("Invalid video job ID")

        if scene_number < 1:
            raise ValueError("Scene number must be positive")

        url = f"{self.BASE_URL}/text-to-speech/{self.voice_id}"
        payload = {
            "text": cleaned,
            "model_id": self.model_id,
        }

        response = self.session.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=120,
            # Free-tier compatible bitrate.
            params={"output_format": "mp3_44100_128"},
        )

        if response.status_code >= 400:
            detail = response.text[:800]
            raise ElevenLabsTTSError(
                f"ElevenLabs TTS failed: HTTP {response.status_code} {detail}"
            )

        audio_bytes = response.content

        if not audio_bytes:
            raise ElevenLabsTTSError("ElevenLabs returned empty audio")

        if len(audio_bytes) > 20 * 1024 * 1024:
            raise ElevenLabsTTSError("Generated audio exceeds 20 MB limit")

        scene_dir = (
            self.storage_root
            / job_id
            / f"scene_{scene_number:02d}"
        )
        scene_dir.mkdir(parents=True, exist_ok=True)

        filename = f"narration_{uuid.uuid4().hex}.mp3"
        output_path = scene_dir / filename
        output_path.write_bytes(audio_bytes)

        character_cost = response.headers.get("character-cost")
        request_id = response.headers.get("request-id")

        return {
            "provider": "elevenlabs",
            "model": self.model_id,
            "voice_id": self.voice_id,
            "request_id": request_id,
            "character_cost": character_cost,
            "filename": filename,
            "storage_path": str(output_path),
            "mime_type": "audio/mpeg",
            "file_size_bytes": len(audio_bytes),
            "scene_number": scene_number,
            "text_length": len(cleaned),
        }
