"""Mascot-in-environment single image (Mascot Monday)."""
from __future__ import annotations

import random
from pathlib import Path

from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext
from chessbrain.settings import get_settings

NAME = "mascot_scene"


class _Plan(BaseModel):
    hook: str = Field(..., description="≤9 words, witty, fits the scene; no exclamation")
    summary: str
    image_prompt: str = Field(
        ...,
        description=(
            "vivid description of OUR mascot (a friendly cartoon pink brain with big "
            "black eyes, wide smile, rosy cheeks, and a black chess king balanced on "
            "top of its head) placed in the given environment. focus on the mascot's "
            "pose, expression, action, and any costume/props it is wearing or holding; "
            "describe the environment richly. NEVER describe the mascot as a chess "
            "piece, golf ball, egg, or any other character — it is always a pink brain "
            "with a chess-king crown. NO TEXT in image."
        ),
    )
    cta_line: str = Field(..., description="single-line CTA referencing chessbrain.coach")


SYSTEM = (
    voice_block()
    + "\n\nYou are writing a single mascot image post that places OUR mascot in a "
    "new environment each week. Our mascot is a friendly cartoon pink brain character "
    "(glossy bubblegum-pink brain body with visible cerebral folds, big round black "
    "eyes with white highlights, wide cheerful smile, rosy pink cheek blush, short "
    "pink arms and legs) with a black chess king piece balanced on top of its head "
    "as a crown. The mascot may wear different hats, scarves, costumes, and hold "
    "different items from week to week, but its body, face, and the chess-king crown "
    "stay identical to the reference. NEVER describe it as a chess piece, golf ball, "
    "or egg. The image must NOT contain any text — text overlays are added separately."
)


def plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    env = slot.series_param or "rainy city street with neon reflections"

    user = build_user_prompt(
        task=(
            "Design a single-image post: our mascot in this environment: "
            f"\"{env}\". The hook should be a witty one-liner that lands "
            "with the scene (no chess jargon needed)."
        ),
        context_lines=[
            "Image prompt should be vivid + specific. Mention pose, lighting, props.",
            "No text in the image.",
        ],
    )
    plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "hook"))

    slide = SlideSpec(
        layout="meme_single",
        text={"hook": plan_obj.hook, "cta": plan_obj.cta_line},
        image_prompt=plan_obj.image_prompt,
        image_model="nano_banana",
        use_mascot_ref=True,
        aspect="4:5",
    )
    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=plan_obj.hook,
        summary=plan_obj.summary,
        slides=[slide],
        caption_seed=plan_obj.summary,
        series=slot.series,
        series_param=slot.series_param,
    )


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total, show_pagination=False)
    return layouts.meme_single(bg_image=ai_image, hook=slide.text["hook"], ctx=ctx)
