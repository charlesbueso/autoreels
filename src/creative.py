"""Creative coding engine — animated text slides, transitions, motion graphics.

Generates video segments programmatically using Pillow for frame rendering.
Used by the Director alongside Wan2.1 AI clips to build professional reels.
"""

from __future__ import annotations

import math
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent  # project root


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _get_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if font_path:
        p = Path(font_path)
        if not p.is_absolute():
            p = _ROOT / p
        return ImageFont.truetype(str(p), size)
    # Fallback to bundled Poppins Medium
    bundled = _ROOT / "assets" / "fonts" / "Poppins-Medium.ttf"
    if bundled.exists():
        return ImageFont.truetype(str(bundled), size)
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _get_font_bold(font_bold_path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if font_bold_path:
        p = Path(font_bold_path)
        if not p.is_absolute():
            p = _ROOT / p
        return ImageFont.truetype(str(p), size)
    bundled = _ROOT / "assets" / "fonts" / "Poppins-SemiBold.ttf"
    if bundled.exists():
        return ImageFont.truetype(str(bundled), size)
    return _get_font(None, size)


def _load_logo(logo_path: str | None, max_w: int, max_h: int) -> Image.Image | None:
    """Load and resize a logo to fit within max_w x max_h, preserving aspect ratio."""
    if not logo_path:
        return None
    p = Path(logo_path)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return None
    try:
        logo = Image.open(p).convert("RGBA")
        logo.thumbnail((max_w, max_h), Image.LANCZOS)
        return logo
    except Exception:
        return None


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex_to_rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(h)
    return (r, g, b, a)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2


def _ease_out_elastic(t: float) -> float:
    if t == 0 or t == 1:
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Background renderers
# ---------------------------------------------------------------------------

def _render_solid_bg(w: int, h: int, color: str) -> Image.Image:
    return Image.new("RGBA", (w, h), _hex_to_rgba(color))


def _render_gradient_bg_fast(
    w: int, h: int,
    color_top: str, color_bottom: str,
) -> Image.Image:
    """Fast numpy-based vertical gradient."""
    r1, g1, b1 = _hex_to_rgb(color_top)
    r2, g2, b2 = _hex_to_rgb(color_bottom)
    t = np.linspace(0, 1, h, dtype=np.float32).reshape(-1, 1)
    r = (r1 + (r2 - r1) * t).astype(np.uint8)
    g = (g1 + (g2 - g1) * t).astype(np.uint8)
    b = (b1 + (b2 - b1) * t).astype(np.uint8)
    a = np.full_like(r, 255)
    row = np.concatenate([r, g, b, a], axis=1)
    arr = np.tile(row[:, np.newaxis, :], (1, w, 1))
    return Image.fromarray(arr, "RGBA")


def _render_radial_gradient_bg(
    w: int, h: int,
    color_center: str, color_edge: str,
    cx: float = 0.5, cy: float = 0.4,
) -> Image.Image:
    """Radial gradient — bright center fading to darker edges."""
    r1, g1, b1 = _hex_to_rgb(color_center)
    r2, g2, b2 = _hex_to_rgb(color_edge)
    y_grid, x_grid = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((x_grid / w - cx) ** 2) + ((y_grid / h - cy) ** 2))
    max_dist = math.sqrt(max(cx, 1 - cx) ** 2 + max(cy, 1 - cy) ** 2)
    t = np.clip(dist / max_dist, 0, 1)[..., np.newaxis]
    c1 = np.array([r1, g1, b1], dtype=np.float32)
    c2 = np.array([r2, g2, b2], dtype=np.float32)
    pixels = (c1 * (1 - t) + c2 * t).astype(np.uint8)
    alpha = np.full((h, w, 1), 255, dtype=np.uint8)
    arr = np.concatenate([pixels, alpha], axis=2)
    return Image.fromarray(arr, "RGBA")


def _draw_accent_stripe(
    draw: ImageDraw.ImageDraw,
    w: int, h: int,
    color: str,
    y_pos: float = 0.5,
    thickness: int = 4,
    width_frac: float = 0.3,
    alpha: int = 200,
    frame_t: float = 0.0,
) -> None:
    """Draw a horizontal accent line that animates in."""
    r, g, b = _hex_to_rgb(color)
    ease = _ease_out_cubic(min(frame_t / 0.4, 1.0))
    line_w = int(w * width_frac * ease)
    cx = w // 2
    y = int(h * y_pos)
    draw.rectangle(
        [cx - line_w // 2, y, cx + line_w // 2, y + thickness],
        fill=(r, g, b, alpha),
    )


def _draw_corner_accents(
    draw: ImageDraw.ImageDraw,
    w: int, h: int,
    color: str,
    alpha: int = 120,
    size: int = 40,
    thickness: int = 3,
) -> None:
    """Draw decorative corner brackets."""
    r, g, b = _hex_to_rgb(color)
    fill = (r, g, b, alpha)
    m = 20  # margin
    # Top-left
    draw.line([(m, m), (m + size, m)], fill=fill, width=thickness)
    draw.line([(m, m), (m, m + size)], fill=fill, width=thickness)
    # Top-right
    draw.line([(w - m, m), (w - m - size, m)], fill=fill, width=thickness)
    draw.line([(w - m, m), (w - m, m + size)], fill=fill, width=thickness)
    # Bottom-left
    draw.line([(m, h - m), (m + size, h - m)], fill=fill, width=thickness)
    draw.line([(m, h - m), (m, h - m - size)], fill=fill, width=thickness)
    # Bottom-right
    draw.line([(w - m, h - m), (w - m - size, h - m)], fill=fill, width=thickness)
    draw.line([(w - m, h - m), (w - m, h - m - size)], fill=fill, width=thickness)


# ---------------------------------------------------------------------------
# Particle / decoration renderers
# ---------------------------------------------------------------------------

def _draw_particles(
    draw: ImageDraw.ImageDraw,
    w: int, h: int,
    color: str,
    count: int,
    frame_t: float,
    seed: int = 42,
    style: str = "float",
) -> None:
    """Draw animated particles — float (drift up) or sparkle (twinkle in place)."""
    rng = np.random.RandomState(seed)
    r, g, b = _hex_to_rgb(color)
    for i in range(count):
        base_x = rng.randint(0, w)
        base_y = rng.randint(0, h)
        speed = 0.3 + rng.random() * 0.7
        size = 1.5 + rng.random() * 3.5

        if style == "sparkle":
            # Twinkle in place with phase offsets
            phase = rng.random() * math.pi * 2
            brightness = 0.5 + 0.5 * math.sin(frame_t * 6 + phase)
            alpha = int(255 * brightness)
            x = base_x + math.sin(frame_t * 2 + i * 0.5) * 5
            y = base_y + math.cos(frame_t * 2 + i * 0.3) * 5
        else:
            # Drift upward, wrap around
            y = (base_y - frame_t * speed * h * 0.5) % h
            x = base_x + math.sin(frame_t * 3 + i) * 15
            alpha = int(100 + 155 * (0.5 + 0.5 * math.sin(frame_t * 4 + i * 0.7)))

        # Glow effect — larger transparent circle behind
        if size > 2.5:
            glow_size = size * 2.5
            draw.ellipse(
                [x - glow_size, y - glow_size, x + glow_size, y + glow_size],
                fill=(r, g, b, alpha // 5),
            )
        draw.ellipse(
            [x - size, y - size, x + size, y + size],
            fill=(r, g, b, alpha),
        )


def _draw_light_rays(
    draw: ImageDraw.ImageDraw,
    w: int, h: int,
    color: str,
    frame_t: float,
    count: int = 5,
) -> None:
    """Draw subtle animated light rays emanating from top-center."""
    r, g, b = _hex_to_rgb(color)
    cx, cy = w // 2, -50
    for i in range(count):
        angle_base = -0.4 + (i / (count - 1)) * 0.8
        angle = angle_base + math.sin(frame_t * 2 + i) * 0.05
        ray_len = h * 1.5
        ex = cx + math.sin(angle) * ray_len
        ey = cy + math.cos(angle) * ray_len
        alpha = int(15 + 10 * math.sin(frame_t * 3 + i * 1.2))
        draw.line([(cx, cy), (ex, ey)], fill=(r, g, b, alpha), width=w // 8)


def _apply_warm_vignette(frame: Image.Image, strength: float = 0.35) -> Image.Image:
    """Apply a soft warm vignette — darker, warmer edges drawing focus to center."""
    w, h = frame.size
    y_grid, x_grid = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    dist = np.sqrt(((x_grid - cx) / (w * 0.6)) ** 2 + ((y_grid - cy) / (h * 0.55)) ** 2)
    dist = np.clip(dist, 0, 1)
    # Smooth falloff
    vignette = (dist ** 1.8) * strength
    arr = np.array(frame).astype(np.float32)
    # Darken and warm the edges (pull toward warm brown)
    warm_tint = np.array([20, 12, 5], dtype=np.float32)  # warm shadow tint
    for c in range(3):
        arr[:, :, c] = arr[:, :, c] * (1 - vignette) + warm_tint[c] * vignette * 0.3
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, frame.mode)


def _apply_paper_texture(frame: Image.Image, intensity: float = 8.0, seed: int = 42) -> Image.Image:
    """Add subtle organic paper-grain noise for warmth."""
    arr = np.array(frame).astype(np.float32)
    rng = np.random.RandomState(seed)
    noise = rng.normal(0, intensity, (frame.size[1], frame.size[0]))
    for c in range(min(arr.shape[2], 3)):
        arr[:, :, c] += noise
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, frame.mode)


def _draw_warm_glow(
    frame: Image.Image,
    color: str,
    cx: float = 0.5,
    cy: float = 0.3,
    radius: float = 0.6,
    intensity: float = 0.08,
) -> Image.Image:
    """Soft circular warm glow — like lamplight falling on a surface."""
    w, h = frame.size
    r, g, b = _hex_to_rgb(color)
    y_grid, x_grid = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((x_grid / w - cx) ** 2) + ((y_grid / h - cy) ** 2))
    glow = np.clip(1.0 - dist / radius, 0, 1) ** 2 * intensity
    arr = np.array(frame).astype(np.float32)
    arr[:, :, 0] += glow * r
    arr[:, :, 1] += glow * g
    arr[:, :, 2] += glow * b
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, frame.mode)


def _draw_ornamental_divider(
    draw: ImageDraw.ImageDraw,
    w: int, h: int,
    color: str,
    y_pos: float = 0.5,
    alpha: int = 160,
    frame_t: float = 0.0,
) -> None:
    """Delicate ornamental divider — thin line with small diamond center."""
    r, g, b = _hex_to_rgb(color)
    ease = _ease_out_cubic(min(frame_t / 0.5, 1.0))
    if ease < 0.05:
        return
    y = int(h * y_pos)
    cx = w // 2
    line_half_w = int(w * 0.15 * ease)
    diamond_size = int(4 * ease)
    a = int(alpha * ease)
    fill = (r, g, b, a)
    # Left line
    draw.line([(cx - line_half_w, y), (cx - diamond_size - 4, y)], fill=fill, width=1)
    # Right line
    draw.line([(cx + diamond_size + 4, y), (cx + line_half_w, y)], fill=fill, width=1)
    # Center diamond
    draw.polygon([
        (cx, y - diamond_size),
        (cx + diamond_size, y),
        (cx, y + diamond_size),
        (cx - diamond_size, y),
    ], fill=fill)


# ---------------------------------------------------------------------------
# Text animation renderers
# ---------------------------------------------------------------------------

def _render_text_on_frame(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    color: str,
    position: str,
    animation: str,
    frame_t: float,
    duration: float,
    w: int, h: int,
    shadow: bool = True,
    line_spacing: int = 14,
    glow: bool = False,
    glow_color: str | None = None,
) -> Image.Image:
    """Render animated text onto a frame. frame_t is 0..1 progress through segment."""
    draw = ImageDraw.Draw(img)
    lines = _wrap_text(text, font, int(w * 0.82))
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + line_spacing * (len(lines) - 1)
    max_w = max(line_widths) if line_widths else 0

    # Base position (shifted slightly upward so content isn't hidden by
    # phone UI chrome at the bottom of reels)
    up_bias = int(h * 0.04)
    if position == "center":
        base_x = (w - max_w) // 2
        base_y = (h - total_h) // 2 - up_bias
    elif position == "top":
        base_x = (w - max_w) // 2
        base_y = int(h * 0.12)
    elif position == "bottom":
        base_x = (w - max_w) // 2
        base_y = int(h * 0.75) - total_h
    else:
        base_x = (w - max_w) // 2
        base_y = (h - total_h) // 2 - up_bias

    # Animation
    offset_x, offset_y = 0, 0
    alpha_mult = 1.0

    if animation == "fade_in":
        alpha_mult = _ease_out_cubic(min(frame_t / 0.3, 1.0))
    elif animation == "fade_out":
        alpha_mult = 1.0 - _ease_out_cubic(max((frame_t - 0.7) / 0.3, 0.0))
    elif animation == "fade_in_out":
        if frame_t < 0.2:
            alpha_mult = _ease_out_cubic(frame_t / 0.2)
        elif frame_t > 0.8:
            alpha_mult = 1.0 - _ease_out_cubic((frame_t - 0.8) / 0.2)
    elif animation == "slide_up":
        ease = _ease_out_back(min(frame_t / 0.35, 1.0))
        offset_y = int((1 - ease) * h * 0.25)
        alpha_mult = _ease_out_cubic(min(frame_t / 0.35, 1.0))
    elif animation == "slide_down":
        ease = _ease_out_back(min(frame_t / 0.35, 1.0))
        offset_y = -int((1 - ease) * h * 0.25)
        alpha_mult = _ease_out_cubic(min(frame_t / 0.35, 1.0))
    elif animation == "slide_left":
        ease = _ease_out_back(min(frame_t / 0.35, 1.0))
        offset_x = int((1 - ease) * w * 0.35)
        alpha_mult = _ease_out_cubic(min(frame_t / 0.35, 1.0))
    elif animation == "slide_right":
        ease = _ease_out_back(min(frame_t / 0.35, 1.0))
        offset_x = -int((1 - ease) * w * 0.35)
        alpha_mult = _ease_out_cubic(min(frame_t / 0.35, 1.0))
    elif animation == "typewriter":
        total_chars = sum(len(l) for l in lines)
        revealed = int(_ease_out_cubic(min(frame_t / 0.7, 1.0)) * total_chars)
        lines = _typewriter_truncate(lines, revealed)
    elif animation == "scale_up":
        ease = _ease_out_elastic(min(frame_t / 0.5, 1.0))
        alpha_mult = _ease_out_cubic(min(frame_t / 0.3, 1.0))
    elif animation == "bounce":
        if frame_t < 0.4:
            ease = _ease_out_back(frame_t / 0.4)
            offset_y = int((1 - ease) * h * 0.25)
            alpha_mult = _ease_out_cubic(frame_t / 0.25)
    elif animation == "word_by_word":
        words = text.split()
        total_words = len(words)
        revealed = int(_ease_out_cubic(min(frame_t / 0.6, 1.0)) * total_words)
        partial_text = " ".join(words[:revealed])
        lines = _wrap_text(partial_text, font, int(w * 0.82))
    elif animation == "pop_in":
        if frame_t < 0.3:
            ease = _ease_out_elastic(frame_t / 0.3)
            alpha_mult = min(ease, 1.0)
        elif frame_t > 0.85:
            alpha_mult = 1.0 - _ease_out_cubic((frame_t - 0.85) / 0.15)

    alpha = int(255 * max(0, min(1, alpha_mult)))
    r, g, b = _hex_to_rgb(color)

    cy = base_y + offset_y
    for i, line in enumerate(lines):
        lw = line_widths[i] if i < len(line_widths) else 0
        cx = (w - lw) // 2 + offset_x

        # Glow behind text
        if glow and alpha > 50:
            gc = _hex_to_rgb(glow_color or color)
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    if dx * dx + dy * dy <= 9:
                        draw.text(
                            (cx + dx, cy + dy), line,
                            fill=(gc[0], gc[1], gc[2], alpha // 6), font=font,
                        )

        # Shadow
        if shadow and alpha > 30:
            draw.text((cx + 2, cy + 3), line, fill=(0, 0, 0, int(alpha * 0.6)), font=font)

        # Main text
        draw.text((cx, cy), line, fill=(r, g, b, alpha), font=font)
        cy += (line_heights[i] if i < len(line_heights) else 30) + line_spacing

    return img


def _typewriter_truncate(lines: list[str], max_chars: int) -> list[str]:
    result = []
    remaining = max_chars
    for line in lines:
        if remaining <= 0:
            break
        result.append(line[:remaining])
        remaining -= len(line)
    return result


# ---------------------------------------------------------------------------
# Segment renderers — each produces a list of numpy frames
# ---------------------------------------------------------------------------

def _composite_bg_image(
    frame: Image.Image,
    bg_image: Image.Image,
    bg_color: str,
    overlay_opacity: float = 0.55,
) -> Image.Image:
    """Composite a background image onto a frame with a brand-tinted overlay.

    The overlay keeps text readable while showing the photo beneath.
    """
    # Resize bg_image to match frame if needed
    if bg_image.size != frame.size:
        bg_image = bg_image.resize(frame.size, Image.LANCZOS)

    bg_rgba = bg_image.convert("RGBA")

    # Create a brand-colored overlay
    r, g, b = _hex_to_rgb(bg_color)
    overlay = Image.new("RGBA", frame.size, (r, g, b, int(255 * overlay_opacity)))

    # Photo → overlay on top → gives tinted photo background
    frame.paste(bg_rgba, (0, 0))
    frame = Image.alpha_composite(frame, overlay)
    return frame


def _composite_asset(
    frame: Image.Image,
    asset_img: Image.Image,
    position: str = "bottom_right",
    margin: float = 0.04,
    opacity: float = 0.0,
) -> Image.Image:
    """Place a small decorative asset (PNG with alpha) on a frame.

    *opacity* of 0.0 means use the asset's own alpha unchanged.
    """
    w, h = frame.size
    aw, ah = asset_img.size
    mx = int(w * margin)
    my = int(h * margin)

    if position == "bottom_right":
        x, y = w - aw - mx, h - ah - my
    elif position == "bottom_left":
        x, y = mx, h - ah - my
    elif position == "top_right":
        x, y = w - aw - mx, my
    elif position == "top_left":
        x, y = mx, my
    elif position == "bottom_center":
        x, y = (w - aw) // 2, h - ah - my
    else:  # center
        x, y = (w - aw) // 2, (h - ah) // 2

    asset_rgba = asset_img.convert("RGBA")
    if opacity > 0:
        arr = np.array(asset_rgba)
        arr[:, :, 3] = (arr[:, :, 3].astype(np.float32) * opacity).astype(np.uint8)
        asset_rgba = Image.fromarray(arr, "RGBA")

    frame.paste(asset_rgba, (x, y), asset_rgba)
    return frame


def render_text_slide(
    text: str,
    duration: float,
    fps: int,
    width: int,
    height: int,
    *,
    animation: str = "fade_in_out",
    text_color: str = "#1a1a1a",
    bg_color: str = "#f7f2ea",
    bg_color_2: str | None = None,
    bg_style: str = "gradient",
    accent_color: str = "#C49A3C",
    font_size: int = 56,
    font_path: str | None = None,
    position: str = "center",
    particles: bool = False,
    particle_color: str = "#C49A3C",
    show_divider: bool = True,
    bg_image: Image.Image | None = None,
    bg_image_opacity: float = 0.55,
    asset_image: Image.Image | None = None,
    asset_position: str = "bottom_right",
) -> list[np.ndarray]:
    """Render an animated text slide as a list of numpy RGB frames.

    bg_image: optional background photo (composited under a brand overlay).
    asset_image: optional small decorative PNG placed at asset_position.
    """
    num_frames = int(duration * fps)
    font = _get_font(font_path, font_size)
    frames = []

    # When using a bg image, swap to light text for readability
    if bg_image is not None:
        text_color = "#f7f2ea"

    for fi in range(num_frames):
        t = fi / max(num_frames - 1, 1)

        # Base background
        frame = Image.new("RGBA", (width, height), _hex_to_rgb(bg_color) + (255,))

        # Composite background image if provided
        if bg_image is not None:
            frame = _composite_bg_image(frame, bg_image, bg_color, bg_image_opacity)

        draw = ImageDraw.Draw(frame)

        # Measure text block to position divider above it with clearance
        font_for_measure = _get_font(font_path, font_size)
        text_lines = _wrap_text(text, font_for_measure, int(width * 0.82))
        text_line_heights = []
        for line in text_lines:
            bbox = draw.textbbox((0, 0), line, font=font_for_measure)
            text_line_heights.append(bbox[3] - bbox[1])
        total_text_h = sum(text_line_heights) + 14 * (len(text_line_heights) - 1)

        if position == "center":
            text_top_y = (height - total_text_h) // 2 - int(height * 0.04)
        elif position == "top":
            text_top_y = int(height * 0.12)
        else:  # bottom
            text_top_y = int(height * 0.75) - total_text_h

        # Ornamental divider — placed above the text block with spacing
        if show_divider:
            divider_y_px = text_top_y - 28
            if divider_y_px > 30:
                _draw_ornamental_divider(
                    draw, width, height, accent_color,
                    y_pos=divider_y_px / height, frame_t=t,
                )

        # Text — use glow when on image bg for extra readability
        has_bg_image = bg_image is not None
        frame = _render_text_on_frame(
            frame, text, font, text_color, position, animation,
            t, duration, width, height,
            shadow=True,
            glow=has_bg_image,
            glow_color="#000000" if has_bg_image else None,
        )

        # Asset sticker overlay — fades in with a slight delay
        if asset_image is not None:
            asset_ease = _ease_out_cubic(min(t / 0.5, 1.0))
            if asset_ease > 0.05:
                frame = _composite_asset(
                    frame, asset_image,
                    position=asset_position,
                    margin=0.04,
                    opacity=asset_ease,
                )

        # Convert RGBA → RGB
        rgb = Image.new("RGB", (width, height), (0, 0, 0))
        rgb.paste(frame, mask=frame.split()[3])
        frames.append(np.array(rgb))

    return frames


def render_title_card(
    title: str,
    subtitle: str,
    duration: float,
    fps: int,
    width: int,
    height: int,
    *,
    title_color: str = "#1a1a1a",
    subtitle_color: str = "#C49A3C",
    bg_color: str = "#f7f2ea",
    bg_color_2: str | None = None,
    accent_color: str = "#C49A3C",
    font_path: str | None = None,
    font_bold_path: str | None = None,
    logo_path: str | None = None,
    title_size: int = 64,
    subtitle_size: int = 36,
    particles: bool = False,
    particle_color: str = "#C49A3C",
    show_divider: bool = True,
) -> list[np.ndarray]:
    """Render a title card with logo + title + subtitle, all animated."""
    num_frames = int(duration * fps)
    title_font = _get_font_bold(font_bold_path, title_size)
    sub_font = _get_font(font_path, subtitle_size)

    logo = _load_logo(logo_path, max_w=int(width * 0.45), max_h=int(height * 0.20))
    frames = []

    for fi in range(num_frames):
        t = fi / max(num_frames - 1, 1)

        # Plain cream background
        frame = Image.new("RGBA", (width, height), _hex_to_rgb(bg_color) + (255,))

        draw = ImageDraw.Draw(frame)

        # Logo — fades in, over clean cream background
        logo_bottom_y = int(height * 0.30)  # default if no logo
        if logo:
            logo_ease = _ease_out_cubic(min(t / 0.4, 1.0))
            logo_y = int(height * 0.22) - int((1 - logo_ease) * height * 0.05)
            logo_x = (width - logo.width) // 2
            # Draw a solid cream rect behind logo area so vignette doesn't darken it
            pad = 16
            cream = _hex_to_rgba(bg_color)
            draw.rectangle(
                [logo_x - pad, logo_y - pad,
                 logo_x + logo.width + pad, logo_y + logo.height + pad],
                fill=cream,
            )
            temp_logo = logo.copy()
            lo_arr = np.array(temp_logo)
            lo_arr[:, :, 3] = (lo_arr[:, :, 3].astype(np.float32) * logo_ease).astype(np.uint8)
            temp_logo = Image.fromarray(lo_arr, "RGBA")
            frame.paste(temp_logo, (logo_x, logo_y), temp_logo)
            logo_bottom_y = logo_y + logo.height + 12

        # Measure title block to position divider between logo and title
        title_lines = _wrap_text(title, title_font, int(width * 0.8))
        title_lhs = []
        title_lws = []
        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            title_lws.append(bbox[2] - bbox[0])
            title_lhs.append(bbox[3] - bbox[1])
        total_title_h = sum(title_lhs) + 10 * (len(title_lhs) - 1) if title_lhs else 40

        # Title start Y — place below logo with room for divider
        title_start_y = logo_bottom_y + 35 if logo else int(height * 0.42)

        # Ornamental divider — centered between logo bottom and title top
        if show_divider:
            divider_y_px = (logo_bottom_y + title_start_y) // 2
            _draw_ornamental_divider(
                draw, width, height, accent_color,
                y_pos=divider_y_px / height, frame_t=t,
            )

        # Title — gentle fade-slide up
        title_ease = _ease_out_cubic(min(t / 0.45, 1.0))
        title_alpha = int(255 * _ease_out_cubic(min(t / 0.35, 1.0)))
        title_offset_y = int((1 - title_ease) * height * 0.04)
        tr, tg, tb = _hex_to_rgb(title_color)

        cy = title_start_y + title_offset_y
        for i, line in enumerate(title_lines):
            lw = title_lws[i]
            cx = (width - lw) // 2
            # Soft warm shadow
            draw.text((cx + 1, cy + 2), line, fill=(80, 60, 40, int(title_alpha * 0.12)), font=title_font)
            draw.text((cx, cy), line, fill=(tr, tg, tb, title_alpha), font=title_font)
            cy += title_lhs[i] + 10

        # Subtitle — fades in after title settles
        sub_t = max(0, (t - 0.35) / 0.65)
        if sub_t > 0:
            sub_lines = _wrap_text(subtitle, sub_font, int(width * 0.85))
            sub_alpha = int(255 * _ease_out_cubic(min(sub_t / 0.35, 1.0)))
            sr, sg, sb = _hex_to_rgb(subtitle_color)
            sub_y = cy + 40
            for line in sub_lines:
                bbox = draw.textbbox((0, 0), line, font=sub_font)
                lw = bbox[2] - bbox[0]
                lh = bbox[3] - bbox[1]
                sub_cx = (width - lw) // 2
                draw.text((sub_cx, sub_y), line, fill=(sr, sg, sb, sub_alpha), font=sub_font)
                sub_y += lh + 8

        rgb = Image.new("RGB", (width, height), (0, 0, 0))
        rgb.paste(frame, mask=frame.split()[3])
        frames.append(np.array(rgb))

    return frames


def render_cta_slide(
    cta_text: str,
    tagline: str,
    duration: float,
    fps: int,
    width: int,
    height: int,
    *,
    cta_color: str = "#1a1a1a",
    tagline_color: str = "#C49A3C",
    bg_color: str = "#f7f2ea",
    bg_color_2: str | None = None,
    accent_color: str = "#C49A3C",
    font_path: str | None = None,
    font_bold_path: str | None = None,
    logo_path: str | None = None,
    cta_size: int = 56,
    tagline_size: int = 32,
    particles: bool = False,
    particle_color: str = "#C49A3C",
    show_divider: bool = True,
) -> list[np.ndarray]:
    """Render a call-to-action ending slide with logo."""
    num_frames = int(duration * fps)
    cta_font = _get_font_bold(font_bold_path, cta_size)
    tag_font = _get_font(font_path, tagline_size)

    logo = _load_logo(logo_path, max_w=int(width * 0.4), max_h=int(height * 0.18))
    frames = []

    for fi in range(num_frames):
        t = fi / max(num_frames - 1, 1)

        # Plain cream background
        frame = Image.new("RGBA", (width, height), _hex_to_rgb(bg_color) + (255,))

        draw = ImageDraw.Draw(frame)

        # --- Logo at top, then divider, then CTA text, then tagline ---

        # Measure CTA text block
        cta_lines_m = _wrap_text(cta_text, cta_font, int(width * 0.82))
        cta_line_heights = []
        for line in cta_lines_m:
            bbox = draw.textbbox((0, 0), line, font=cta_font)
            cta_line_heights.append(bbox[3] - bbox[1])
        total_cta_h = sum(cta_line_heights) + 14 * (len(cta_line_heights) - 1)

        # Measure tagline block
        tag_lines = _wrap_text(tagline, tag_font, int(width * 0.8))
        tag_line_heights = []
        for line in tag_lines:
            bbox = draw.textbbox((0, 0), line, font=tag_font)
            tag_line_heights.append(bbox[3] - bbox[1])
        total_tag_h = sum(tag_line_heights) + 6 * (len(tag_line_heights) - 1) if tag_line_heights else 0

        # Calculate total content height for vertical centering
        logo_h = logo.height if logo else 0
        divider_gap = 30  # space between logo and divider + divider and text
        tag_gap = 40  # space between CTA text and tagline
        content_h = logo_h + divider_gap + total_cta_h + tag_gap + total_tag_h
        # Position content block slightly below center
        content_top = (height - content_h) // 2 + int(height * 0.03)

        # Logo — fades in first, at top of content block
        if logo:
            logo_ease = _ease_out_cubic(min(t / 0.35, 1.0))
            logo_alpha = _ease_out_cubic(min(t / 0.3, 1.0))
            logo_x = (width - logo.width) // 2
            logo_y = content_top
            temp_logo = logo.copy()
            lo_arr = np.array(temp_logo)
            lo_arr[:, :, 3] = (lo_arr[:, :, 3].astype(np.float32) * logo_alpha).astype(np.uint8)
            temp_logo = Image.fromarray(lo_arr, "RGBA")
            frame.paste(temp_logo, (logo_x, logo_y), temp_logo)
            below_logo_y = logo_y + logo.height
        else:
            below_logo_y = content_top

        # Ornamental divider between logo and CTA text
        if show_divider:
            divider_y_px = below_logo_y + divider_gap // 2
            _draw_ornamental_divider(
                draw, width, height, accent_color,
                y_pos=divider_y_px / height, frame_t=t,
            )

        # CTA text — fade in, placed below divider
        cta_y = below_logo_y + divider_gap
        cta_alpha = int(255 * _ease_out_cubic(min(t / 0.35, 1.0)))
        cr, cg, cb = _hex_to_rgb(cta_color)
        for i, line in enumerate(cta_lines_m):
            lw = draw.textbbox((0, 0), line, font=cta_font)
            tw = lw[2] - lw[0]
            cx = (width - tw) // 2
            # Soft shadow
            draw.text((cx + 2, cta_y + 3), line, fill=(0, 0, 0, int(cta_alpha * 0.6)), font=cta_font)
            draw.text((cx, cta_y), line, fill=(cr, cg, cb, cta_alpha), font=cta_font)
            cta_y += cta_line_heights[i] + 14

        # Tagline — appears late, below CTA text
        tag_t = max(0, (t - 0.4) / 0.6)
        if tag_t > 0:
            tag_alpha = int(255 * _ease_out_cubic(min(tag_t / 0.35, 1.0)))
            tr, tg, tb = _hex_to_rgb(tagline_color)
            ty = cta_y + tag_gap - 14  # -14 to offset last line_spacing
            for line in tag_lines:
                bbox = draw.textbbox((0, 0), line, font=tag_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = (width - tw) // 2
                draw.text((tx, ty), line, fill=(tr, tg, tb, tag_alpha), font=tag_font)
                ty += th + 6

        rgb = Image.new("RGB", (width, height), (0, 0, 0))
        rgb.paste(frame, mask=frame.split()[3])
        frames.append(np.array(rgb))

    return frames


def render_placeholder_clip(
    prompt: str,
    duration: float,
    fps: int,
    width: int,
    height: int,
    *,
    bg_color: str = "#0a0a0a",
    text_color: str = "#555555",
    label_color: str = "#C49A3C",
    font_path: str | None = None,
) -> list[np.ndarray]:
    """Render a black placeholder for AI video, showing the prompt text.

    Used in --skip-ai test mode so you can preview storyboard flow
    without waiting for GPU inference.
    """
    num_frames = int(duration * fps)
    prompt_font = _get_font(font_path, 24)
    label_font = _get_font_bold(None, 18)
    frames = []

    for fi in range(num_frames):
        t = fi / max(num_frames - 1, 1)
        frame = Image.new("RGBA", (width, height), _hex_to_rgba(bg_color))
        draw = ImageDraw.Draw(frame)

        # Subtle scan line effect
        for y in range(0, height, 4):
            draw.line([(0, y), (width, y)], fill=(255, 255, 255, 6), width=1)

        # "AI VIDEO" label at top
        label = "[ AI VIDEO — PLACEHOLDER ]"
        label_ease = _ease_out_cubic(min(t / 0.3, 1.0))
        lr, lg, lb = _hex_to_rgb(label_color)
        bbox = draw.textbbox((0, 0), label, font=label_font)
        lw = bbox[2] - bbox[0]
        lx = (width - lw) // 2
        ly = int(height * 0.08)
        draw.text((lx, ly), label, fill=(lr, lg, lb, int(200 * label_ease)), font=label_font)

        # Prompt text in muted color, word-wrapped
        lines = _wrap_text(prompt, prompt_font, int(width * 0.85))
        pr, pg, pb = _hex_to_rgb(text_color)
        prompt_ease = _ease_out_cubic(min(max(t - 0.1, 0) / 0.4, 1.0))
        cy = int(height * 0.35)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=prompt_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (width - tw) // 2
            draw.text((tx, cy), line, fill=(pr, pg, pb, int(180 * prompt_ease)), font=prompt_font)
            cy += th + 8

        # Duration indicator at bottom
        dur_text = f"{duration:.1f}s"
        bbox = draw.textbbox((0, 0), dur_text, font=label_font)
        dw = bbox[2] - bbox[0]
        draw.text(
            ((width - dw) // 2, int(height * 0.88)),
            dur_text, fill=(lr, lg, lb, 120), font=label_font,
        )

        # Progress bar at very bottom
        bar_w = int(width * 0.6 * t)
        bar_x = int(width * 0.2)
        bar_y = int(height * 0.93)
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 3], fill=(lr, lg, lb, 80))

        rgb = Image.new("RGB", (width, height), (0, 0, 0))
        rgb.paste(frame, mask=frame.split()[3])
        frames.append(np.array(rgb))

    return frames


# ---------------------------------------------------------------------------
# Darken helper
# ---------------------------------------------------------------------------

def _darken_hex(hex_color: str, factor: float = 0.5) -> str:
    """Return a darker version of a hex color."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Transition helpers — blend between two frame sequences
# ---------------------------------------------------------------------------

def apply_crossfade(
    frames_a: list[np.ndarray],
    frames_b: list[np.ndarray],
    overlap_frames: int,
) -> list[np.ndarray]:
    """Crossfade the last N frames of A with the first N frames of B."""
    if overlap_frames <= 0:
        return frames_a + frames_b

    overlap = min(overlap_frames, len(frames_a), len(frames_b))
    result = list(frames_a[:-overlap])

    for i in range(overlap):
        t = (i + 1) / (overlap + 1)
        blended = (
            frames_a[len(frames_a) - overlap + i].astype(np.float32) * (1 - t)
            + frames_b[i].astype(np.float32) * t
        ).astype(np.uint8)
        result.append(blended)

    result.extend(frames_b[overlap:])
    return result


def apply_fade_to_black(frames: list[np.ndarray], fade_frames: int) -> list[np.ndarray]:
    """Fade the last N frames to black."""
    result = list(frames)
    n = min(fade_frames, len(result))
    for i in range(n):
        idx = len(result) - n + i
        t = (i + 1) / n  # reaches 1.0 on last frame
        result[idx] = (result[idx].astype(np.float32) * (1 - t)).astype(np.uint8)
    return result


def apply_fade_from_black(frames: list[np.ndarray], fade_frames: int) -> list[np.ndarray]:
    """Fade the first N frames from black."""
    result = list(frames)
    n = min(fade_frames, len(result))
    for i in range(n):
        t = (i + 1) / n  # reaches 1.0 on last fade frame
        result[i] = (result[i].astype(np.float32) * t).astype(np.uint8)
    return result


def apply_wipe(
    frames_a: list[np.ndarray],
    frames_b: list[np.ndarray],
    overlap_frames: int,
    direction: str = "left",
) -> list[np.ndarray]:
    """Wipe transition — A slides out while B slides in."""
    if overlap_frames <= 0:
        return frames_a + frames_b

    overlap = min(overlap_frames, len(frames_a), len(frames_b))
    result = list(frames_a[:-overlap])

    h, w = frames_a[0].shape[:2]
    for i in range(overlap):
        t = _ease_in_out_sine((i + 1) / (overlap + 1))
        fa = frames_a[len(frames_a) - overlap + i]
        fb = frames_b[i]
        blended = fa.copy()
        if direction == "left":
            cut = int(w * t)
            blended[:, :cut] = fb[:, :cut]
        elif direction == "right":
            cut = int(w * (1 - t))
            blended[:, cut:] = fb[:, cut:]
        elif direction == "up":
            cut = int(h * t)
            blended[:cut, :] = fb[:cut, :]
        else:  # down
            cut = int(h * (1 - t))
            blended[cut:, :] = fb[cut:, :]
        result.append(blended)

    result.extend(frames_b[overlap:])
    return result


# ---------------------------------------------------------------------------
# Video clip to frames helper
# ---------------------------------------------------------------------------

def video_to_frames(video_path: Path, fps: int) -> list[np.ndarray]:
    """Load an MP4 file and return its frames as numpy arrays."""
    from moviepy import VideoFileClip
    clip = VideoFileClip(str(video_path))
    frames = []
    for frame in clip.iter_frames(fps=fps, dtype="uint8"):
        frames.append(frame)
    clip.close()
    return frames


def frames_to_video(frames: list[np.ndarray], output_path: Path, fps: int, crf: int = 23) -> Path:
    """Write numpy frames to MP4 using imageio-ffmpeg."""
    import imageio
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(
        str(output_path),
        format="mp4",
        fps=fps,
        codec="libx264",
        output_params=["-crf", str(crf), "-pix_fmt", "yuv420p"],
    ) as writer:
        for frame in frames:
            writer.append_data(frame)
    return output_path


def add_text_overlay_to_frames(
    frames: list[np.ndarray],
    text: str,
    fps: int,
    *,
    animation: str = "fade_in_out",
    text_color: str = "#f7f2ea",
    font_size: int = 44,
    font_path: str | None = None,
    position: str = "bottom",
    shadow: bool = True,
) -> list[np.ndarray]:
    """Overlay animated text onto existing video frames."""
    if not text:
        return frames
    font = _get_font(font_path, font_size)
    h, w = frames[0].shape[:2]
    result = []
    num_frames = len(frames)

    for fi, frame in enumerate(frames):
        t = fi / max(num_frames - 1, 1)
        img = Image.fromarray(frame).convert("RGBA")
        img = _render_text_on_frame(
            img, text, font, text_color, position, animation,
            t, num_frames / fps, w, h, shadow=shadow,
        )
        rgb = Image.new("RGB", (w, h), (0, 0, 0))
        rgb.paste(img, mask=img.split()[3])
        result.append(np.array(rgb))

    return result
