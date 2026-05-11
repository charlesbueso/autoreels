"""Discord product-demo carousel — procedurally rendered Discord mocks."""
from __future__ import annotations

import random
from pathlib import Path

from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.render import layouts, product_mock
from chessbrain.render.layouts import SlideContext
from chessbrain.settings import get_settings

NAME = "product_demo"


# Pre-validated FENs + suggestion arrows for board renders. The planner picks
# from these instead of trusting the LLM with FEN syntax.
BOARD_SAMPLES: list[dict] = [
    {
        # Italian Game, after 3...Bc5 — classic teaching position.
        "fen": "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "last": "f8c5",
        "arrow": ("d2", "d4", "green"),
    },
    {
        # Sicilian Najdorf, after 5...a6.
        "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
        "last": "a7a6",
        "arrow": ("c1", "g5", "blue"),
    },
    {
        # Queen's Gambit Declined, classical.
        "fen": "rnbq1rk1/ppp1bppp/4pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQ - 1 6",
        "last": "f8e7",
        "arrow": ("c4", "d5", "yellow"),
    },
    {
        # London System middle-game.
        "fen": "rnbq1rk1/ppp1ppbp/3p1np1/8/2PP1B2/2N2N2/PP2PPPP/R2QKB1R w KQ - 2 6",
        "last": "f8g7",
        "arrow": ("e2", "e3", "green"),
    },
    {
        # King's Indian Defense, classical.
        "fen": "rnbq1rk1/ppp1ppbp/3p1np1/8/2PPP3/2N2N2/PP2BPPP/R1BQK2R b KQ - 3 6",
        "last": "f1e2",
        "arrow": ("e7", "e5", "red"),
    },
    {
        # Caro-Kann, classical main line.
        "fen": "rn1qkbnr/pp2pppp/2p5/3p1b2/3P4/2N5/PPP1PPPP/R1BQKBNR w KQkq - 2 4",
        "last": "c8f5",
        "arrow": ("g1", "f3", "blue"),
    },
]


class _Mock(BaseModel):
    title: str = Field(..., description="slide-level title above the Discord panel; ≤8 words")
    bot_message: str = Field(..., description="what the ChessBrain bot 'says' in the channel")
    embed_title: str = Field(..., description="title of the embed card (a chess concept)")
    embed_description: str = Field(..., description="40-90 words; the bot's analysis text")
    feature_pitch: str = Field(..., description="one-liner naming the feature being shown")
    feature_key: str = Field(
        ...,
        description=(
            "lowercase id of the feature: one of "
            "'auto_import', 'engine_analysis', 'ask', 'board', 'billing', 'setup'"
        ),
    )


class _Plan(BaseModel):
    hook: str = Field(
        ...,
        description=(
            "≤8 words. Cover hook pitching the PRODUCT itself (ChessBrain Discord bot) — "
            "NOT a specific chess concept like an opening, square, or move. "
            "The slides demo bot features (auto-import, /ask, /board), so the hook "
            "must promise the product, not a chess tip. "
            "Examples (style only): 'Stockfish lives in your Discord', "
            "'Your chess coach is a Discord bot', "
            "'Auto-analyze every Lichess game', 'Skip the post-game guesswork'."
        ),
    )
    summary: str
    badge: str = Field(default="HOW IT WORKS")
    cover_image_prompt: str
    mocks: list[_Mock]
    cta_headline: str
    cta_subline: str = Field(
        ...,
        description=(
            "1 sentence, ≤14 words. Reinforce the BENEFIT (e.g. 'Engine-verified "
            "analysis of every Lichess game, posted in your Discord.'). Do NOT "
            "mention the free trial here — that is rendered as a separate pill."
        ),
    )


SYSTEM = (
    voice_block()
    + "\n\nYou are demoing how ChessBrain (a Discord bot) shows up inside a user's "
    "server. Each mock is a single Discord message from the bot, with an embed. "
    "The COVER hook must sell the product, not a chess concept — readers should "
    "understand from slide 1 that this is a tool, not a tip. Concrete chess "
    "details (openings, squares, moves) belong inside the embeds, not the hook."
)


def _board_for(feature_key: str) -> dict | None:
    """Pick a board sample for features that visually benefit from one."""
    if feature_key in {"auto_import", "engine_analysis", "board", "ask"}:
        return random.choice(BOARD_SAMPLES)
    return None


def plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    cfg = s.content_types[NAME]
    n = random.randint(cfg["mocks"]["count_min"], cfg["mocks"]["count_max"])
    user = build_user_prompt(
        task=(
            f"Design a {n}-mock Discord product-demo carousel for ChessBrain. "
            "Each mock highlights ONE feature: auto-import, engine-verified analysis, "
            "/ask conversational follow-ups, /board position render, /billing, /setup. "
            "Set feature_key to the matching id."
        ),
        context_lines=[
            "Make embed_description sound like a real coach, not marketing.",
            "Each mock must show a different feature.",
            "The cover hook pitches the BOT, not a specific chess move/square.",
        ],
    )
    plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "hook"))

    slides: list[SlideSpec] = [
        SlideSpec(
            layout="cover_listicle",
            text={"hook": plan_obj.hook, "badge": plan_obj.badge},
            image_prompt=plan_obj.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        )
    ]
    for m in plan_obj.mocks[:n]:
        embed: dict = {
            "title": m.embed_title,
            "description": m.embed_description,
        }
        board = _board_for(m.feature_key.lower().strip())
        if board:
            embed["board_fen"] = board["fen"]
            embed["board_last"] = board.get("last")
            embed["board_arrow"] = board.get("arrow")
        slides.append(
            SlideSpec(
                layout="discord_mock",
                text={"title": m.title, "feature": m.feature_pitch},
                extra={
                    "messages": [
                        {
                            "author": "ChessBrain",
                            "role_color": "#C49A3C",
                            "time": "Today at 14:22",
                            "text": m.bot_message,
                            "embed": embed,
                        }
                    ]
                },
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
            # Reuse the cover image as the CTA background — same prompt + seed
            # hits the image cache so this costs $0 and the asset is used twice.
            image_prompt=plan_obj.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        )
    )

    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{random.randint(1000, 9999)}",
        content_type=NAME,
        hook=plan_obj.hook,
        summary=plan_obj.summary,
        badge=plan_obj.badge,
        slides=slides,
        caption_seed=plan_obj.summary,
    )


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total)
    if slide.layout == "cover_listicle":
        return layouts.cover_listicle(
            bg_image=ai_image, hook=slide.text["hook"], badge=slide.text.get("badge"), ctx=ctx
        )
    if slide.layout == "discord_mock":
        return product_mock.render_discord_mock(
            title=slide.text["title"],
            messages=slide.extra["messages"],
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
