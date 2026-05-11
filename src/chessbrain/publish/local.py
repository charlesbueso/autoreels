"""Save a generated post (slides + caption + meta) to ``output/YYYY-MM-DD/{slug}/``."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Sequence

from PIL import Image

from chessbrain.caption import CaptionSet
from chessbrain.content_types.base import PostPlan
from chessbrain.settings import get_settings


def post_dir(d: date | str, slug: str) -> Path:
    s = get_settings()
    d_str = d.isoformat() if isinstance(d, date) else d
    p = s.output_dir / d_str / slug
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_post(
    *,
    d: date | str,
    plan: PostPlan,
    slides: Sequence[Image.Image],
    captions: CaptionSet,
) -> Path:
    out = post_dir(d, plan.slug)
    paths: list[str] = []
    for i, im in enumerate(slides, start=1):
        p = out / f"{i:02d}.png"
        im.save(p, format="PNG", optimize=True)
        paths.append(str(p))

    # caption.md
    cap_md = out / "caption.md"
    cap_md.write_text(_render_caption_md(plan, captions), encoding="utf-8")

    # meta.json
    (out / "meta.json").write_text(
        json.dumps(
            {
                "slug": plan.slug,
                "content_type": plan.content_type,
                "hook": plan.hook,
                "summary": plan.summary,
                "badge": plan.badge,
                "series": plan.series,
                "series_param": plan.series_param,
                "slides": paths,
                "captions": captions.model_dump(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return out


def _render_caption_md(plan: PostPlan, c: CaptionSet) -> str:
    return (
        f"# {plan.hook}\n\n"
        f"**Type:** {plan.content_type}\n\n"
        "## Instagram\n```\n" + c.instagram + "\n```\n\n"
        "## TikTok\n```\n" + c.tiktok + "\n```\n\n"
        "## X / Twitter\n```\n" + c.x + "\n```\n\n"
        "## Reddit\n"
        "**Title:** " + c.reddit_title + "\n\n"
        "**Body:**\n```\n" + c.reddit_body + "\n```\n\n"
        "## YouTube Shorts\n```\n" + c.youtube_shorts + "\n```\n\n"
        "## Facebook\n```\n" + c.facebook + "\n```\n"
    )
