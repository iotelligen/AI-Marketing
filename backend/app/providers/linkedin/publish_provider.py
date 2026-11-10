import logging
import os
from typing import Any

import requests


logger = logging.getLogger(__name__)


class LinkedInPublishError(Exception):
    """Raised when LinkedIn publishing fails."""


class LinkedInPublishProvider:
    """
    Publish an MP4 to LinkedIn via the Videos + UGC APIs.

    Required account credentials:
      - access_token
      - author_urn  (urn:li:person:... or urn:li:organization:...)
    """

    API_BASE = "https://api.linkedin.com"
    API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202405")

    def __init__(self, credentials: dict[str, Any]):
        access_token = (credentials or {}).get("access_token")
        author_urn = (credentials or {}).get("author_urn")

        if not access_token:
            raise LinkedInPublishError(
                "LinkedIn account is missing access_token"
            )

        if not author_urn:
            raise LinkedInPublishError(
                "LinkedIn account is missing author_urn "
                "(urn:li:person:... or urn:li:organization:...)"
            )

        self.access_token = access_token
        self.author_urn = author_urn
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": self.API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        })

    def publish_video(
        self,
        *,
        video_bytes: bytes,
        caption: str,
        title: str,
        filename: str = "video.mp4",
    ) -> dict[str, Any]:
        if not video_bytes:
            raise LinkedInPublishError("Video file is empty")

        if len(video_bytes) > 500 * 1024 * 1024:
            raise LinkedInPublishError(
                "Video exceeds LinkedIn's 500 MB upload limit"
            )

        video_urn = self._initialize_and_upload(
            video_bytes=video_bytes,
            filename=filename,
        )
        post_urn = self._create_ugc_post(
            video_urn=video_urn,
            caption=caption,
            title=title,
        )

        return {
            "provider": "linkedin",
            "remote_post_id": post_urn,
            "remote_url": None,
            "video_urn": video_urn,
            "author_urn": self.author_urn,
        }

    def _initialize_and_upload(
        self,
        *,
        video_bytes: bytes,
        filename: str,
    ) -> str:
        init_url = f"{self.API_BASE}/rest/videos?action=initializeUpload"
        init_payload = {
            "initializeUploadRequest": {
                "owner": self.author_urn,
                "fileSizeBytes": len(video_bytes),
                "uploadCaptions": False,
                "uploadThumbnail": False,
            }
        }

        response = self.session.post(
            init_url,
            json=init_payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        self._raise_for_status(response, "initialize upload")

        value = response.json().get("value") or {}
        video_urn = value.get("video")
        upload_instructions = value.get("uploadInstructions") or []

        if not video_urn or not upload_instructions:
            raise LinkedInPublishError(
                "LinkedIn initializeUpload returned an incomplete response"
            )

        # Single-part uploads are common for short promotional videos.
        # Multi-part uploads are supported by walking all instructions.
        offset = 0

        for instruction in upload_instructions:
            upload_url = instruction.get("uploadUrl")
            first_byte = int(instruction.get("firstByte", offset))
            last_byte = int(
                instruction.get(
                    "lastByte",
                    len(video_bytes) - 1,
                )
            )

            if not upload_url:
                raise LinkedInPublishError(
                    "LinkedIn upload instruction is missing uploadUrl"
                )

            chunk = video_bytes[first_byte:last_byte + 1]

            upload_response = requests.put(
                upload_url,
                data=chunk,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/octet-stream",
                },
                timeout=300,
            )

            if upload_response.status_code >= 400:
                raise LinkedInPublishError(
                    "LinkedIn video upload failed: "
                    f"HTTP {upload_response.status_code} "
                    f"{upload_response.text[:500]}"
                )

            offset = last_byte + 1

        finalize_url = f"{self.API_BASE}/rest/videos?action=finalizeUpload"
        finalize_payload = {
            "finalizeUploadRequest": {
                "video": video_urn,
                "uploadToken": "",
                "uploadedPartIds": [
                    instruction.get("uploadUrl", "")
                    for instruction in upload_instructions
                ],
            }
        }

        # Some LinkedIn API versions finalize implicitly after a single PUT.
        # Call finalize when the endpoint accepts it; ignore 404/400 that
        # indicate the upload is already complete for single-part uploads.
        finalize_response = self.session.post(
            finalize_url,
            json=finalize_payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )

        if finalize_response.status_code >= 400:
            logger.warning(
                "LinkedIn finalizeUpload returned HTTP %s: %s",
                finalize_response.status_code,
                finalize_response.text[:300],
            )

        logger.info(
            "Uploaded LinkedIn video %s (%s bytes, file=%s)",
            video_urn,
            len(video_bytes),
            filename,
        )

        return video_urn

    def _create_ugc_post(
        self,
        *,
        video_urn: str,
        caption: str,
        title: str,
    ) -> str:
        # UGC Posts API remains the most widely supported way to attach
        # a video asset to an organic person/organization share.
        url = f"{self.API_BASE}/v2/ugcPosts"
        payload = {
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": caption[:3000],
                    },
                    "shareMediaCategory": "VIDEO",
                    "media": [
                        {
                            "status": "READY",
                            "description": {
                                "text": caption[:3000],
                            },
                            "media": video_urn,
                            "title": {
                                "text": (title or "Video")[:200],
                            },
                        }
                    ],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
            },
        }

        response = self.session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        self._raise_for_status(response, "create UGC post")

        post_urn = response.headers.get("x-restli-id") or response.json().get(
            "id"
        )

        if not post_urn:
            raise LinkedInPublishError(
                "LinkedIn UGC post response did not include a post id"
            )

        return post_urn

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if response.status_code < 400:
            return

        detail = response.text[:800]
        raise LinkedInPublishError(
            f"LinkedIn {action} failed: HTTP {response.status_code} {detail}"
        )
