"""Render chess board PNGs from FEN with optional arrows + highlighted squares.

Pure-Pillow implementation — no native cairo dependency. Pieces are drawn with
unicode chess glyphs (a Windows-friendly font is auto-detected).
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import chess
from PIL import Image, ImageDraw, ImageFont

from chessbrain.brain.db import connect, utc_now_iso
from chessbrain.settings import get_settings


# Brand-aligned palette for squares + coords + arrows.
COLOR_LIGHT = "#F7F2EA"
COLOR_DARK = "#C49A3C"
COLOR_BORDER = "#1F2A44"
COLOR_COORD = "#FBF8F2"
COLOR_LASTMOVE = (226, 192, 121, 140)   # gold_soft, semi-transparent
COLOR_HIGHLIGHT = (63, 125, 88, 140)    # green
ARROW_COLORS = {
    "green": "#3F7D58",
    "red": "#C0392B",
    "blue": "#1F4E8A",
    "yellow": "#E2C079",
}

# Unicode chess pieces. We use the FILLED (solid silhouette) glyphs for BOTH
# colors and distinguish via fill+outline color, which is more reliable across
# fonts than relying on outlined-vs-filled glyph variants.
_FILLED = {
    "k": "\u265A", "q": "\u265B", "r": "\u265C", "b": "\u265D", "n": "\u265E", "p": "\u265F",
}
PIECE_GLYPHS = {
    "P": _FILLED["p"], "N": _FILLED["n"], "B": _FILLED["b"],
    "R": _FILLED["r"], "Q": _FILLED["q"], "K": _FILLED["k"],
    "p": _FILLED["p"], "n": _FILLED["n"], "b": _FILLED["b"],
    "r": _FILLED["r"], "q": _FILLED["q"], "k": _FILLED["k"],
}

# Piece colors — solid silhouettes with a contrast outline so they pop on both
# light and dark squares.
WHITE_FILL = "#FBF8F2"
WHITE_OUTLINE = "#1A1A1A"
BLACK_FILL = "#1A1A1A"
BLACK_OUTLINE = "#FBF8F2"

# Try fonts that ship a complete Chess Symbols block. First match wins.
_PIECE_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\seguisym.ttf",        # Segoe UI Symbol
    r"C:\Windows\Fonts\arialuni.ttf",        # Arial Unicode MS (older Windows)
    r"C:\Windows\Fonts\DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _piece_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _PIECE_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _coord_font(size: int) -> ImageFont.FreeTypeFont:
    s = get_settings()
    try:
        return ImageFont.truetype(str(s.root / s.brand["fonts"]["display_alt"]), size)
    except OSError:
        return ImageFont.load_default()


def _cache_dir() -> Path:
    d = get_settings().data_dir / "board_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _square_xy(file: int, rank: int, board_origin: tuple[int, int], sq_size: int, flip: bool) -> tuple[int, int]:
    if flip:
        col = 7 - file
        row = rank
    else:
        col = file
        row = 7 - rank
    return board_origin[0] + col * sq_size, board_origin[1] + row * sq_size


def _draw_arrow(
    overlay: Image.Image,
    a_sq: int,
    b_sq: int,
    color: str,
    board_origin: tuple[int, int],
    sq_size: int,
    flip: bool,
) -> None:
    draw = ImageDraw.Draw(overlay)
    fa, ra = chess.square_file(a_sq), chess.square_rank(a_sq)
    fb, rb = chess.square_file(b_sq), chess.square_rank(b_sq)
    ax, ay = _square_xy(fa, ra, board_origin, sq_size, flip)
    bx, by = _square_xy(fb, rb, board_origin, sq_size, flip)
    ax += sq_size // 2
    ay += sq_size // 2
    bx += sq_size // 2
    by += sq_size // 2
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    # Trim 35% from start so the arrow doesn't smother the source square.
    trim = sq_size * 0.35
    ax2 = ax + ux * trim
    ay2 = ay + uy * trim
    head_len = sq_size * 0.42
    head_w = sq_size * 0.28
    bx2 = bx - ux * head_len * 0.6
    by2 = by - uy * head_len * 0.6
    line_w = max(8, sq_size // 9)
    rgb = ARROW_COLORS.get(color, color)
    draw.line([(ax2, ay2), (bx2, by2)], fill=rgb, width=line_w)
    # Arrowhead.
    px, py = -uy, ux
    p1 = (bx, by)
    p2 = (bx - ux * head_len + px * head_w, by - uy * head_len + py * head_w)
    p3 = (bx - ux * head_len - px * head_w, by - uy * head_len - py * head_w)
    draw.polygon([p1, p2, p3], fill=rgb)


def render_board(
    *,
    fen: str,
    last_move: str | None = None,         # "e2e4"
    arrows: list[tuple[str, str, str]] | None = None,  # (from, to, color)
    highlight: list[str] | None = None,
    size: int = 1024,
    flip: bool = False,
) -> Path:
    """Render board to PNG and cache it."""
    key = hashlib.sha256(
        f"{fen}|{last_move}|{arrows}|{highlight}|{size}|{flip}|pillow-v2".encode()
    ).hexdigest()
    out = _cache_dir() / f"{key}.png"
    if out.exists():
        return out

    board = chess.Board(fen)

    # Border holds rank/file coordinates.
    border = max(28, size // 26)
    board_w = size - border * 2
    sq_size = board_w // 8
    board_w = sq_size * 8                  # snap to integer
    full = sq_size * 8 + border * 2
    board_origin = (border, border)

    img = Image.new("RGB", (full, full), COLOR_BORDER)
    draw = ImageDraw.Draw(img)

    # Squares.
    for sq in chess.SQUARES:
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        x, y = _square_xy(f, r, board_origin, sq_size, flip)
        light = (f + r) % 2 == 1
        draw.rectangle((x, y, x + sq_size, y + sq_size), fill=COLOR_LIGHT if light else COLOR_DARK)

    # Last-move highlight.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    if last_move:
        try:
            mv = chess.Move.from_uci(last_move)
            for sq in (mv.from_square, mv.to_square):
                f, r = chess.square_file(sq), chess.square_rank(sq)
                x, y = _square_xy(f, r, board_origin, sq_size, flip)
                odraw.rectangle((x, y, x + sq_size, y + sq_size), fill=COLOR_LASTMOVE)
        except ValueError:
            pass
    if highlight:
        for s in highlight:
            try:
                sq = chess.parse_square(s)
            except ValueError:
                continue
            f, r = chess.square_file(sq), chess.square_rank(sq)
            x, y = _square_xy(f, r, board_origin, sq_size, flip)
            odraw.rectangle((x, y, x + sq_size, y + sq_size), fill=COLOR_HIGHLIGHT)

    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(img)

    # Pieces.
    pf = _piece_font(int(sq_size * 0.82))
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece:
            continue
        sym = piece.symbol()
        glyph = PIECE_GLYPHS.get(sym, sym)
        f, r = chess.square_file(sq), chess.square_rank(sq)
        x, y = _square_xy(f, r, board_origin, sq_size, flip)
        bbox = pf.getbbox(glyph)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        gx = x + (sq_size - gw) // 2 - bbox[0]
        gy = y + (sq_size - gh) // 2 - bbox[1]
        is_white = sym.isupper()
        fill = WHITE_FILL if is_white else BLACK_FILL
        outline = WHITE_OUTLINE if is_white else BLACK_OUTLINE
        # Crisp outline via 8-direction offset compositing.
        ow = max(2, sq_size // 38)
        for ox in (-ow, 0, ow):
            for oy in (-ow, 0, ow):
                if ox == 0 and oy == 0:
                    continue
                draw.text((gx + ox, gy + oy), glyph, font=pf, fill=outline)
        draw.text((gx, gy), glyph, font=pf, fill=fill)

    # Arrows (on a separate translucent overlay to keep crisp colors).
    if arrows:
        arrow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for a, b, color in arrows:
            try:
                _draw_arrow(
                    arrow_layer,
                    chess.parse_square(a),
                    chess.parse_square(b),
                    color,
                    board_origin,
                    sq_size,
                    flip,
                )
            except ValueError:
                continue
        # Soften slightly so the arrow doesn't dominate the read.
        alpha = arrow_layer.split()[-1].point(lambda v: int(v * 0.92))
        arrow_layer.putalpha(alpha)
        img = Image.alpha_composite(img, arrow_layer)

    # Coordinates around the border.
    cf = _coord_font(max(14, border - 8))
    files = "abcdefgh"
    ranks = "12345678"
    if flip:
        files = files[::-1]
        ranks_top_to_bot = ranks            # rank 1 at top
    else:
        ranks_top_to_bot = ranks[::-1]      # rank 8 at top
    cdraw = ImageDraw.Draw(img)
    for i, ch in enumerate(files):
        x = board_origin[0] + i * sq_size + sq_size // 2
        y = board_origin[1] + sq_size * 8 + border // 2
        bbox = cf.getbbox(ch)
        cdraw.text((x - (bbox[2] - bbox[0]) // 2, y - (bbox[3] - bbox[1]) // 2), ch, font=cf, fill=COLOR_COORD)
    for i, ch in enumerate(ranks_top_to_bot):
        x = border // 2
        y = board_origin[1] + i * sq_size + sq_size // 2
        bbox = cf.getbbox(ch)
        cdraw.text((x - (bbox[2] - bbox[0]) // 2, y - (bbox[3] - bbox[1]) // 2), ch, font=cf, fill=COLOR_COORD)

    img = img.convert("RGB").resize((size, size), Image.LANCZOS)
    img.save(out, "PNG")

    with connect() as c:
        c.execute(
            """INSERT OR IGNORE INTO assets (sha, kind, model, prompt, seed, path, cost_usd, reuse_count, created_at)
               VALUES (?, 'board', 'pillow', ?, NULL, ?, 0, 1, ?)""",
            (key, fen, str(out), utc_now_iso()),
        )
    return out
