"""SQLite schema + connection helpers for the marketing brain.

Schema is intentionally Supabase-mirror-ready (UUID-friendly text PKs,
``created_at``/``updated_at`` timestamps, ``synced_at`` for future sync).
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from chessbrain.settings import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar (
    id              TEXT PRIMARY KEY,
    date            TEXT NOT NULL,        -- YYYY-MM-DD
    slot            INTEGER NOT NULL,     -- 0,1,2
    weekday         TEXT NOT NULL,        -- monday..sunday
    content_type    TEXT NOT NULL,
    series          TEXT,                 -- nullable
    series_param    TEXT,                 -- chosen param value (json)
    status          TEXT NOT NULL DEFAULT 'planned',
    post_slug       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    synced_at       TEXT,
    UNIQUE(date, slot)
);

CREATE TABLE IF NOT EXISTS posts (
    slug            TEXT PRIMARY KEY,
    calendar_id     TEXT NOT NULL,
    date            TEXT NOT NULL,
    slot            INTEGER NOT NULL,
    content_type    TEXT NOT NULL,
    hook            TEXT,
    summary         TEXT,
    num_slides      INTEGER NOT NULL DEFAULT 0,
    paths_json      TEXT,                 -- list of slide paths
    caption_json    TEXT,                 -- platform → caption
    plan_json       TEXT,                 -- full PostPlan dump
    status          TEXT NOT NULL DEFAULT 'ready',
    posted_at_json  TEXT,                 -- platform → ISO ts
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    synced_at       TEXT,
    FOREIGN KEY(calendar_id) REFERENCES calendar(id)
);

CREATE TABLE IF NOT EXISTS idea_log (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,        -- hook|slide_line|scene|cta|image_prompt|caption|seed
    value           TEXT NOT NULL,
    norm_value      TEXT NOT NULL,        -- lowercased / stripped for exact-match dedup
    embedding       BLOB,                 -- float32 LE bytes (1536 dim)
    embed_model     TEXT,
    post_slug       TEXT,
    content_type    TEXT,
    created_at      TEXT NOT NULL,
    synced_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_idea_log_kind_created ON idea_log(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_idea_log_norm ON idea_log(kind, norm_value);

CREATE TABLE IF NOT EXISTS recurring_series (
    name            TEXT PRIMARY KEY,
    last_index      INTEGER NOT NULL DEFAULT -1,
    used_params     TEXT NOT NULL DEFAULT '[]',  -- json list of {param, used_at}
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    sha             TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,        -- image|board|mock|composite
    model           TEXT,
    prompt          TEXT,
    seed            INTEGER,
    path            TEXT NOT NULL,
    cost_usd        REAL DEFAULT 0,
    reuse_count     INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spend_log (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    units           REAL NOT NULL,
    cost_usd        REAL NOT NULL,
    post_slug       TEXT,
    created_at      TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


def db_path() -> Path:
    return get_settings().data_dir / "brain.sqlite"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    with connect() as c:
        c.executescript(SCHEMA)
