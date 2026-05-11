"""Slide-level rendering primitives — composes AI imagery + typography +
brand chrome (logo watermark, slide indicator) into a final 1080×1350 PNG.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter

from chessbrain.render import canvas as canvas_mod
from chessbrain.render import effects, typography
from chessbrain.settings import get_settings


@dataclass
class SlideContext:
    slide_index: int
    total_slides: int
    show_watermark: bool = True
    show_pagination: bool = True


def _watermark(img: Image.Image, ctx: SlideContext) -> Image.Image:
    s = get_settings()
    if not s.brand["watermark"]["enabled"] or not ctx.show_watermark:
        return img
    if ctx.slide_index == 0 or ctx.slide_index == ctx.total_slides - 1:
        return img  # cover/CTA usually have full logo elsewhere
    logo_path = s.root / s.brand["logos"]["primary"]
    if not logo_path.exists():
        return img
    logo = Image.open(logo_path).convert("RGBA")
    target_w = int(img.width * float(s.brand["watermark"]["scale"]))
    ratio = target_w / logo.width
    logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
    op = float(s.brand["watermark"]["opacity"])
    alpha = logo.split()[-1].point(lambda v: int(v * op))
    logo.putalpha(alpha)
    margin = 36
    pos = (img.width - logo.width - margin, img.height - logo.height - margin)
    base = img.convert("RGBA")
    base.alpha_composite(logo, pos)
    return base.convert("RGB")


def _pagination(img: Image.Image, ctx: SlideContext) -> Image.Image:
    s = get_settings()
    if not ctx.show_pagination or ctx.total_slides <= 1:
        return img
    draw = ImageDraw.Draw(img)
    palette = s.brand["palette"]
    dot_r = 7
    gap = 14
    total_w = ctx.total_slides * (dot_r * 2) + (ctx.total_slides - 1) * gap
    x0 = (img.width - total_w) // 2
    y = 56
    for i in range(ctx.total_slides):
        cx = x0 + i * (dot_r * 2 + gap) + dot_r
        color = palette["ink"] if i == ctx.slide_index else palette["gold_soft"]
        draw.ellipse((cx - dot_r, y - dot_r, cx + dot_r, y + dot_r), fill=color)
    return img


def finalize(img: Image.Image, ctx: SlideContext) -> Image.Image:
    img = _pagination(img, ctx)
    img = _watermark(img, ctx)
    return img


# ---------------------------------------------------------------------------
# Layouts


def cover_listicle(
    *,
    bg_image: Path,
    hook: str,
    badge: str | None,           # e.g. "MONDAY"
    ctx: SlideContext,
) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.fit_to(canvas_mod.open_rgb(bg_image), *s.carousel_size, mode="cover").copy()

    # Top-area scrim for hook readability.
    overlay = Image.new("RGBA", img.size, (247, 242, 234, 0))
    grad = Image.new("L", (1, img.height), 0)
    for y in range(img.height):
        grad.putpixel((0, y), max(0, int(220 * (1 - y / (img.height * 0.45))) ))
    grad = grad.resize(img.size)
    scrim = Image.new("RGBA", img.size, palette["bg_cream"])
    scrim.putalpha(grad)
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")

    margin = s.runtime["canvas"]["safe_margin"]
    if badge:
        ft = typography.font("display", 36)
        bw, bh = typography.measure(badge, ft)
        pad_x, pad_y = 24, 12
        chip = Image.new("RGB", (bw + pad_x * 2, bh + pad_y * 2), palette["ink"])
        ImageDraw.Draw(chip).text((pad_x, pad_y - 4), badge, font=ft, fill=palette["bg_cream"])
        chip = effects.round_corners(chip, radius=18)
        img_rgba = img.convert("RGBA")
        img_rgba.alpha_composite(chip, (margin, margin + 80))
        img = img_rgba.convert("RGB")

    typography.draw_block(
        img,
        hook,
        role="display",
        xy=(margin, margin + 220),
        box=(img.width - margin * 2, 360),
        fill=palette["ink"],
        align="left",
        max_size=120,
        min_size=60,
        line_spacing=1.04,
        bg=palette["bg_cream"],
        bg_opacity=0.92,
        bg_pad=(28, 16),
        bg_radius=24,
    )
    return finalize(img, ctx)


def numbered_item(
    *,
    bg_image: Path,
    number: int,
    title: str,
    body: str,
    ctx: SlideContext,
) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.fit_to(canvas_mod.open_rgb(bg_image), *s.carousel_size, mode="cover").copy()

    # Bottom card
    margin = s.runtime["canvas"]["safe_margin"]
    card_h = 540
    card_y = img.height - card_h - margin
    card = Image.new("RGB", (img.width - margin * 2, card_h), palette["off_white"])
    card = effects.round_corners(card, radius=36)
    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(card, (margin, card_y))
    img = img_rgba.convert("RGB")

    # Number badge
    num_str = f"{number:02d}"
    ft_num = typography.font("display", 96)
    nw, nh = typography.measure(num_str, ft_num)
    pad = 28
    badge = Image.new("RGB", (nw + pad * 2, nh + pad * 2), palette["gold"])
    ImageDraw.Draw(badge).text((pad, pad - 8), num_str, font=ft_num, fill=palette["bg_cream"])
    badge = effects.round_corners(badge, radius=28)
    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(badge, (margin + 32, card_y - badge.height // 2))
    img = img_rgba.convert("RGB")

    # Title + body inside card
    inner_x = margin + 48
    inner_w = img.width - margin * 2 - 96
    title_y = typography.draw_block(
        img,
        title,
        role="display",
        xy=(inner_x, card_y + 80),
        box=(inner_w, 180),
        fill=palette["ink"],
        max_size=72,
        min_size=40,
    )
    typography.draw_block(
        img,
        body,
        role="body",
        xy=(inner_x, title_y + 16),
        box=(inner_w, card_h - (title_y - card_y) - 80),
        fill=palette["navy"],
        max_size=44,
        min_size=24,
        line_spacing=1.30,
    )
    return finalize(img, ctx)


def cta_card(
    *,
    bg_image: Path | None,
    headline: str,
    subline: str,
    url: str,
    ctx: SlideContext,
    trial_text: str | None = None,
) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    if trial_text is None:
        trial_text = s.brand.get("cta_primary") or "Start 7-day free trial"
    if bg_image and bg_image.exists():
        img = canvas_mod.fit_to(canvas_mod.open_rgb(bg_image), *s.carousel_size, mode="cover").copy()
        scrim = Image.new("RGBA", img.size, (*[int(palette["bg_cream"][i:i+2], 16) for i in (1, 3, 5)], 200))
        img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
    else:
        img = canvas_mod.carousel_canvas()

    margin = s.runtime["canvas"]["safe_margin"]
    # Center logo at top
    logo_bottom = margin + 40
    logo_path = s.root / s.brand["logos"]["primary"]
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        target_w = 240
        logo = logo.resize((target_w, int(logo.height * target_w / logo.width)), Image.LANCZOS)
        img_rgba = img.convert("RGBA")
        img_rgba.alpha_composite(logo, ((img.width - logo.width) // 2, margin + 20))
        img = img_rgba.convert("RGB")
        logo_bottom = margin + 20 + logo.height

    # URL chip (built first so we can reserve its space).
    ft_url = typography.font("display_alt", 44)
    uw, uh = typography.measure(url, ft_url)
    pad_x, pad_y = 32, 18
    chip = Image.new("RGB", (uw + pad_x * 2, uh + pad_y * 2), palette["ink"])
    ImageDraw.Draw(chip).text((pad_x, pad_y - 6), url, font=ft_url, fill=palette["gold"])
    chip = effects.round_corners(chip, radius=26)

    # Trial pill (gold) — sits just above the URL chip.
    ft_trial = typography.font("display", 46)
    tw, th = typography.measure(trial_text, ft_trial)
    tpad_x, tpad_y = 36, 22
    trial = Image.new("RGB", (tw + tpad_x * 2, th + tpad_y * 2), palette["gold"])
    ImageDraw.Draw(trial).text((tpad_x, tpad_y - 6), trial_text, font=ft_trial, fill=palette["ink"])
    trial = effects.round_corners(trial, radius=32)

    chip_bottom_pad = 70
    gap_chips = 22
    chip_top = img.height - margin - chip.height - chip_bottom_pad
    trial_top = chip_top - gap_chips - trial.height

    # Layout headline + subline in the band between logo and trial pill.
    band_top = logo_bottom + 56
    band_bot = trial_top - 56
    band_h = max(360, band_bot - band_top)
    headline_h = int(band_h * 0.62)
    subline_gap = 24
    subline_h = band_h - headline_h - subline_gap

    typography.draw_block(
        img,
        headline,
        role="display",
        xy=(margin, band_top),
        box=(img.width - margin * 2, headline_h),
        fill=palette["ink"],
        align="center",
        max_size=98,
        min_size=48,
        line_spacing=1.05,
    )
    typography.draw_block(
        img,
        subline,
        role="body",
        xy=(margin, band_top + headline_h + subline_gap),
        box=(img.width - margin * 2, subline_h),
        fill=palette["navy"],
        align="center",
        max_size=38,
        min_size=22,
        line_spacing=1.28,
    )

    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(trial, ((img.width - trial.width) // 2, trial_top))
    img_rgba.alpha_composite(chip, ((img.width - chip.width) // 2, chip_top))
    img = img_rgba.convert("RGB")

    return finalize(img, ctx)


def quote_card(*, bg_image: Path, quote: str, author: str, ctx: SlideContext) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.fit_to(canvas_mod.open_rgb(bg_image), *s.carousel_size, mode="cover").copy()
    scrim = Image.new("RGBA", img.size, (31, 42, 68, 160))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")

    margin = s.runtime["canvas"]["safe_margin"]
    typography.draw_block(
        img,
        f"\u201c{quote}\u201d",
        role="display",
        xy=(margin, margin + 280),
        box=(img.width - margin * 2, 600),
        fill=palette["bg_cream"],
        align="center",
        max_size=84,
        min_size=44,
        line_spacing=1.16,
        bg=palette["ink"],
        bg_opacity=0.78,
        bg_pad=(36, 20),
        bg_radius=28,
    )
    typography.draw_block(
        img,
        f"— {author}",
        role="body",
        xy=(margin, img.height - margin - 120),
        box=(img.width - margin * 2, 80),
        fill=palette["gold_soft"],
        align="center",
        max_size=42,
        min_size=28,
        bg=palette["ink"],
        bg_opacity=0.78,
        bg_pad=(28, 14),
        bg_radius=22,
    )
    return finalize(img, ctx)


def meme_single(*, bg_image: Path, hook: str, ctx: SlideContext) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.fit_to(canvas_mod.open_rgb(bg_image), *s.carousel_size, mode="cover").copy()
    margin = s.runtime["canvas"]["safe_margin"]
    typography.draw_block(
        img,
        hook,
        role="display",
        xy=(margin, img.height - 460),
        box=(img.width - margin * 2, 360),
        fill=palette["ink"],
        align="center",
        max_size=92,
        min_size=44,
        line_spacing=1.10,
        bg=palette["bg_cream"],
        bg_opacity=0.92,
        bg_pad=(32, 18),
        bg_radius=28,
    )
    return finalize(img, ctx)


def meme_repost(*, meme_image: Path, attribution: str, ctx: SlideContext) -> Image.Image:
    """Re-share a meme image as-is, centered on a brand-cream canvas with a
    small attribution footer. No text overlay — the meme already has its joke."""
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.carousel_canvas()
    margin = s.runtime["canvas"]["safe_margin"]

    src = canvas_mod.open_rgb(meme_image)
    # Fit-contain into a slightly inset frame, leaving room for footer.
    footer_h = 90
    frame_w = img.width - margin * 2
    frame_h = img.height - margin * 2 - footer_h
    scale = min(frame_w / src.width, frame_h / src.height)
    new_w = int(src.width * scale)
    new_h = int(src.height * scale)
    src = src.resize((new_w, new_h), Image.LANCZOS)
    fx = (img.width - new_w) // 2
    fy = margin + (frame_h - new_h) // 2

    img_rgba = img.convert("RGBA")
    sh = effects.drop_shadow(src.convert("RGBA"), blur=24, opacity=0.18)
    img_rgba.alpha_composite(sh, (fx - (sh.width - new_w) // 2, fy - (sh.height - new_h) // 2))
    img_rgba.alpha_composite(src.convert("RGBA"), (fx, fy))
    img = img_rgba.convert("RGB")

    typography.draw_block(
        img,
        attribution,
        role="body_light",
        xy=(margin, img.height - margin - footer_h + 20),
        box=(img.width - margin * 2, footer_h),
        fill=palette["ink"],
        align="center",
        max_size=28,
        min_size=20,
    )
    return finalize(img, ctx)


def board_only(*, board_image: Path, caption: str | None, ctx: SlideContext) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.carousel_canvas()
    margin = s.runtime["canvas"]["safe_margin"]
    target = img.width - margin * 2
    board = canvas_mod.open_rgb(board_image)
    board = board.resize((target, target), Image.LANCZOS)
    bx = margin
    by = (img.height - target) // 2 - 40
    img_rgba = img.convert("RGBA")
    sh = effects.drop_shadow(board.convert("RGBA"), blur=30, opacity=0.18)
    img_rgba.alpha_composite(sh, (bx - (sh.width - board.width) // 2, by - (sh.height - board.height) // 2))
    img = img_rgba.convert("RGB")
    if caption:
        typography.draw_block(
            img,
            caption,
            role="display",
            xy=(margin, by + target + 60),
            box=(target, 200),
            fill=palette["ink"],
            align="center",
            max_size=64,
            min_size=32,
        )
    return finalize(img, ctx)


def board_explainer(
    *,
    board_image: Path,
    title: str,
    body: str,
    ctx: SlideContext,
) -> Image.Image:
    s = get_settings()
    palette = s.brand["palette"]
    img = canvas_mod.carousel_canvas()
    margin = s.runtime["canvas"]["safe_margin"]
    target = img.width - margin * 2 - 80
    board = canvas_mod.open_rgb(board_image).resize((target, target), Image.LANCZOS)
    img_rgba = img.convert("RGBA")
    sh = effects.drop_shadow(board.convert("RGBA"), blur=24, opacity=0.16)
    img_rgba.alpha_composite(sh, (margin + 40 - (sh.width - target) // 2, margin + 40 - (sh.height - target) // 2))
    img = img_rgba.convert("RGB")
    text_y = margin + 40 + target + 60
    text_box_h = img.height - text_y - margin - 60
    title_end = typography.draw_block(
        img,
        title,
        role="display",
        xy=(margin, text_y),
        box=(img.width - margin * 2, text_box_h // 2),
        fill=palette["ink"],
        max_size=64,
        min_size=36,
    )
    typography.draw_block(
        img,
        body,
        role="body",
        xy=(margin, title_end + 16),
        box=(img.width - margin * 2, text_box_h - (title_end - text_y) - 16),
        fill=palette["navy"],
        max_size=42,
        min_size=24,
        line_spacing=1.30,
    )
    return finalize(img, ctx)
