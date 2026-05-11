"""Visual effects: drop shadow, paper grain, vignette, rounded mask."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def round_corners(img: Image.Image, radius: int) -> Image.Image:
    img = img.convert("RGBA")
    mask = rounded_mask(img.size, radius)
    img.putalpha(mask)
    return img


def drop_shadow(img: Image.Image, *, offset: tuple[int, int] = (0, 12), blur: int = 24, opacity: float = 0.25) -> Image.Image:
    """Return a new RGBA image of original size + padding containing img + shadow underneath."""
    pad = blur * 2 + max(abs(offset[0]), abs(offset[1])) + 8
    base = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    alpha = img.split()[-1] if img.mode == "RGBA" else Image.new("L", img.size, 255)
    sh_mask = Image.new("L", base.size, 0)
    sh_mask.paste(alpha, (pad + offset[0], pad + offset[1]))
    sh_mask = sh_mask.filter(ImageFilter.GaussianBlur(radius=blur))
    shadow_color = Image.new("RGBA", base.size, (0, 0, 0, int(255 * opacity)))
    shadow_color.putalpha(sh_mask)
    base = Image.alpha_composite(base, shadow_color)
    base.paste(img, (pad, pad), img if img.mode == "RGBA" else None)
    return base


def add_paper_grain(img: Image.Image, *, intensity: int = 10, seed: int = 0) -> Image.Image:
    rng = random.Random(seed)
    noise = Image.new("L", img.size)
    pixels = noise.load()
    for y in range(img.height):
        for x in range(img.width):
            pixels[x, y] = 128 + rng.randint(-intensity, intensity)
    noise = noise.filter(ImageFilter.GaussianBlur(radius=0.5))
    grain = Image.merge("RGB", (noise, noise, noise)).convert("RGBA")
    grain.putalpha(40)
    out = img.convert("RGBA")
    out = Image.alpha_composite(out, grain)
    return out.convert("RGB")


def vignette(img: Image.Image, *, strength: float = 0.4) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((-w // 4, -h // 4, w + w // 4, h + h // 4), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 6))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, dark, ImageOps.invert(mask).point(lambda v: int(v * strength)))


def paste_with_shadow(
    base: Image.Image, fg: Image.Image, xy: tuple[int, int], *, shadow_blur: int = 24, opacity: float = 0.25
) -> Image.Image:
    """Paste fg onto base with a drop shadow centered on xy (xy is fg top-left, pre-shadow)."""
    sh = drop_shadow(fg.convert("RGBA"), blur=shadow_blur, opacity=opacity)
    pad = (sh.width - fg.width) // 2
    base_rgba = base.convert("RGBA")
    base_rgba.alpha_composite(sh, (xy[0] - pad, xy[1] - pad))
    return base_rgba.convert("RGB")
