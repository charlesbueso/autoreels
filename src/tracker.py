"""Tracker — SQLite-backed state for reels, segments, and clip library."""

from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    reel_id TEXT PRIMARY KEY,
    campaign TEXT NOT NULL,
    theme TEXT NOT NULL,
    prompt TEXT NOT NULL,
    cta_text TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    attempt INTEGER DEFAULT 1,
    file_path TEXT,
    storyboard_json TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    fb_video_id TEXT,
    ig_media_id TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS clip_library (
    clip_id TEXT PRIMARY KEY,
    campaign TEXT NOT NULL,
    theme TEXT,
    prompt TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_reel_id TEXT,
    source_segment_index INTEGER,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    width INTEGER,
    height INTEGER,
    duration_sec REAL,
    fps INTEGER,
    created_at TEXT NOT NULL
);
"""


def init_db(db_path: Path | None = None) -> None:
    """Initialize the tracker database."""
    global _DB_PATH, _conn
    if db_path is None:
        from .campaign import ROOT_DIR
        db_path = ROOT_DIR / "autoreels.db"
    _DB_PATH = db_path
    _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    for stmt in SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            _conn.execute(stmt)
    _conn.commit()

    # Migrate: add storyboard_json column if missing
    _migrate_add_column("reels", "storyboard_json", "TEXT")

    logger.info("Tracker DB initialized at %s", _DB_PATH)


def _migrate_add_column(table: str, column: str, col_type: str) -> None:
    """Add a column if it doesn't exist (SQLite migration helper)."""
    conn = _get_conn()
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
        logger.info("Migrated: added %s.%s", table, column)


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        init_db()
    return _conn


# ---------------------------------------------------------------------------
# Reels CRUD
# ---------------------------------------------------------------------------

def create_reel(
    reel_id: str,
    campaign: str,
    theme: str,
    prompt: str,
    cta_text: str,
    file_path: str,
    storyboard: dict | None = None,
) -> None:
    conn = _get_conn()
    sb_json = json.dumps(storyboard) if storyboard else None
    conn.execute(
        """INSERT INTO reels
           (reel_id, campaign, theme, prompt, cta_text, file_path, storyboard_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (reel_id, campaign, theme, prompt, cta_text, file_path, sb_json,
         datetime.now().isoformat()),
    )
    conn.commit()


def update_reel_status(reel_id: str, status: str, **kwargs: Any) -> None:
    conn = _get_conn()
    sets = ["status = ?"]
    vals: list[Any] = [status]

    if status in ("approved", "approved_local"):
        sets.append("approved_at = ?")
        vals.append(datetime.now().isoformat())

    for key in ("fb_video_id", "ig_media_id", "error", "file_path", "attempt",
                "storyboard_json"):
        if key in kwargs:
            sets.append(f"{key} = ?")
            vals.append(kwargs[key])

    vals.append(reel_id)
    conn.execute(f"UPDATE reels SET {', '.join(sets)} WHERE reel_id = ?", vals)
    conn.commit()


def update_reel_storyboard(reel_id: str, storyboard: dict) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE reels SET storyboard_json = ? WHERE reel_id = ?",
        (json.dumps(storyboard), reel_id),
    )
    conn.commit()


def get_reel(reel_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM reels WHERE reel_id = ?", (reel_id,)).fetchone()
    return dict(row) if row else None


def get_reel_storyboard(reel_id: str) -> dict | None:
    reel = get_reel(reel_id)
    if reel and reel.get("storyboard_json"):
        return json.loads(reel["storyboard_json"])
    return None


def get_today_reels(campaign: str) -> list[dict]:
    conn = _get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM reels WHERE campaign = ? AND created_at LIKE ?",
        (campaign, f"{today}%"),
    ).fetchall()
    return [dict(r) for r in rows]


def get_pending_reels(campaign: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM reels WHERE campaign = ? AND status = 'pending'",
        (campaign,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_pending_reels() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM reels WHERE status = 'pending'",
    ).fetchall()
    return [dict(r) for r in rows]


def delete_reel(reel_id: str) -> None:
    """Delete a reel record and its files."""
    reel = get_reel(reel_id)
    if reel:
        fp = Path(reel["file_path"]) if reel.get("file_path") else None
        if fp and fp.exists():
            fp.unlink()
        if fp:
            for seg_file in fp.parent.glob(f"{reel_id}_seg*.mp4"):
                seg_file.unlink()
    conn = _get_conn()
    conn.execute("DELETE FROM reels WHERE reel_id = ?", (reel_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Clip Library
# ---------------------------------------------------------------------------

def save_clip_to_library(
    clip_id: str,
    campaign: str,
    prompt: str,
    file_path: str,
    *,
    theme: str = "",
    source_reel_id: str = "",
    source_segment_index: int = -1,
    tags: str = "",
    notes: str = "",
    width: int = 0,
    height: int = 0,
    duration_sec: float = 0,
    fps: int = 16,
) -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO clip_library
           (clip_id, campaign, theme, prompt, file_path, source_reel_id,
            source_segment_index, tags, notes, width, height, duration_sec, fps, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (clip_id, campaign, theme, prompt, file_path, source_reel_id,
         source_segment_index, tags, notes, width, height, duration_sec, fps,
         datetime.now().isoformat()),
    )
    conn.commit()


def get_library_clips(campaign: str = "") -> list[dict]:
    conn = _get_conn()
    if campaign:
        rows = conn.execute(
            "SELECT * FROM clip_library WHERE campaign = ? ORDER BY created_at DESC",
            (campaign,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clip_library ORDER BY created_at DESC",
        ).fetchall()
    return [dict(r) for r in rows]


def get_library_clip(clip_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM clip_library WHERE clip_id = ?", (clip_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_library_clip(clip_id: str) -> None:
    clip = get_library_clip(clip_id)
    if clip:
        fp = Path(clip["file_path"])
        if fp.exists():
            fp.unlink()
    conn = _get_conn()
    conn.execute("DELETE FROM clip_library WHERE clip_id = ?", (clip_id,))
    conn.commit()


def search_library_clips(
    campaign: str = "",
    theme: str = "",
    tags: str = "",
) -> list[dict]:
    conn = _get_conn()
    conditions = []
    params: list[str] = []
    if campaign:
        conditions.append("campaign = ?")
        params.append(campaign)
    if theme:
        conditions.append("theme LIKE ?")
        params.append(f"%{theme}%")
    if tags:
        conditions.append("tags LIKE ?")
        params.append(f"%{tags}%")
    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"SELECT * FROM clip_library WHERE {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]
