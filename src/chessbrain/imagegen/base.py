"""Shared types + style assembly for image generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chessbrain.settings import get_settings


@dataclass
class RenderRequest:
    """A single image-generation job."""

    prompt: str
    aspect: str = "4:5"                  # "4:5" | "9:16" | "1:1" | "16:9"
    model: str = "nano_banana"           # imagegen.{model}
    reference_images: list[Path] = field(default_factory=list)
    seed: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class RenderResult:
    path: Path
    model: str
    prompt: str
    seed: int | None
    cost_usd: float
    cached: bool


# Approximate per-image USD cost (used for spend_log; refresh annually).
COST_USD = {
    "nano_banana": 0.039,
    "flux_dev": 0.025,
    "flux_pro": 0.06,
    "ideogram_v3": 0.06,
}


def assemble_prompt(prompt: str, *, include_style: bool = True, include_mascot_lock: bool = False) -> str:
    s = get_settings().visual_style
    parts = [prompt.strip()]
    if include_mascot_lock:
        parts.append(s.get("mascot_style_lock", "").strip())
    if include_style:
        parts.append(s.get("style_suffix", "").strip())
    return ". ".join(p for p in parts if p)


def negative_prompt() -> str:
    return get_settings().visual_style.get("negative_prompt", "").strip()
