
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests


class FalImageProviderError(Exception):
    """Raised when fal.ai image generation fails."""


class FalImageProvider:
    BASE_URL = "https://queue.fal.run"

    def __init__(self):
        self.api_key = os.getenv("FAL_KEY")
        self.model = os.getenv(
            "FAL_IMAGE_MODEL",
            "fal-ai/flux/dev",
        )
        self.storage_root = Path(
            os.getenv("ASSET_STORAGE", "/data/assets")
        )

        if not self.api_key:
            raise FalImageProviderError(
                "FAL_KEY environment variable is not configured"
            )

        if not re.fullmatch(r"[a-zA-Z0-9/_-]+", self.model):
            raise FalImageProviderError("Invalid fal.ai model identifier")

        self.headers = {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }

        self.session = requests.Session()

    @staticmethod
    def _validate_queue_url(url: str) -> None:
        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "queue.fal.run"
            or parsed.port not in (None, 443)
        ):
            raise FalImageProviderError(
                "Unexpected fal.ai queue URL"
            )

    @staticmethod
    def _validate_image_url(url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme != "https" or not parsed.hostname:
            raise FalImageProviderError(
                "Invalid generated image URL"
            )

        allowed_hosts = (
            "fal.media",
            "fal.ai",
            "storage.googleapis.com",
        )

        if not any(
            parsed.hostname == host
            or parsed.hostname.endswith("." + host)
            for host in allowed_hosts
        ):
            raise FalImageProviderError(
                "Generated image URL uses an untrusted host"
            )

    def generate_image(
        self,
        prompt: str,
        job_id: str,
        scene_number: int,
        aspect_ratio: str = "portrait",
        max_wait_seconds: int = 600,
    ) -> dict:
        if not prompt.strip():
            raise ValueError("Image prompt cannot be empty")

        if not re.fullmatch(r"[a-fA-F0-9-]{36}", job_id):
            raise ValueError("Invalid video job ID")

        if scene_number < 1:
            raise ValueError("Scene number must be positive")

        # Submit image generation request.
        submit_url = f"{self.BASE_URL}/{self.model}"

        image_sizes = {
            "9:16": "portrait_16_9",
            "16:9": "landscape_16_9",
            "1:1": "square_hd",
            "portrait": "portrait_16_9",
            "landscape": "landscape_16_9",
            "square": "square_hd",
        }

        if aspect_ratio not in image_sizes:
            raise ValueError(
                f"Unsupported aspect ratio: {aspect_ratio}"
            )

        image_sizes = {
            "9:16": "portrait_16_9",
            "16:9": "landscape_16_9",
            "1:1": "square_hd",
            "portrait": "portrait_16_9",
            "landscape": "landscape_16_9",
            "square": "square_hd",
        }

        if aspect_ratio not in image_sizes:
            raise ValueError(
                f"Unsupported aspect ratio: {aspect_ratio}"
            )

        payload = {
            "prompt": prompt,
            "image_size": image_sizes[aspect_ratio],
            "num_images": 1,
        }

        response = self.session.post(
            submit_url,
            headers=self.headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        submission = response.json()

        request_id = submission.get("request_id")
        status_url = submission.get("status_url")
        response_url = submission.get("response_url")

        if not request_id or not status_url or not response_url:
            raise FalImageProviderError(
                "fal.ai returned an incomplete queue response"
            )

        self._validate_queue_url(status_url)
        self._validate_queue_url(response_url)

        # Poll queue until generation completes.
        deadline = time.monotonic() + max_wait_seconds

        while time.monotonic() < deadline:
            status_response = self.session.get(
                status_url,
                headers=self.headers,
                timeout=30,
            )
            status_response.raise_for_status()

            status_data = status_response.json()
            status = status_data.get("status")

            if status == "COMPLETED":
                if status_data.get("error"):
                    raise FalImageProviderError(
                        status_data["error"]
                    )
                break

            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise FalImageProviderError(
                    f"Unexpected fal.ai status: {status}"
                )

            time.sleep(5)

        else:
            raise TimeoutError(
                "fal.ai image generation timed out"
            )

        # Retrieve completed result.
        result_response = self.session.get(
            response_url,
            headers=self.headers,
            timeout=60,
        )
        result_response.raise_for_status()

        result = result_response.json()
        images = result.get("images", [])

        if not images or not images[0].get("url"):
            raise FalImageProviderError(
                "fal.ai response did not contain an image URL"
            )

        image_url = images[0]["url"]
        self._validate_image_url(image_url)

        # Download generated image to persistent local storage.
        scene_dir = (
            self.storage_root
            / job_id
            / f"scene_{scene_number:02d}"
        )
        scene_dir.mkdir(parents=True, exist_ok=True)

        image_response = self.session.get(
            image_url,
            stream=True,
            timeout=120,
        )
        image_response.raise_for_status()

        content_type = image_response.headers.get(
            "Content-Type",
            "image/png",
        ).split(";")[0].lower()

        extensions = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }

        extension = extensions.get(content_type)

        if not extension:
            raise FalImageProviderError(
                f"Unsupported image content type: {content_type}"
            )

        filename = f"image_{uuid.uuid4().hex}{extension}"
        output_path = scene_dir / filename

        max_bytes = 30 * 1024 * 1024
        total_bytes = 0

        try:
            with output_path.open("wb") as output:
                for chunk in image_response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    total_bytes += len(chunk)

                    if total_bytes > max_bytes:
                        raise FalImageProviderError(
                            "Generated image exceeds 30 MB limit"
                        )

                    output.write(chunk)

        except Exception:
            output_path.unlink(missing_ok=True)
            raise

        if total_bytes == 0:
            output_path.unlink(missing_ok=True)
            raise FalImageProviderError(
                "Downloaded image is empty"
            )

        return {
            "provider": "fal",
            "model": self.model,
            "request_id": request_id,
            "filename": filename,
            "storage_path": str(output_path),
            "source_url": image_url,
            "mime_type": content_type,
            "file_size_bytes": total_bytes,
            "scene_number": scene_number,
        }
