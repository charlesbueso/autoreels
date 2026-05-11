"""Typography helpers — font loading, text wrapping, auto-fit."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from chessbrain.settings import get_settings


@lru_cache(maxsize=64)
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    fonts = get_settings().brand["fonts"]
    return load_font(str(get_settings().root / fonts[role]), size)


def measure(text: str, ft: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = ft.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(text: str, ft: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if measure(trial, ft)[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def auto_fit_font(
    text: str,
    role: str,
    *,
    max_width: int,
    max_height: int,
    max_size: int = 140,
    min_size: int = 24,
    line_spacing: float = 1.10,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Find largest font size that fits text in (max_width, max_height).

    Returns (font, wrapped_lines, total_height).
    """
    for size in range(max_size, min_size - 1, -2):
        ft = font(role, size)
        lines = wrap_text(text, ft, max_width)
        line_h = ft.getbbox("Ag")[3] - ft.getbbox("Ag")[1]
        block_h = int(len(lines) * line_h * line_spacing)
        widest = max((measure(line, ft)[0] for line in lines), default=0)
        if widest <= max_width and block_h <= max_height:
            return ft, lines, block_h
    ft = font(role, min_size)
    lines = wrap_text(text, ft, max_width)
    line_h = ft.getbbox("Ag")[3] - ft.getbbox("Ag")[1]
    return ft, lines, int(len(lines) * line_h * line_spacing)


def draw_block(
    img: Image.Image,
    text: str,
    *,
    role: str,
    xy: tuple[int, int],
    box: tuple[int, int],
    fill: str,
    align: str = "left",
    max_size: int = 140,
    min_size: int = 24,
    line_spacing: float = 1.10,
    bg: str | None = None,
    bg_pad: tuple[int, int] = (28, 16),
    bg_radius: int = 24,
    bg_opacity: float = 1.0,
) -> int:
    """Draw text block fitted to ``box``; returns y after the block.

    If ``bg`` is provided, a rounded pill is drawn per line behind the text
    for contrast against busy AI backgrounds. ``bg_opacity`` ∈ [0, 1].
    """
    ft, lines, _h = auto_fit_font(
        text,
        role,
        max_width=box[0],
        max_height=box[1],
        max_size=max_size,
        min_size=min_size,
        line_spacing=line_spacing,
    )
    line_h = ft.getbbox("Ag")[3] - ft.getbbox("Ag")[1]
    step = int(line_h * line_spacing)
    pad_x, pad_y = bg_pad

    if bg is not None:
        # Draw per-line rounded pills onto an RGBA overlay first.
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        # Parse hex bg color into rgba with requested opacity.
        hx = bg.lstrip("#")
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        a = max(0, min(255, int(255 * bg_opacity)))
        x0, y = xy
        for line in lines:
            w, _ = measure(line, ft)
            if align == "center":
                x = x0 + (box[0] - w) // 2
            elif align == "right":
                x = x0 + box[0] - w
            else:
                x = x0
            rect = (
                x - pad_x,
                y - pad_y // 2,
                x + w + pad_x,
                y + line_h + pad_y,
            )
            odraw.rounded_rectangle(rect, radius=bg_radius, fill=(r, g, b, a))
            y += step
        # Composite overlay onto img.
        base = img.convert("RGBA")
        base.alpha_composite(overlay)
        # Mutate img in place: paste back.
        img.paste(base.convert(img.mode))

    draw = ImageDraw.Draw(img)
    x0, y = xy
    for line in lines:
        w, _ = measure(line, ft)
        if align == "center":
            x = x0 + (box[0] - w) // 2
        elif align == "right":
            x = x0 + box[0] - w
        else:
            x = x0
        draw.text((x, y), line, font=ft, fill=fill)
        y += step
    return y
