"""Opening trap walkthrough.

The PGN line is NEVER invented by the LLM — it is drawn from a hand-verified
catalog at ``config/knowledge/opening_traps.yaml``. The LLM only writes the
marketing copy (hook, per-step narration, lesson, CTA) around a real trap.
"""
from __future__ import annotations

import random
from pathlib import Path

import chess
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

NAME = "opening_trap"


# ---------- catalog --------------------------------------------------------


def _load_catalog() -> list[dict]:
    s = get_settings()
    path = s.root / "config" / "knowledge" / "opening_traps.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pick_trap(slot: CalendarSlot) -> dict:
    """Pick a catalog trap that we haven't used recently."""
    catalog = _load_catalog()
    if not catalog:
        raise RuntimeError("opening_traps.yaml is empty")
    try:
        used = {r.value for r in memory.recent(kind="opening_trap_id", days=60)}
    except Exception:
        used = set()
    fresh = [t for t in catalog if t["id"] not in used]
    pool = fresh or catalog
    rng = random.Random(f"{slot.date}:{slot.slot}")
    return rng.choice(pool)


# ---------- LLM schema (copy only, no moves) -------------------------------


class _StepNarration(BaseModel):
    title: str = Field(
        ...,
        description=(
            "≤6 words, CONCRETE, names the idea (e.g. 'Bishop hits f7', "
            "'The queen sacrifice', 'Mate on d5'). NEVER 'Move N'."
        ),
    )
    body: str = Field(..., description="≤35 words; the idea behind this move in plain language")


class _Plan(BaseModel):
    hook: str = Field(..., description="≤8 words; teases the trap, no spoiler of the killing move")
    summary: str = Field(..., description="1 sentence summarizing the post")
    cover_image_prompt: str = Field(..., description="vivid scene; chess motif; no text in image")
    step_narrations: list[_StepNarration] = Field(
        ...,
        description=(
            "One entry PER PROVIDED MOVE, in order. Must match the count of provided "
            "moves exactly. Describe what each move accomplishes."
        ),
    )
    lesson: str = Field(..., description="40-70 words; the generalized takeaway")
    cta_headline: str = Field(..., description="≤6 words; CTA-card headline")
    cta_subline: str = Field(..., description="≤14 words; CTA-card subline")


SYSTEM = voice_block() + (
    "\n\nYou are writing the marketing narration for a REAL opening trap. "
    "The exact move list, the trap-springing move, the losing reply, and the "
    "refutation are provided to you as ground truth — do NOT contradict them, "
    "do NOT invent extra moves, do NOT change which move is the trap. Your job "
    "is only the hook, per-move narration, lesson, and CTA copy."
)


def plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    trap = _pick_trap(slot)

    moves_san: list[str] = list(trap["pgn"])

    # Build the LLM brief from verified facts.
    move_lines = []
    for i, san in enumerate(moves_san, 1):
        side = "White" if i % 2 == 1 else "Black"
        marker = ""
        if i == trap.get("trap_ply"):
            marker = "  <-- TRAP MOVE"
        if i == trap.get("killing_ply"):
            marker = "  <-- KILLING BLOW"
        move_lines.append(f"{i:>2}. {side} plays {san}{marker}")

    user = build_user_prompt(
        task=(
            f"Write narration for the **{trap['name']}** trap "
            f"(opening: {trap['opening']}, ECO {trap.get('eco', '?')}). "
            "Provide exactly one step_narration for each move below, in order."
        ),
        context_lines=[
            "GROUND-TRUTH MOVES (do not change, do not add, do not remove):",
            *move_lines,
            "",
            f"LOSING MOVE: {trap['losing_move']}",
            f"REFUTATION: {trap['refutation']}",
            f"LESSON SEED: {trap['lesson']}",
            "",
            "Step narration rules:",
            "- For setup moves: 1 short sentence on the idea (development, prep, etc.).",
            "- For the trap move: highlight the tactical idea WITHOUT spoiling the conclusion.",
            "- For the losing reply: name it as the mistake and gesture at the refutation.",
            "- For the killing blow: spell out why it wins (mate / piece / overload).",
            "- Hook should tease without giving away which move is the trap.",
        ],
    )
    plan_obj = plan_with_retry(
        system=SYSTEM,
        user=user,
        schema=_Plan,
        novelty_check=("hook", "hook"),
    )

    # Coerce LLM narration count to match move count.
    narrations = list(plan_obj.step_narrations)
    if len(narrations) < len(moves_san):
        for i in range(len(narrations), len(moves_san)):
            san = moves_san[i]
            narrations.append(_StepNarration(title=san, body=f"{san} continues the line."))
    narrations = narrations[: len(moves_san)]

    # Render the boards (verified to parse).
    board = chess.Board()
    board_paths: list[Path] = []
    for san in moves_san:
        move = board.parse_san(san)
        board.push(move)
        board_paths.append(render_board(fen=board.fen(), last_move=move.uci(), size=1024))

    trap_ply = trap.get("trap_ply")
    killing_ply = trap.get("killing_ply", trap_ply)

    slides: list[SlideSpec] = [
        SlideSpec(
            layout="cover_listicle",
            text={"hook": plan_obj.hook, "badge": trap["name"].upper()},
            image_prompt=plan_obj.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        )
    ]
    for i, (san, n) in enumerate(zip(moves_san, narrations), 1):
        if i == killing_ply:
            prefix = "TRAP \u2014 "
        elif i == trap_ply and trap_ply != killing_ply:
            prefix = "SETUP \u2014 "
        else:
            prefix = f"{i}. "
        slides.append(
            SlideSpec(
                layout="board_explainer",
                text={"title": f"{prefix}{san} \u2014 {n.title}", "body": n.body},
                extra={"board_path": str(board_paths[i - 1])},
            )
        )
    slides.append(
        SlideSpec(
            layout="board_explainer",
            text={"title": "The lesson", "body": plan_obj.lesson},
            extra={"board_path": str(board_paths[-1])},
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
        badge=trap["name"],
        slides=slides,
        caption_seed=plan_obj.summary,
    )
    # Record the trap id so we don't repeat it for a while.
    try:
        memory.log_many(
            [("opening_trap_id", trap["id"])],
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
