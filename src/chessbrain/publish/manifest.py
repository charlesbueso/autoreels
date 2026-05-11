"""Daily / weekly HTML manifest — opens in browser to preview & copy captions."""
from __future__ import annotations

import html
import json
from datetime import date, timedelta
from pathlib import Path

from chessbrain.settings import get_settings


CSS = """
body { font-family: -apple-system, system-ui, sans-serif; background: #1a1a1a; color: #f7f2ea; margin: 0; padding: 24px; }
h1 { font-size: 28px; margin: 0 0 24px; color: #C49A3C; }
.day { margin-bottom: 32px; }
.day h2 { font-size: 22px; color: #E2C079; margin: 0 0 16px; }
.post { background: #2b2d31; border-radius: 16px; padding: 16px; margin-bottom: 16px; }
.post h3 { margin: 0 0 6px; font-size: 18px; }
.post .meta { color: #949BA4; font-size: 13px; margin-bottom: 12px; }
.thumbs { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px; }
.thumbs img { height: 220px; border-radius: 8px; }
.captions { margin-top: 12px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.caption { background: #1f2125; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.caption .label { color: #C49A3C; font-weight: 600; font-size: 11px; text-transform: uppercase; }
pre { white-space: pre-wrap; word-wrap: break-word; margin: 4px 0 0; font-family: inherit; }
"""


def _post_card(post_dir: Path) -> str:
    meta_p = post_dir / "meta.json"
    if not meta_p.exists():
        return ""
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    slides = sorted(post_dir.glob("*.png"))
    thumbs = "".join(f'<img src="{post_dir.name}/{p.name}" />' for p in slides)
    cap_blocks = []
    for label, key in [
        ("Instagram", "instagram"),
        ("TikTok", "tiktok"),
        ("X", "x"),
        ("Reddit", "reddit_title"),
        ("Facebook", "facebook"),
    ]:
        v = meta.get("captions", {}).get(key, "")
        cap_blocks.append(
            f'<div class="caption"><div class="label">{label}</div><pre>{html.escape(v)}</pre></div>'
        )
    return (
        f'<div class="post">'
        f'<h3>{html.escape(meta["hook"])}</h3>'
        f'<div class="meta">{meta["content_type"]} · {meta["slug"]}</div>'
        f'<div class="thumbs">{thumbs}</div>'
        f'<div class="captions">{"".join(cap_blocks)}</div>'
        f"</div>"
    )


def render_day(d: date) -> Path:
    """Render a manifest HTML for a single date directory."""
    s = get_settings()
    day_dir = s.output_dir / d.isoformat()
    if not day_dir.exists():
        raise FileNotFoundError(day_dir)
    cards = []
    for sub in sorted(day_dir.iterdir()):
        if sub.is_dir():
            cards.append(_post_card(sub))
    body = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>ChessBrain — {d.isoformat()}</title>"
        f"<style>{CSS}</style></head><body>"
        f"<h1>Chess Brain · {d.isoformat()}</h1>"
        f"{''.join(cards)}"
        f"</body></html>"
    )
    out = day_dir / "manifest.html"
    out.write_text(body, encoding="utf-8")
    return out


def render_week(start: date) -> Path:
    s = get_settings()
    sections = []
    for i in range(7):
        d = start + timedelta(days=i)
        day_dir = s.output_dir / d.isoformat()
        if not day_dir.exists():
            continue
        cards = []
        for sub in sorted(day_dir.iterdir()):
            if sub.is_dir():
                # for week view, image paths must be relative to the week file
                cards.append(_post_card_relative(sub, d))
        if cards:
            sections.append(
                f'<div class="day"><h2>{d.strftime("%A · %Y-%m-%d")}</h2>{"".join(cards)}</div>'
            )
    body = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>ChessBrain · week of {start.isoformat()}</title>"
        f"<style>{CSS}</style></head><body>"
        f"<h1>Chess Brain · week of {start.isoformat()}</h1>"
        f"{''.join(sections)}"
        f"</body></html>"
    )
    out = s.output_dir / f"manifest_week_{start.isoformat()}.html"
    out.write_text(body, encoding="utf-8")
    return out


def _post_card_relative(post_dir: Path, d: date) -> str:
    meta_p = post_dir / "meta.json"
    if not meta_p.exists():
        return ""
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    slides = sorted(post_dir.glob("*.png"))
    thumbs = "".join(f'<img src="{d.isoformat()}/{post_dir.name}/{p.name}" />' for p in slides)
    cap_blocks = []
    for label, key in [
        ("Instagram", "instagram"),
        ("TikTok", "tiktok"),
        ("X", "x"),
        ("Reddit", "reddit_title"),
    ]:
        v = meta.get("captions", {}).get(key, "")
        cap_blocks.append(
            f'<div class="caption"><div class="label">{label}</div><pre>{html.escape(v)}</pre></div>'
        )
    return (
        f'<div class="post">'
        f'<h3>{html.escape(meta["hook"])}</h3>'
        f'<div class="meta">{meta["content_type"]} · {meta["slug"]}</div>'
        f'<div class="thumbs">{thumbs}</div>'
        f'<div class="captions">{"".join(cap_blocks)}</div>'
        f"</div>"
    )
