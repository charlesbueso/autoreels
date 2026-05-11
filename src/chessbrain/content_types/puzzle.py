"""Tactical puzzle from Lichess DB."""
from __future__ import annotations

import random
import re
from pathlib import Path

import chess
from pydantic import BaseModel, Field

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.chessboard import render_board
from chessbrain.content_types.base import PostPlan, SlideSpec
from chessbrain.content_types.planner import build_user_prompt, plan_with_retry, voice_block
from chessbrain.puzzle import pick as pick_puzzle
from chessbrain.render import layouts
from chessbrain.render.layouts import SlideContext
from chessbrain.settings import get_settings

NAME = "puzzle"


class _Plan(BaseModel):
    hook: str = Field(..., description="≤8 words, ends in '?' or '.'")
    summary: str
    cover_image_prompt: str = Field(..., description="illustration that hints at the tactic, no text")
    explanation: str = Field(..., description="40-70 words explaining why the move wins")
    cta_headline: str
    cta_subline: str


SYSTEM = voice_block() + "\n\nYou are presenting a tactical puzzle to a club-level Lichess player."


def _square_from_uci(uci: str) -> tuple[str, str]:
    return uci[:2], uci[2:4]


def _detect_mate_in(themes: str) -> int | None:
    """Lichess puzzle themes use 'mateIn1', 'mateIn2', etc."""
    m = re.search(r"mateIn(\d+)", themes or "")
    return int(m.group(1)) if m else None


def _move_san(board: chess.Board, uci: str) -> str:
    """Best-effort SAN for a UCI string on a given board."""
    try:
        return board.san(chess.Move.from_uci(uci))
    except Exception:
        return uci


def plan(slot: CalendarSlot) -> PostPlan:
    s = get_settings()
    cfg = s.content_types[NAME]
    rmin, rmax = cfg["target_rating_range"]
    theme = slot.series_param if isinstance(slot.series_param, str) else None
    puz = pick_puzzle(rating_min=rmin, rating_max=rmax, theme=theme)
    if puz is None:
        puz = pick_puzzle(rating_min=1200, rating_max=1900)
    if puz is None:
        raise RuntimeError("No puzzles available — run `chessbrain puzzles ingest`.")

    moves: list[str] = puz["moves"].split()
    if not moves:
        raise RuntimeError(f"Puzzle {puz['id']} has no moves.")

    # Lichess protocol: moves[0] is the OPPONENT's move that triggers the puzzle.
    # The player solving the puzzle then plays moves[1], opponent moves[2], player moves[3], etc.
    setup_move = moves[0]
    player_moves = moves[1::2]   # indices 1, 3, 5, ...
    opp_replies = moves[2::2]    # indices 2, 4, 6, ...

    initial = chess.Board(puz["fen"])
    initial.push_uci(setup_move)
    pos_fen = initial.fen()
    side_to_move = "White" if initial.turn == chess.WHITE else "Black"
    flip = initial.turn == chess.BLACK   # show board from solver's POV

    mate_in = _detect_mate_in(puz.get("themes", ""))
    if mate_in:
        side_label = f"{side_to_move} to move. Mate in {mate_in}."
    else:
        side_label = f"{side_to_move} to move."

    user = build_user_prompt(
        task=(
            f"Write a chess puzzle post around this position. "
            f"Side to move: {side_to_move}. "
            f"{'It is a mate in ' + str(mate_in) + '. ' if mate_in else ''}"
            f"Lichess themes: {puz['themes']}. "
            f"Rating: {puz['rating']}. "
            f"The hook teases the moment without revealing the move."
        ),
        context_lines=[
            f"Solution sequence (UCI): {' '.join(player_moves)}",
            "Explanation: name the tactic, name the target piece, give the key follow-up idea.",
            "Do NOT spell out specific squares in the hook.",
        ],
    )
    plan_obj = plan_with_retry(system=SYSTEM, user=user, schema=_Plan, novelty_check=("hook", "hook"))

    # Build the slides.
    slides: list[SlideSpec] = [
        SlideSpec(
            layout="cover_listicle",
            text={"hook": plan_obj.hook, "badge": "PUZZLE"},
            image_prompt=plan_obj.cover_image_prompt,
            image_model="flux_pro",
            aspect="4:5",
        ),
    ]

    # The starting position with the opponent's setup move highlighted.
    pos_board_path = render_board(fen=pos_fen, last_move=setup_move, size=1024, flip=flip)
    slides.append(
        SlideSpec(
            layout="board_only",
            text={"caption": side_label},
            extra={"board_path": str(pos_board_path)},
        )
    )

    # Walk the solution: one slide per PLAYER move with arrow + SAN caption.
    # Total slides budget: cover + position + N solution slides + explainer + cta ≤ 10.
    max_solution_slides = max(1, 10 - 4)   # = 6 player-move slides max
    walking = chess.Board(pos_fen)
    seq_san: list[str] = []
    for i, pmove in enumerate(player_moves[:max_solution_slides]):
        san = _move_san(walking, pmove)
        seq_san.append(san)
        sf, st = _square_from_uci(pmove)
        # Render with arrow on the move BEFORE pushing it.
        # Use last_move=opponent's previous reply if any, otherwise None.
        prev_opp = opp_replies[i - 1] if i > 0 and i - 1 < len(opp_replies) else None
        board_path = render_board(
            fen=walking.fen(),
            last_move=prev_opp,
            arrows=[(sf, st, "green")],
            highlight=[st],
            size=1024,
            flip=flip,
        )
        if mate_in:
            cap = f"Move {i + 1} of {mate_in}: {san}"
        elif len(player_moves) > 1:
            cap = f"Move {i + 1}: {san}"
        else:
            cap = f"The move: {san}"
        slides.append(
            SlideSpec(
                layout="board_only",
                text={"caption": cap},
                extra={"board_path": str(board_path)},
            )
        )
        walking.push_uci(pmove)
        # Apply opponent reply (no slide for this).
        if i < len(opp_replies):
            try:
                walking.push_uci(opp_replies[i])
            except ValueError:
                break

    # Explainer slide on the final position.
    final_path = render_board(fen=walking.fen(), size=1024, flip=flip)
    seq_str = " ".join(seq_san)
    explainer_body = plan_obj.explanation
    if seq_str:
        explainer_body = f"{seq_str}\n\n{plan_obj.explanation}"
    slides.append(
        SlideSpec(
            layout="board_explainer",
            text={"title": "Why it works", "body": explainer_body},
            extra={"board_path": str(final_path)},
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

    return PostPlan(
        slug=f"{slot.date}_{slot.slot}_{NAME}_{puz['id']}",
        content_type=NAME,
        hook=plan_obj.hook,
        summary=plan_obj.summary,
        badge="PUZZLE",
        slides=slides,
        caption_seed=plan_obj.summary,
        series=slot.series,
        series_param=slot.series_param,
    )


def render_slide(post_plan: PostPlan, slide: SlideSpec, index: int, total: int, *, ai_image: Path | None):
    ctx = SlideContext(slide_index=index, total_slides=total)
    if slide.layout == "cover_listicle":
        return layouts.cover_listicle(
            bg_image=ai_image, hook=slide.text["hook"], badge=slide.text.get("badge"), ctx=ctx
        )
    if slide.layout == "board_only":
        return layouts.board_only(
            board_image=Path(slide.extra["board_path"]), caption=slide.text.get("caption"), ctx=ctx
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
