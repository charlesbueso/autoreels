"""Facebook Page video upload via Meta Graph API."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


async def upload_video_to_page(
    video_path: Path,
    page_id: str,
    access_token: str,
    description: str = "",
) -> dict:
    """Upload a video to a Facebook Page.

    Uses the resumable upload flow for reliability.

    Returns the API response dict with video ID.
    """
    file_size = video_path.stat().st_size

    # Step 1: Start upload session
    async with httpx.AsyncClient(timeout=120) as client:
        start_resp = await client.post(
            f"{GRAPH_API_BASE}/{page_id}/videos",
            params={"access_token": access_token},
            data={
                "upload_phase": "start",
                "file_size": str(file_size),
            },
        )
        start_resp.raise_for_status()
        start_data = start_resp.json()
        upload_session_id = start_data["upload_session_id"]
        video_id = start_data["video_id"]
        logger.info("FB upload session started: video_id=%s", video_id)

        # Step 2: Transfer the file
        with open(video_path, "rb") as f:
            transfer_resp = await client.post(
                f"{GRAPH_API_BASE}/{page_id}/videos",
                params={"access_token": access_token},
                data={
                    "upload_phase": "transfer",
                    "upload_session_id": upload_session_id,
                    "start_offset": "0",
                },
                files={"video_file_chunk": (video_path.name, f, "video/mp4")},
            )
            transfer_resp.raise_for_status()

        # Step 3: Finish upload
        finish_resp = await client.post(
            f"{GRAPH_API_BASE}/{page_id}/videos",
            params={"access_token": access_token},
            data={
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "description": description,
                "published": "true",
            },
        )
        finish_resp.raise_for_status()
        result = finish_resp.json()
        logger.info("FB video published: %s", result)
        return result
