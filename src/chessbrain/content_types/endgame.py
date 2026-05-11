"""Endgame concept walkthrough.

The teaching positions are NEVER invented by the LLM — they come from a
hand-verified catalog at ``config/knowledge/endgame_concepts.yaml``.
The LLM only writes the hook, cover-image prompt, and CTA copy. The
per-position titles/bodies and the takeaway are also from the catalog,
so the chess content is always correct.
"""
from __future__ import annotations

import random
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from chessbrain.brain import memory
from chessbrain.brain.calendar import CalendarSlot
from chessbrain.chessboard import render_board
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext
from chessbrain.settings import get_settings

NAME = "endgame"


def _load_catalog() -> list[dict]:
    s = get_settings()
    path = s.root / "config" / "knowledge" / "endgame_concepts.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pick_concept(slot: CalendarSlot) -> dict:
    catalog = _load_catalog()
    if not catalog:
        raise RuntimeError("endgame_concepts.yaml is empty")

    # If the calendar slot named a series param, try to honor it.
    want = (slot.series_param or "").strip().lower() if isinstance(slot.series_param, str) else ""
    if want:
        for c in catalog:
            if c.get("param", "").lower() == want or c["id"] == want:
                return c

    try:
        used = {r.value for r in memory.recent(kind="endgame_concept_id", days=60)}
    except Exception:
        used = set()
    fresh = [c for c in catalog if c["id"] not in used]
    pool = fresh or catalog
    rng = random.Random(f"{slot.date}:{slot.slot}")
    return rng.choice(pool)


class _Plan(BaseModel):
    hook: str = Field(..., description="≤9 words; teases the lesson, no spoiler")
    summary: str = Field(..., description="1 sentence summary of the post")
    cover_image_prompt: str = Field(..., description="vivid chess scene; NO TEXT in image")
    cta_headline: str = Field(..., description="≤6 words")
    cta_subline: str = Field(..., description="≤14 words")


SYSTEM = voice_block() + (
    "\n\nYou are writing marketing copy around a REAL endgame teaching "
    "concept. The board positions, the per-position narration, and the "
    "takeaway are provided to you as ground truth — do NOT contradict "
    "them. Your job is only the hook, cover-image prompt, and CTA lines."
)


def plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    concept = _pick_concept(slot)

    user = build_user_prompt(
        task=(
            f"Write a hook + cover + CTA for an endgame post about: "
            f"**{concept['name']}**."
        ),
        context_lines=[
            f"CONCEPT: {concept['name']}",
            f"TAKEAWAY: {concept['takeaway']}",
            "The carousel will show 3-4 chess board diagrams with their own captions, "
            "which are already written. You only write hook + cover-image prompt + CTA.",
            "Hook should tease the concept without spoiling the takeaway.",
            "Cover image: chess-themed, atmospheric, NO text in image.",
        ],
    )
    plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "hook"))

    # Render the verified board positions.
    rendered: list[Path] = []
    positions = concept["positions"]
    for pos in positions:
        rendered.append(render_board(fen=pos["fen"], size=1024))

    slides: list[SlideSpec] = [
        SlideSpec(
            layout="cover_listicle",
            text={"hook": plan_obj.hook, "badge": concept["name"].upper()},
            image_prompt=plan_obj.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        )
    ]
    for i, pos in enumerate(positions):
        slides.append(
            SlideSpec(
                layout="board_explainer",
                text={"title": f"{i+1}. {pos['title']}", "body": pos["body"]},
                extra={"board_path": str(rendered[i])},
            )
        )
    slides.append(
        SlideSpec(
            layout="board_explainer",
            text={"title": "Takeaway", "body": concept["takeaway"]},
            extra={"board_path": str(rendered[-1])},
        )
    )
    slides.append(
        SlideSpec(
            layout="cta_card",
            text={
                "headline": plan_obj.cta_headline,
                "subline": plan_obj.cta_subline,
                "url": s.brand["cta_short"],
            },
        )
    )

    post = PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=plan_obj.hook,
        summary=plan_obj.summary,
        badge=concept["name"],
        slides=slides,
        caption_seed=plan_obj.summary,
    )
    try:
        memory.log_many(
            [("endgame_concept_id", concept["id"])],
            post_slug=post.slug,
            content_type=NAME,
        )
    except Exception:
        pass
    return post


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total)
    if slide.layout == "cover_listicle":
        return layouts.cover_listicle(
            bg_image=ai_image, hook=slide.text["hook"], badge=slide.text.get("badge"), ctx=ctx
        )
    if slide.layout == "board_explainer":
        return layouts.board_explainer(
            board_image=Path(slide.extra["board_path"]),
            title=slide.text["title"],
            body=slide.text["body"],
            ctx=ctx,
        )
    if slide.layout == "cta_card":
        return layouts.cta_card(
            bg_image=ai_image,
            headline=slide.text["headline"],
            subline=slide.text["subline"],
            url=slide.text["url"],
            ctx=ctx,
        )
    raise ValueError(slide.layout)
