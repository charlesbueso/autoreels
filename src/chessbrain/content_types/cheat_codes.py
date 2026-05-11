"""'X Chess Cheat Codes' listicle — the golf-post style listicle."""
from __future__ import annotations

import random
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.imagegen.base import RenderRequest
from chessbrain.imagegen.client import render as render_image
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext
from chessbrain.settings import get_settings

NAME = "cheat_codes"


# Cache for the curated knowledge file.
_KNOWLEDGE: list[dict] | None = None


def _load_knowledge() -> list[dict]:
    """Flatten config/knowledge/cheat_codes.yaml into a list of {title, body, group}."""
    global _KNOWLEDGE
    if _KNOWLEDGE is not None:
        return _KNOWLEDGE
    s = get_settings()
    path = s.root / "config" / "knowledge" / "cheat_codes.yaml"
    items: list[dict] = []
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for group, entries in data.items():
            for e in entries or []:
                items.append({"group": group, "title": e["title"], "body": e["body"]})
    _KNOWLEDGE = items
    return items


def _knowledge_block(topic_seed: str, k: int = 8) -> str:
    """Pick K depth examples — biased toward the topic if it matches a group."""
    pool = _load_knowledge()
    if not pool:
        return ""
    topic_lc = (topic_seed or "").lower()
    relevant = [it for it in pool if it["group"] in topic_lc or topic_lc in it["group"]]
    other = [it for it in pool if it not in relevant]
    random.shuffle(relevant)
    random.shuffle(other)
    chosen = (relevant + other)[:k]
    lines = [
        "DEPTH BAR — match the specificity of these examples (do NOT copy them):",
    ]
    for it in chosen:
        lines.append(f'- "{it["title"]}" — {it["body"]}')
    return "\n".join(lines)


class _Item(BaseModel):
    title: str = Field(..., description="≤7 words, sharp, concrete; names a piece, square, or named idea")
    body: str = Field(
        ...,
        description=(
            "≤32 words, ONE concrete instruction. Must reference a SPECIFIC chess element: "
            "a piece, a square, a structure (IQP, hanging pawns, fianchetto, doubled pawns, "
            "minority attack), a named plan, or a named master/game. No platitudes."
        ),
    )
    image_prompt: str = Field(..., description="vivid one-sentence illustration prompt, no text in image")


class _Plan(BaseModel):
    hook: str = Field(..., description="cover hook ≤8 words, ends in colon, e.g. '7 Chess Cheat Codes:'")
    summary: str
    badge: str = Field(..., description="short uppercase tag like 'CHEAT CODES'")
    cover_image_prompt: str
    items: list[_Item]
    cta_headline: str
    cta_subline: str


SYSTEM = (
    voice_block()
    + "\n\nYou are a strong chess coach (FM/IM level) writing a listicle for "
    "1500–1900 Lichess players. Your tips MUST sound like advice from a coach, "
    "NOT generic motivation.\n"
    "\nABSOLUTE RULES:\n"
    "- Every item must reference a CONCRETE chess element: a specific square "
    "(d5, h3, the 7th rank), a piece role (bad bishop, outpost knight, "
    "blockader), a pawn structure (IQP, hanging pawns, doubled f-pawns, "
    "Carlsbad), or a named plan/maneuver/master.\n"
    "- BANNED platitudes: 'develop your pieces', 'control the center', "
    "'protect good bishops', 'play actively', 'think before you move', "
    "'safeguard your X', 'maintain X', 'gain control', 'improve your X'.\n"
    "- BANNED structure: never write 'Title: Body' where Body just rephrases "
    "Title. Body must add a SECOND idea (mechanism, exception, named example).\n"
    "- If you cannot make a tip pass the depth bar examples, REPLACE the topic "
    "rather than weaken the tip.\n"
    "- Prefer counter-intuitive insights over obvious ones (Karpov's bad-bishop "
    "trade, Tartakower's doubled pawns, the IQP-wants-pieces rule).\n"
)


def _plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    cfg = s.content_types[NAME]
    n = random.randint(cfg["items"]["count_min"], cfg["items"]["count_max"])
    topic_seed = slot.series_param if slot.series_param else "general chess improvement"

    user = build_user_prompt(
        task=(
            f"Design a {n}-item chess listicle carousel themed around: "
            f"\"{topic_seed}\". Each item must be a different, concrete habit, "
            f"trick, or principle a 1500–1900 Lichess player can apply tomorrow."
        ),
        context_lines=[
            "Target audience: club-level Lichess players (1500–1900).",
            f"Items: exactly {n}.",
            "Each item: title ≤7 words; body ≤32 words; ONE concrete instruction.",
            "Image prompts: vivid illustration, no text in the image.",
            "Body must add NEW info beyond the title (a mechanism, an exception, a named example).",
        ],
        extra_instructions=_knowledge_block(str(topic_seed)),
    )

    plan = plan_with_retry(
        system=SYSTEM,
        user=user,
        schema=_Plan,
        novelty_check=("hook", "hook"),
    )

    # Trim to requested count if model gave more/fewer.
    items = plan.items[:n]
    while len(items) < cfg["items"]["count_min"]:
        items.append(items[-1])  # pad rather than fail; rare path

    slides: list[SlideSpec] = []
    slides.append(
        SlideSpec(
            layout="cover_listicle",
            text={"hook": plan.hook, "badge": plan.badge},
            image_prompt=plan.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        )
    )
    for i, it in enumerate(items, start=1):
        slides.append(
            SlideSpec(
                layout="numbered_item",
                text={"number": i, "title": it.title, "body": it.body},
                image_prompt=it.image_prompt,
                image_model="nano_banana",
                aspect="4:5",
            )
        )
    slides.append(
        SlideSpec(
            layout="cta_card",
            text={
                "headline": plan.cta_headline,
                "subline": plan.cta_subline,
                "url": s.brand["cta_short"],
            },
            image_prompt=None,
            aspect="4:5",
        )
    )

    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=plan.hook,
        summary=plan.summary,
        badge=plan.badge,
        slides=slides,
        caption_seed=plan.summary,
        series=slot.series,
        series_param=slot.series_param,
    )


def _render_slide(
    plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None
) -> Path:
    ctx = SlideContext(slide_index=index, total_slides=total)
    if slide.layout == "cover_listicle":
        return layouts.cover_listicle(
            bg_image=ai_image,
            hook=slide.text["hook"],
            badge=slide.text.get("badge"),
            ctx=ctx,
        )
    if slide.layout == "numbered_item":
        return layouts.numbered_item(
            bg_image=ai_image,
            number=int(slide.text["number"]),
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
    raise ValueError(f"Unknown layout: {slide.layout}")


# --- public API expected by the pipeline ---
def plan(slot: CalendarSlot) -> PostPlan:
    return _plan(slot)


def render_slide(plan_obj: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    return _render_slide(plan_obj, slide, index, total, ai_image=ai_image)
