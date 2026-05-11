"""Base types and protocol for content types."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot


class SlideSpec(BaseModel):
    """A single slide's render instructions."""

    layout: str
    text: dict[str, Any] = Field(default_factory=dict)        # title, body, hook, etc.
    image_prompt: str | None = None                            # for AI image gen
    image_model: str | None = None                             # override per-slide
    use_mascot_ref: bool = False
    aspect: str = "4:5"
    seed: int | None = None
    preset_image_path: str | None = None                       # use this file directly, skip AI gen
    extra: dict[str, Any] = Field(default_factory=dict)        # board fen, mock messages, etc.


class PostPlan(BaseModel):
    slug: str
    content_type: str
    hook: str
    summary: str
    badge: str | None = None
    slides: list[SlideSpec]
    caption_seed: str = ""
    series: str | None = None
    series_param: Any = None


class ContentType(Protocol):
    name: str

    def plan(self, slot: CalendarSlot) -> PostPlan: ...

    def render_slide(self, plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None) -> Path: ...
