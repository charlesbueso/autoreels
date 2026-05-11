"""Embeddings client — defaults to OpenAI text-embedding-3-small.

Cached locally by SHA(text) in ``data/embed_cache.sqlite`` to avoid
re-embedding identical strings (e.g. when validating the same candidate
across multiple retries).
"""
from __future__ import annotations

import hashlib
import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np

from chessbrain.settings import get_settings


def _cache_path() -> Path:
    p = get_settings().data_dir / "embed_cache.sqlite"
    return p


def _ensure_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path())
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (sha TEXT PRIMARY KEY, model TEXT, vec BLOB)"
    )
    return conn


def _sha(text: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


@lru_cache(maxsize=1)
def _client():
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY missing — required for embeddings. "
            "Set it in .env.local."
        )
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


def embed_one(text: str) -> np.ndarray:
    settings = get_settings()
    model = settings.runtime["embeddings"]["model"]
    sha = _sha(text, model)
    with _ensure_cache() as conn:
        row = conn.execute("SELECT vec FROM cache WHERE sha = ?", (sha,)).fetchone()
        if row:
            return np.frombuffer(row[0], dtype="<f4")
        client = _client()
        resp = client.embeddings.create(model=model, input=text[:8000])
        vec = np.asarray(resp.data[0].embedding, dtype="<f4")
        conn.execute(
            "INSERT OR REPLACE INTO cache (sha, model, vec) VALUES (?, ?, ?)",
            (sha, model, vec.tobytes()),
        )
        conn.commit()
    return vec
