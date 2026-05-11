"""Video generation via Modal serverless GPU (Wan2.1-T2V-14B on H100).

Calls the deployed Modal function remotely — no local GPU needed.
The H100 runs the full 14B model natively with torch.compile.
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_generator = None


def _get_generator():
    """Lazy-load the remote Modal generator class (cached across calls)."""
    global _generator
    if _generator is not None:
        return _generator

    import modal

    WanGenerator = modal.Cls.from_name("autoreels-wan14b", "WanGenerator")
    _generator = WanGenerator()
    logger.info("Connected to Modal serverless Wan2.1-14B")
    return _generator


async def generate_clip(
    prompt: str,
    output_path: Path,
    settings: dict[str, Any],
    *,
    seed: int | None = None,
) -> Path:
    """Generate a single video clip via Modal remote GPU."""
    gen = _get_generator()
    video_cfg = settings.get("video", {})

    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    height = video_cfg.get("native_height", 480)
    width = video_cfg.get("native_width", 832)
    fps = video_cfg.get("fps", 16)
    duration = video_cfg.get("clip_duration_sec", 3)
    num_inference_steps = video_cfg.get("num_inference_steps", 30)
    guidance_scale = video_cfg.get("guidance_scale", 5.0)

    # Wan2.1 expects num_frames as 4k+1
    raw_frames = fps * duration
    num_frames = ((raw_frames - 1) // 4) * 4 + 1

    logger.info(
        "Requesting Modal generation: %dx%d, %d frames @ %d fps, %d steps, seed=%d",
        width, height, num_frames, fps, num_inference_steps, seed,
    )

    start = time.time()
    mp4_bytes = await gen.generate.remote.aio(
        prompt=prompt,
        width=width,
        height=height,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        fps=fps,
        seed=seed,
    )
    elapsed = time.time() - start
    logger.info("Modal returned %.0f KB in %.1fs", len(mp4_bytes) / 1024, elapsed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(mp4_bytes)

    logger.info("Clip saved: %s (%d frames, %dx%d)", output_path, num_frames, width, height)
    return output_path


def unload_model() -> None:
    """No-op for serverless — nothing to unload locally."""
    global _generator
    _generator = None
    logger.info("Modal generator reference cleared")
