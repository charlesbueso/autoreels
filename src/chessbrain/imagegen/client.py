"""fal.ai client wrapper — async-style submit/result via fal_client.

Routes ``RenderRequest.model`` to the appropriate fal endpoint slug.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from chessbrain.brain.db import connect, new_id, utc_now_iso
from chessbrain.imagegen import cache as cache_mod
from chessbrain.imagegen.base import (
    COST_USD,
    RenderRequest,
    RenderResult,
    assemble_prompt,
    negative_prompt,
)
from chessbrain.settings import get_settings

log = logging.getLogger(__name__)


# fal.ai endpoint slugs (verified May 2026; update if fal renames).
FAL_ENDPOINTS: dict[str, str] = {
    "nano_banana": "fal-ai/nano-banana/edit",             # Nano Banana / Gemini 2.5 Flash Image (edit)
    "flux_dev": "fal-ai/flux/dev",
    "flux_pro": "fal-ai/flux-pro/v1.1-ultra",
    "ideogram_v3": "fal-ai/ideogram/v3",
}


def _ensure_fal_env() -> None:
    s = get_settings()
    if not s.fal_key:
        raise RuntimeError("FAL_KEY missing — set it in .env.local.")
    os.environ.setdefault("FAL_KEY", s.fal_key)


def _build_payload(req: RenderRequest, ref_urls: list[str]) -> dict[str, Any]:
    full_prompt = assemble_prompt(
        req.prompt,
        include_style=True,
        include_mascot_lock=bool(ref_urls),
    )
    base: dict[str, Any] = {"prompt": full_prompt}
    if req.seed is not None:
        base["seed"] = int(req.seed) & 0x7FFFFFFF

    if req.model == "nano_banana":
        # fal-ai/nano-banana/edit requires `image_urls` (plural, list<string>).
        base["image_urls"] = ref_urls
        base["aspect_ratio"] = req.aspect
        base["num_images"] = 1
        base["output_format"] = "png"
    elif req.model in ("flux_dev", "flux_pro"):
        base["aspect_ratio"] = req.aspect
        base["enable_safety_checker"] = False
        base["num_images"] = 1
    elif req.model == "ideogram_v3":
        base["aspect_ratio"] = req.aspect
        base["negative_prompt"] = negative_prompt()
        base["style"] = "DESIGN"
    return base


def _upload_refs(refs: list[Path]) -> list[str]:
    if not refs:
        return []
    import fal_client

    urls: list[str] = []
    for p in refs:
        urls.append(fal_client.upload_file(str(p)))
    return urls


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, timeout=60.0, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def _extract_image_url(result: dict[str, Any]) -> str:
    # Most fal models return {"images": [{"url": ...}]} or {"image": {"url": ...}}.
    if "images" in result and result["images"]:
        first = result["images"][0]
        return first["url"] if isinstance(first, dict) else first
    if "image" in result:
        img = result["image"]
        return img["url"] if isinstance(img, dict) else img
    if "output" in result:
        out = result["output"]
        if isinstance(out, list) and out:
            return out[0] if isinstance(out[0], str) else out[0].get("url", "")
        if isinstance(out, dict):
            return out.get("url", "")
    raise RuntimeError(f"Could not find image URL in fal result: {list(result.keys())}")


def _log_spend(model: str, cost: float, post_slug: str | None) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO spend_log (id, provider, model, units, cost_usd, post_slug, created_at)
               VALUES (?, 'fal.ai', ?, 1, ?, ?, ?)""",
            (new_id(), model, cost, post_slug, utc_now_iso()),
        )


def render(req: RenderRequest, *, post_slug: str | None = None) -> RenderResult:
    """Generate (or retrieve from cache) a single image."""
    _ensure_fal_env()
    s = get_settings()

    # Nano Banana is an *edit* endpoint — it needs at least one input image.
    # When the slide has no reference image, transparently fall back to the
    # configured text-to-image model so we don't 422 on `image_url required`.
    if req.model == "nano_banana" and not req.reference_images:
        fallback = s.runtime["imagegen"].get("fallback_model", "flux_dev")
        log.info("nano_banana requires a reference image; falling back to %s", fallback)
        req = RenderRequest(
            prompt=req.prompt,
            aspect=req.aspect,
            model=fallback,
            reference_images=req.reference_images,
            seed=req.seed,
            extra=req.extra,
        )

    full_prompt = assemble_prompt(
        req.prompt,
        include_style=True,
        include_mascot_lock=bool(req.reference_images),
    )
    sha = cache_mod.cache_key(req.model, full_prompt, req.seed, req.reference_images)
    cached_path = cache_mod.lookup(sha)
    if cached_path is not None:
        return RenderResult(
            path=cached_path,
            model=req.model,
            prompt=full_prompt,
            seed=req.seed,
            cost_usd=0.0,
            cached=True,
        )

    if req.model not in FAL_ENDPOINTS:
        raise ValueError(f"Unknown image model: {req.model}")
    endpoint = FAL_ENDPOINTS[req.model]

    import fal_client

    ref_urls = _upload_refs(req.reference_images)
    payload = _build_payload(req, ref_urls)

    log.info("fal.ai %s ← %s", endpoint, full_prompt[:120])
    try:
        handle = fal_client.submit(endpoint, arguments=payload)
        result = handle.get()
        img_url = _extract_image_url(result)
    except Exception as exc:
        # Nano Banana / edit endpoints are flaky and the schema drifts. If the
        # call fails for any reason, fall back to a pure text-to-image model so
        # the post still renders. We drop the mascot reference because the
        # fallback can't condition on an image — the brand style suffix in the
        # prompt keeps it on-brand.
        fallback = s.runtime["imagegen"].get("fallback_model", "flux_dev")
        if req.model == fallback:
            raise
        log.warning(
            "fal.ai %s failed (%s); falling back to %s without reference image",
            endpoint, type(exc).__name__, fallback,
        )
        fb_req = RenderRequest(
            prompt=req.prompt,
            aspect=req.aspect,
            model=fallback,
            reference_images=[],
            seed=req.seed,
            extra=req.extra,
        )
        return render(fb_req, post_slug=post_slug)

    out_path = cache_mod.cache_dir() / f"{sha}.png"
    _download(img_url, out_path)

    cost = COST_USD.get(req.model, 0.04)
    cache_mod.store(
        sha=sha,
        path=out_path,
        model=req.model,
        prompt=full_prompt,
        seed=req.seed,
        cost_usd=cost,
    )
    _log_spend(req.model, cost, post_slug)

    return RenderResult(
        path=out_path,
        model=req.model,
        prompt=full_prompt,
        seed=req.seed,
        cost_usd=cost,
        cached=False,
    )
