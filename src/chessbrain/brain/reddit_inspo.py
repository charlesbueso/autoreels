"""Fetch chess memes from Reddit via OAuth.

Two modes:
- ``fetch_inspiration_titles()`` — titles only (idea seeds for our LLM).
- ``fetch_top_meme()`` — downloads one top meme image directly so we can
  republish it. Use only with proper attribution.

Auth uses the "script" app flow with client credentials. Set in .env:
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET
    REDDIT_USERNAME   (optional — only needed for >60 req/min)
    REDDIT_PASSWORD   (optional)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx

from chessbrain.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "python:chessbrain-content:0.1 (by /u/chessbrain_coach)"
SUBREDDITS = ("chessmemes", "AnarchyChess", "chess")
DEFAULT_LIMIT = 50
MIN_SCORE = 300
POOL_TTL_SECONDS = 6 * 3600

_NICHE_BLOCKLIST = (
    "magnus", "hikaru", "fischer", "kasparov", "ding", "nepo", "carlsen",
    "anish", "gukesh", "pragg", "alireza", "fabi", "wesley",
    "world championship", "candidates", "tournament",
    "elo", "rating", "fide",
    "engine", "stockfish", "leela",
    "[oc]", "[meme]",
)

_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}


# ----- auth ---------------------------------------------------------------

def _get_token() -> str | None:
    if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expires_at"] - 60:
        return _TOKEN_CACHE["token"]

    cid = os.getenv("REDDIT_CLIENT_ID")
    csec = os.getenv("REDDIT_CLIENT_SECRET")
    if not cid or not csec:
        log.warning("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET missing")
        return None

    user = os.getenv("REDDIT_USERNAME")
    pw = os.getenv("REDDIT_PASSWORD")
    if user and pw:
        data = {"grant_type": "password", "username": user, "password": pw}
    else:
        data = {"grant_type": "client_credentials"}

    try:
        r = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            data=data,
            auth=(cid, csec),
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        r.raise_for_status()
        blob = r.json()
    except Exception as exc:
        log.warning("reddit auth failed: %s", exc)
        return None

    tok = blob.get("access_token")
    expires_in = int(blob.get("expires_in", 3600))
    _TOKEN_CACHE["token"] = tok
    _TOKEN_CACHE["expires_at"] = time.time() + expires_in
    return tok


# ----- caches -------------------------------------------------------------

def _used_path() -> Path:
    return get_settings().data_dir / "reddit_inspo_used.json"


def _pool_path() -> Path:
    return get_settings().data_dir / "reddit_pool.json"


def _meme_image_dir() -> Path:
    p = get_settings().data_dir / "reddit_memes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_used() -> set[str]:
    p = _used_path()
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except Exception:
        return set()


def _save_used(used: Iterable[str]) -> None:
    p = _used_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(used)))


def _load_pool(period: str) -> list[dict] | None:
    p = _pool_path()
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text())
    except Exception:
        return None
    if blob.get("period") != period:
        return None
    if time.time() - blob.get("fetched_at", 0) > POOL_TTL_SECONDS:
        return None
    return blob.get("posts", [])


def _save_pool(period: str, posts: list[dict]) -> None:
    p = _pool_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "period": period,
        "fetched_at": time.time(),
        "posts": posts,
    }))


# ----- fetching -----------------------------------------------------------

def _fetch_subreddit(name: str, *, period: str, limit: int, token: str) -> list[dict]:
    url = f"https://oauth.reddit.com/r/{name}/top"
    params = {"t": period, "limit": str(limit), "raw_json": "1"}
    headers = {"User-Agent": USER_AGENT, "Authorization": f"bearer {token}"}
    try:
        r = httpx.get(url, params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("reddit fetch failed for r/%s: %s", name, exc)
        return []
    return [c.get("data", {}) for c in data.get("data", {}).get("children", [])]


def _is_simple_relatable(title: str) -> bool:
    t = title.lower().strip()
    if len(t) > 140 or len(t) < 12:
        return False
    if any(b in t for b in _NICHE_BLOCKLIST):
        return False
    if t.count('"') >= 2 and len(t.split()) < 8:
        return False
    return True


def _is_image_post(post: dict) -> bool:
    if post.get("is_video") or post.get("is_self"):
        return False
    url = (post.get("url_overridden_by_dest") or post.get("url") or "").lower()
    return url.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _image_url(post: dict) -> str | None:
    previews = post.get("preview", {}).get("images", [])
    if previews:
        src = previews[0].get("source", {}).get("url")
        if src:
            return src
    return post.get("url_overridden_by_dest") or post.get("url")


def _build_pool(period: str) -> list[dict]:
    cached = _load_pool(period)
    if cached is not None:
        log.info("reddit pool: cached (%d posts)", len(cached))
        return cached

    token = _get_token()
    if not token:
        return []

    posts: list[dict] = []
    for idx, sub in enumerate(SUBREDDITS):
        if idx > 0:
            time.sleep(1.0)
        for post in _fetch_subreddit(sub, period=period, limit=DEFAULT_LIMIT, token=token):
            pid = post.get("id")
            title = post.get("title", "")
            score = int(post.get("score", 0))
            if not pid or not title:
                continue
            if post.get("over_18") or post.get("stickied"):
                continue
            if score < MIN_SCORE:
                continue
            posts.append({
                "id": pid,
                "subreddit": sub,
                "title": title,
                "score": score,
                "author": post.get("author"),
                "permalink": f"https://reddit.com{post.get('permalink', '')}",
                "image_url": _image_url(post) if _is_image_post(post) else None,
            })

    if posts:
        _save_pool(period, posts)
    return posts


# ----- public API ---------------------------------------------------------

def fetch_inspiration_titles(*, n: int = 12, period: str = "week",
                             skip_used: bool = True) -> list[str]:
    used = _load_used() if skip_used else set()
    pool = [p for p in _build_pool(period) if p["id"] not in used]
    pool = [p for p in pool if _is_simple_relatable(p["title"])]
    if not pool:
        return []
    pool.sort(key=lambda x: -x["score"])
    picked = pool[:n]
    if skip_used:
        used.update(p["id"] for p in picked)
        _save_used(used)
    return [p["title"] for p in picked]


@dataclass
class RedditMeme:
    id: str
    title: str
    author: str
    subreddit: str
    permalink: str
    image_path: Path

    @property
    def attribution(self) -> str:
        return f"via u/{self.author} on r/{self.subreddit}"


def _download_image(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        with httpx.stream("GET", url, headers={"User-Agent": USER_AGENT},
                          timeout=30.0, follow_redirects=True) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        return True
    except Exception as exc:
        log.warning("reddit image download failed (%s): %s", url, exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def fetch_top_meme(*, period: str = "week", skip_used: bool = True) -> RedditMeme | None:
    """Return one fresh, image-bearing meme post + downloaded image path."""
    used = _load_used() if skip_used else set()
    pool = [p for p in _build_pool(period)
            if p["id"] not in used and p.get("image_url")
            and _is_simple_relatable(p["title"])]
    if not pool:
        log.info("reddit: no fresh image memes available")
        return None
    pool.sort(key=lambda x: -x["score"])

    for post in pool:
        url = post["image_url"]
        ext = ".jpg"
        for cand in (".png", ".jpeg", ".webp", ".jpg"):
            if cand in url.lower():
                ext = cand if cand != ".jpeg" else ".jpg"
                break
        dest = _meme_image_dir() / f"{post['id']}{ext}"
        if not _download_image(url, dest):
            continue
        if skip_used:
            used.add(post["id"])
            _save_used(used)
        return RedditMeme(
            id=post["id"],
            title=post["title"],
            author=post.get("author") or "unknown",
            subreddit=post["subreddit"],
            permalink=post["permalink"],
            image_path=dest,
        )
    return None
