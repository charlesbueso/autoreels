"""Single-image meme post.

Two paths:
- Reddit repost: pull a top meme image, frame it on brand canvas with credit.
- AI fallback: when no Reddit meme is available, generate via the model.
"""
from __future__ import annotations

import random
from pathlib import Path

from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.brain.reddit_inspo import (
    RedditMeme,
    fetch_inspiration_titles,
    fetch_top_meme,
)
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext

NAME = "meme"


class _Plan(BaseModel):
    hook: str = Field(..., description="≤12 words; relatable chess moment, dry humor")
    summary: str
    image_prompt: str = Field(
        ..., description="vivid scene with the mascot reacting to the hook; NO TEXT in image"
    )


SYSTEM = (
    voice_block()
    + "\n\nWrite a meme single-image post: a relatable Lichess-player moment. "
    "Keep it dry, never cringe. Avoid emoji, avoid 'POV:'. "
    "Universal moments only — no player names, no tournaments, no engine drama. "
    "Our mascot is a friendly cartoon pink brain with big black eyes, a wide smile, "
    "and a black chess king on top of its head as a crown. When describing the "
    "image, always refer to it as 'our pink-brain mascot' — never as a chess piece "
    "or golf ball."
)


def _inspiration_block() -> list[str]:
    titles = fetch_inspiration_titles(n=10, period="week")
    if not titles:
        return []
    lines = [
        "INSPIRATION (trending chess-meme themes from Reddit this week — use",
        "as IDEA SEEDS only; never copy a title verbatim, never reference a",
        "specific image, and pick the simplest / most universal angle):",
    ]
    lines.extend(f"- {t}" for t in titles)
    lines.append(
        "Distill the *underlying relatable moment*, then write your own "
        "hook in our voice."
    )
    return lines


def _plan_repost(slot: CalendarSlot, meme: RedditMeme) -> PostPlan:
    """Use the Reddit meme as-is; LLM only writes a short caption seed."""
    summary = (
        f"{meme.title} {meme.attribution}. "
        "We're reposting this because it nailed something every chess player feels."
    )
    slide = SlideSpec(
        layout="meme_repost",
        text={"hook": meme.title, "attribution": meme.attribution},
        preset_image_path=str(meme.image_path),
        aspect="4:5",
    )
    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=meme.title,
        summary=summary,
        slides=[slide],
        caption_seed=summary,
    )


def _plan_ai(slot: CalendarSlot) -> PostPlan:
    user = build_user_prompt(
        task="Write a chess-meme single image: a moment every Lichess player has had.",
        context_lines=[
            "Examples of moments: pre-moving the wrong piece, time scramble at +5, ",
            "blundering after a 30-second think, opponent disconnecting, tilt queue.",
            *_inspiration_block(),
        ],
    )
    plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "hook"))
    slide = SlideSpec(
        layout="meme_single",
        text={"hook": plan_obj.hook},
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
    )


def plan(slot: CalendarSlot) -> PostPlan:
    meme = fetch_top_meme(period="week")
    if meme is not None:
        return _plan_repost(slot, meme)
    return _plan_ai(slot)


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total, show_pagination=False)
    if slide.layout == "meme_repost" and ai_image is not None:
        return layouts.meme_repost(
            meme_image=ai_image,
            attribution=slide.text.get("attribution", ""),
            ctx=ctx,
        )
    return layouts.meme_single(bg_image=ai_image, hook=slide.text["hook"], ctx=ctx)
