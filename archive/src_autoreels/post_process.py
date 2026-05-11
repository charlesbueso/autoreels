"""Post-processing — upscale, overlay logo + text, stitch clips, encode final MP4."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from moviepy import VideoFileClip, CompositeVideoClip, ImageClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
import numpy as np

logger = logging.getLogger(__name__)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _make_text_image(
    text: str,
    width: int,
    font_size: int = 48,
    color: str = "#f7f2ea",
    bg_color: str | None = None,
    font_path: str | None = None,
    padding: int = 20,
) -> np.ndarray:
    """Render text to an RGBA numpy array using Pillow (more reliable than TextClip)."""
    if font_path:
        font = ImageFont.truetype(font_path, font_size)
    else:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    # Measure text
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Create image with padding
    img_w = min(tw + padding * 2, width)
    img_h = th + padding * 2

    if bg_color:
        bg = _hex_to_rgb(bg_color) + (180,)  # semi-transparent
    else:
        bg = (0, 0, 0, 0)

    img = Image.new("RGBA", (img_w, img_h), bg)
    draw = ImageDraw.Draw(img)

    # Center text
    x = (img_w - tw) // 2
    y = padding
    draw.text((x, y), text, fill=_hex_to_rgb(color) + (255,), font=font)

    return np.array(img)


def upscale_clip(clip: VideoFileClip, target_w: int, target_h: int) -> VideoFileClip:
    """Resize clip to target dimensions using Lanczos."""
    return clip.resized((target_w, target_h))


def add_logo_overlay(
    clip: VideoFileClip,
    logo_path: str | Path,
    position: str = "top-right",
    margin: int = 30,
    scale: float = 0.12,
) -> CompositeVideoClip:
    """Overlay a logo PNG onto the video."""
    logo_path = Path(logo_path)
    if not logo_path.exists():
        logger.warning("Logo not found at %s — skipping overlay", logo_path)
        return clip

    logo = Image.open(logo_path).convert("RGBA")
    target_w = int(clip.w * scale)
    ratio = target_w / logo.width
    target_h = int(logo.height * ratio)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    logo_arr = np.array(logo)
    logo_clip = ImageClip(logo_arr, is_mask=False, transparent=True).with_duration(clip.duration)

    if position == "top-right":
        pos = (clip.w - target_w - margin, margin)
    elif position == "top-left":
        pos = (margin, margin)
    elif position == "bottom-right":
        pos = (clip.w - target_w - margin, clip.h - target_h - margin)
    else:
        pos = (margin, clip.h - target_h - margin)

    logo_clip = logo_clip.with_position(pos)
    return CompositeVideoClip([clip, logo_clip])


def add_text_overlay(
    clip: VideoFileClip,
    cta_text: str,
    campaign: dict[str, Any],
    settings: dict[str, Any],
) -> CompositeVideoClip:
    """Add CTA text at the bottom of the video."""
    if not cta_text:
        return clip

    colors = campaign.get("brand", {}).get("colors", {})
    font_path = campaign.get("brand", {}).get("font")
    text_color = colors.get("secondary", "#f7f2ea")
    bg_color = colors.get("primary", "#16431c")

    text_img = _make_text_image(
        cta_text,
        width=clip.w,
        font_size=52,
        color=text_color,
        bg_color=bg_color,
        font_path=font_path,
    )

    text_clip = (
        ImageClip(text_img, is_mask=False, transparent=True)
        .with_duration(clip.duration)
        .with_position(("center", clip.h - text_img.shape[0] - 60))
    )

    return CompositeVideoClip([clip, text_clip])


def stitch_clips(clip_paths: list[Path], crossfade: float = 0.3) -> VideoFileClip:
    """Concatenate multiple clips with a short crossfade."""
    clips = [VideoFileClip(str(p)) for p in clip_paths]
    if len(clips) == 1:
        return clips[0]
    return concatenate_videoclips(clips, method="compose", padding=-crossfade)


def process_reel(
    clip_paths: list[Path],
    output_path: Path,
    campaign: dict[str, Any],
    settings: dict[str, Any],
    cta_text: str = "",
) -> Path:
    """Full post-processing pipeline: stitch → upscale → overlay → encode.

    Args:
        clip_paths: Raw clip files from video_gen.
        output_path: Final MP4 output path.
        campaign: Campaign config dict.
        settings: Global settings dict.

    Returns:
        Path to the final encoded MP4.
    """
    video_cfg = settings.get("video", {})
    target_w = video_cfg.get("width", 768)
    target_h = video_cfg.get("height", 1344)

    logger.info("Stitching %d clips", len(clip_paths))
    combined = stitch_clips(clip_paths)

    logger.info("Upscaling to %dx%d", target_w, target_h)
    combined = upscale_clip(combined, target_w, target_h)

    # Logo overlay
    from .campaign import ROOT_DIR
    logo_rel = campaign.get("brand", {}).get("logo", "")
    if logo_rel:
        logo_path = ROOT_DIR / logo_rel
        combined = add_logo_overlay(combined, logo_path)

    # Text overlay
    if cta_text:
        combined = add_text_overlay(combined, cta_text, campaign, settings)

    # Encode
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crf = video_cfg.get("crf", 23)
    fps = video_cfg.get("fps", 24)

    combined.write_videofile(
        str(output_path),
        fps=fps,
        codec=video_cfg.get("codec", "libx264"),
        audio=False,
        ffmpeg_params=["-crf", str(crf), "-pix_fmt", "yuv420p"],
        logger=None,
    )

    # Clean up moviepy clips
    combined.close()

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Reel saved: %s (%.1f MB)", output_path, file_size_mb)
    return output_path
