"""GM quote card."""
from __future__ import annotations

import random
from pathlib import Path

from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext

NAME = "quote"


class _Plan(BaseModel):
    quote: str
    author: str
    summary: str
    image_prompt: str = Field(
        ..., description="atmospheric backdrop matching the quote's mood; NO TEXT in image"
    )


SYSTEM = voice_block() + "\n\nDeliver a single GM quote card."


def plan(slot: CalendarSlot) -> PostPlan:
    seeded_quote = None
    seeded_author = None
    if isinstance(slot.series_param, dict):
        seeded_quote = slot.series_param.get("quote")
        seeded_author = slot.series_param.get("author")

    if seeded_quote and seeded_author:
        # Skip LLM for quote text; just plan the backdrop.
        class _BgPlan(BaseModel):
            image_prompt: str
            summary: str
        bg = plan_with_retry(
            system=SYSTEM,
            user=build_user_prompt(
                task=(
                    f"Design a backdrop image for the chess quote: \"{seeded_quote}\" — "
                    f"{seeded_author}. The image must be evocative, atmospheric, NO TEXT."
                ),
            ),
            schema=_BgPlan,
        )
        plan_obj = _Plan(
            quote=seeded_quote, author=seeded_author, summary=bg.summary, image_prompt=bg.image_prompt
        )
    else:
        user = build_user_prompt(
            task="Pick a real famous chess quote (verifiable). Choose a backdrop that matches its mood."
        )
        plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "quote"))

    slide = SlideSpec(
        layout="quote_card",
        text={"quote": plan_obj.quote, "author": plan_obj.author},
        image_prompt=plan_obj.image_prompt,
        image_model="flux_pro",
        aspect="4:5",
    )
    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=plan_obj.quote[:80],
        summary=plan_obj.summary,
        slides=[slide],
        caption_seed=plan_obj.summary,
    )


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total, show_pagination=False)
    return layouts.quote_card(
        bg_image=ai_image, quote=slide.text["quote"], author=slide.text["author"], ctx=ctx
    )
