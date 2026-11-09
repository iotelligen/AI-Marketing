import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests


class FalVideoProviderError(Exception):
    pass


class FalVideoProvider:
    BASE_URL = "https://queue.fal.run"

    def __init__(self):
        self.api_key = os.getenv("FAL_KEY")
        self.model = os.getenv(
            "FAL_VIDEO_MODEL",
            "bytedance/seedance-2.0/fast/image-to-video",
        )
        self.resolution = os.getenv("FAL_VIDEO_RESOLUTION", "720p")
        self.storage_root = Path(
            os.getenv("ASSET_STORAGE", "/data/assets")
        )

        if not self.api_key:
            raise FalVideoProviderError(
                "FAL_KEY environment variable is not configured"
            )

        if not re.fullmatch(r"[a-zA-Z0-9/_.-]+", self.model):
            raise FalVideoProviderError("Invalid fal.ai model identifier")

        if self.resolution not in ("480p", "720p"):
            raise FalVideoProviderError(
                "FAL_VIDEO_RESOLUTION must be 480p or 720p"
            )

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
            raise FalVideoProviderError(
                "Unexpected fal.ai queue URL"
            )

    @staticmethod
    def _validate_fal_media_url(url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme != "https" or not parsed.hostname:
            raise FalVideoProviderError("Invalid fal.ai media URL")

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
            raise FalVideoProviderError(
                "fal.ai media URL uses an untrusted host"
            )

    def generate_video(
        self,
        prompt: str,
        image_url: str,
        job_id: str,
        scene_number: int,
        aspect_ratio: str,
        duration_seconds: int,
        max_wait_seconds: int = 1200,
    ) -> dict:
        if not prompt.strip():
            raise ValueError("Video motion prompt cannot be empty")

        if not re.fullmatch(r"[a-fA-F0-9-]{36}", job_id):
            raise ValueError("Invalid video job ID")

        if scene_number < 1:
            raise ValueError("Scene number must be positive")

        if aspect_ratio not in ("9:16", "16:9", "1:1"):
            raise ValueError("Unsupported video aspect ratio")

        if duration_seconds < 4 or duration_seconds > 15:
            raise ValueError(
                "Video duration must be between 4 and 15 seconds"
            )

        self._validate_fal_media_url(image_url)

        response = self.session.post(
            f"{self.BASE_URL}/{self.model}",
            headers=self.headers,
            json={
                "prompt": prompt,
                "image_url": image_url,
                "duration": str(duration_seconds),
                "resolution": self.resolution,
                "aspect_ratio": aspect_ratio,
                "generate_audio": False,
            },
            timeout=60,
        )
        response.raise_for_status()

        submission = response.json()
        request_id = submission.get("request_id")
        status_url = submission.get("status_url")
        response_url = submission.get("response_url")

        if not request_id or not status_url or not response_url:
            raise FalVideoProviderError(
                "fal.ai returned an incomplete queue response"
            )

        self._validate_queue_url(status_url)
        self._validate_queue_url(response_url)

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
                    raise FalVideoProviderError(status_data["error"])
                break

            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise FalVideoProviderError(
                    f"Unexpected fal.ai status: {status}"
                )

            time.sleep(5)
        else:
            raise TimeoutError("fal.ai video generation timed out")

        result_response = self.session.get(
            response_url,
            headers=self.headers,
            timeout=60,
        )
        result_response.raise_for_status()
        result = result_response.json()
        video = result.get("video") or {}
        video_url = video.get("url")

        if not video_url:
            raise FalVideoProviderError(
                "fal.ai response did not contain a video URL"
            )

        self._validate_fal_media_url(video_url)

        scene_dir = (
            self.storage_root
            / job_id
            / f"scene_{scene_number:02d}"
        )
        scene_dir.mkdir(parents=True, exist_ok=True)

        video_response = self.session.get(
            video_url,
            stream=True,
            timeout=180,
        )
        video_response.raise_for_status()
        content_type = video_response.headers.get(
            "Content-Type",
            "video/mp4",
        ).split(";")[0].lower()

        if content_type != "video/mp4":
            raise FalVideoProviderError(
                f"Unsupported generated video content type: {content_type}"
            )

        filename = f"video_{uuid.uuid4().hex}.mp4"
        output_path = scene_dir / filename
        max_bytes = 200 * 1024 * 1024
        total_bytes = 0

        try:
            with output_path.open("wb") as output:
                for chunk in video_response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    total_bytes += len(chunk)

                    if total_bytes > max_bytes:
                        raise FalVideoProviderError(
                            "Generated video exceeds 200 MB limit"
                        )

                    output.write(chunk)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

        if total_bytes == 0:
            output_path.unlink(missing_ok=True)
            raise FalVideoProviderError(
                "Downloaded video is empty"
            )

        return {
            "provider": "fal",
            "model": self.model,
            "request_id": request_id,
            "filename": filename,
            "storage_path": str(output_path),
            "source_url": video_url,
            "mime_type": content_type,
            "file_size_bytes": total_bytes,
            "duration_seconds": duration_seconds,
            "scene_number": scene_number,
        }
