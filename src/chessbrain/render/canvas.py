"""Canvas + image-loading primitives."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from chessbrain.settings import get_settings


def carousel_canvas() -> Image.Image:
    s = get_settings()
    w, h = s.carousel_size
    bg = s.brand["palette"]["bg_cream"]
    return Image.new("RGB", (w, h), bg)


def reel_canvas() -> Image.Image:
    s = get_settings()
    w, h = s.reel_size
    bg = s.brand["palette"]["bg_cream"]
    return Image.new("RGB", (w, h), bg)


def fit_to(img: Image.Image, target_w: int, target_h: int, *, mode: str = "cover") -> Image.Image:
    """Resize+crop (cover) or pad (contain) an image to (target_w, target_h)."""
    if mode == "cover":
        return ImageOps.fit(img, (target_w, target_h), method=Image.LANCZOS)
    if mode == "contain":
        c = img.copy()
        c.thumbnail((target_w, target_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(c, ((target_w - c.width) // 2, (target_h - c.height) // 2))
        return canvas
    raise ValueError(mode)


def open_rgba(path: Path) -> Image.Image:
    img = Image.open(path)
    return img.convert("RGBA")


def open_rgb(path: Path) -> Image.Image:
    img = Image.open(path)
    return img.convert("RGB")
