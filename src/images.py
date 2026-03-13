"""Image fetching — Unsplash API search + download + local cache.

Provides background images for text slides and decorative assets
for reel segments.  Results are cached locally so the same query
returns consistent images across edits and re-renders.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ROOT / "cache" / "images"

# Unsplash API base
_UNSPLASH_API = "https://api.unsplash.com"


def _cache_key(query: str) -> str:
    """Deterministic cache key for a search query."""
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]


async def search_and_download(
    query: str,
    api_key: str,
    *,
    width: int = 480,
    height: int = 832,
    index: int = 0,
) -> Path | None:
    """Search Unsplash for *query* and download the result at *index*.

    Returns the local cached file path, or None on failure.
    The image is cropped/resized to fit *width* x *height* (portrait).
    """
    if not api_key:
        logger.warning("No UNSPLASH_ACCESS_KEY — skipping image fetch")
        return None

    cache_name = f"{_cache_key(query)}_{index}.jpg"
    cache_path = _CACHE_DIR / cache_name
    if cache_path.exists():
        logger.info("Image cache hit: %s → %s", query, cache_path.name)
        return cache_path

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_UNSPLASH_API}/search/photos",
                params={
                    "query": query,
                    "per_page": max(index + 1, 5),
                    "orientation": "portrait",
                },
                headers={"Authorization": f"Client-ID {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results or index >= len(results):
            logger.warning("Unsplash returned no results for '%s'", query)
            return None

        # Use the "regular" size URL (1080px wide, good quality)
        photo = results[index]
        image_url = photo.get("urls", {}).get("regular")
        if not image_url:
            return None

        # Download the image
        async with httpx.AsyncClient(timeout=30) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(img_resp.content)
        logger.info("Downloaded image for '%s' → %s", query, cache_path.name)

        # Resize/crop to target dimensions
        _crop_to_fit(cache_path, width, height)

        return cache_path

    except Exception:
        logger.exception("Failed to fetch image for '%s'", query)
        return None


def _crop_to_fit(image_path: Path, target_w: int, target_h: int) -> None:
    """Crop and resize an image file to exactly target_w x target_h (center crop)."""
    img = Image.open(image_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider — crop sides
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, src_h))
    else:
        # Source is taller — crop top/bottom
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        img = img.crop((0, offset, src_w, offset + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)
    img.save(image_path, "JPEG", quality=90)


def load_image(path: Path | str, max_w: int, max_h: int) -> Image.Image | None:
    """Load an image and fit within max_w x max_h, preserving aspect ratio."""
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return None
    try:
        img = Image.open(p).convert("RGBA")
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        return img
    except Exception:
        logger.exception("Failed to load image: %s", p)
        return None
