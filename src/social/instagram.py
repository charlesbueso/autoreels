"""Instagram Reels upload via Meta Graph API (Content Publishing API)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


async def _wait_for_container(
    client: httpx.AsyncClient,
    ig_account_id: str,
    container_id: str,
    access_token: str,
    max_wait: int = 300,
    poll_interval: int = 5,
) -> str:
    """Poll the container status until it's FINISHED or errors out."""
    elapsed = 0
    while elapsed < max_wait:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": access_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status_code")
        logger.debug("IG container %s status: %s", container_id, status)

        if status == "FINISHED":
            return status
        if status == "ERROR":
            raise RuntimeError(f"IG container failed: {data}")

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"IG container {container_id} not ready after {max_wait}s")


async def upload_reel(
    video_url: str,
    ig_account_id: str,
    access_token: str,
    caption: str = "",
) -> dict:
    """Upload a Reel to Instagram via the Content Publishing API.

    NOTE: Instagram requires the video to be accessible via a public URL.
    For local files, you must first host the video (e.g., upload to your own
    server or a temporary file host), then pass that URL here.

    Args:
        video_url: Public URL to the video file.
        ig_account_id: Instagram Business Account ID.
        access_token: Page Access Token with instagram_content_publish permission.
        caption: Post caption with hashtags.

    Returns:
        API response dict with the published media ID.
    """
    async with httpx.AsyncClient(timeout=120) as client:
        # Step 1: Create media container
        create_resp = await client.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media",
            params={"access_token": access_token},
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
            },
        )
        create_resp.raise_for_status()
        container_id = create_resp.json()["id"]
        logger.info("IG container created: %s", container_id)

        # Step 2: Wait for processing
        await _wait_for_container(client, ig_account_id, container_id, access_token)

        # Step 3: Publish
        publish_resp = await client.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media_publish",
            params={"access_token": access_token},
            data={"creation_id": container_id},
        )
        publish_resp.raise_for_status()
        result = publish_resp.json()
        logger.info("IG reel published: %s", result)
        return result


async def upload_reel_from_local(
    video_path: Path,
    ig_account_id: str,
    page_id: str,
    access_token: str,
    caption: str = "",
) -> dict:
    """Upload a local video file as an IG Reel.

    Strategy: First upload to Facebook Page as an unpublished video to get a
    hosted URL, then use that URL for the IG Content Publishing API.

    This avoids needing a separate file hosting service.
    """
    # Upload to FB as unpublished to get a URL
    file_size = video_path.stat().st_size

    async with httpx.AsyncClient(timeout=120) as client:
        # Start FB upload
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

        # Transfer
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

        # Finish as unpublished
        finish_resp = await client.post(
            f"{GRAPH_API_BASE}/{page_id}/videos",
            params={"access_token": access_token},
            data={
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "published": "false",
            },
        )
        finish_resp.raise_for_status()
        fb_video_id = finish_resp.json().get("video_id", finish_resp.json().get("id"))

        # Wait a bit for FB to process, then get the source URL
        await asyncio.sleep(10)
        video_resp = await client.get(
            f"{GRAPH_API_BASE}/{fb_video_id}",
            params={
                "fields": "source",
                "access_token": access_token,
            },
        )
        video_resp.raise_for_status()
        video_url = video_resp.json()["source"]

        # Now publish to IG using the FB-hosted URL
        return await upload_reel(video_url, ig_account_id, access_token, caption)
