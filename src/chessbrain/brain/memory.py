"""Idea-log memory + similarity gate (the anti-repetition mechanism).

Every hook, slide line, mascot scene description, CTA line, image prompt, and
caption is logged here. Before any new candidate is accepted, we compare its
embedding to recent same-kind entries; if cosine similarity exceeds the
configured threshold, the candidate is rejected (caller can re-roll).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import numpy as np

from chessbrain.brain.db import connect, new_id, utc_now_iso
from chessbrain.embed import embed_one
from chessbrain.settings import get_settings


@dataclass
class IdeaRow:
    id: str
    kind: str
    value: str
    embedding: np.ndarray | None
    post_slug: str | None
    created_at: str


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())[:512]


def _vec_to_bytes(v: np.ndarray) -> bytes:
    return v.astype("<f4").tobytes()


def _bytes_to_vec(b: bytes | None) -> np.ndarray | None:
    if not b:
        return None
    return np.frombuffer(b, dtype="<f4")


def log_idea(
    kind: str,
    value: str,
    *,
    post_slug: str | None = None,
    content_type: str | None = None,
    embedding: np.ndarray | None = None,
) -> str:
    settings = get_settings()
    if embedding is None:
        try:
            embedding = embed_one(value)
        except Exception:
            embedding = None
    rid = new_id()
    with connect() as c:
        c.execute(
            """INSERT INTO idea_log
               (id, kind, value, norm_value, embedding, embed_model,
                post_slug, content_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                kind,
                value,
                _normalize(value),
                _vec_to_bytes(embedding) if embedding is not None else None,
                settings.runtime["embeddings"]["model"] if embedding is not None else None,
                post_slug,
                content_type,
                utc_now_iso(),
            ),
        )
    return rid


def log_many(
    items: Sequence[tuple[str, str]],
    *,
    post_slug: str | None = None,
    content_type: str | None = None,
) -> list[str]:
    """Log a batch of (kind, value) pairs."""
    return [
        log_idea(k, v, post_slug=post_slug, content_type=content_type) for k, v in items
    ]


def recent(kind: str, *, days: int = 90, limit: int = 500) -> list[IdeaRow]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as c:
        rows = c.execute(
            """SELECT id, kind, value, embedding, post_slug, created_at
               FROM idea_log WHERE kind = ? AND created_at >= ?
               ORDER BY created_at DESC LIMIT ?""",
            (kind, cutoff, limit),
        ).fetchall()
    return [
        IdeaRow(
            id=r["id"],
            kind=r["kind"],
            value=r["value"],
            embedding=_bytes_to_vec(r["embedding"]),
            post_slug=r["post_slug"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def exact_exists(kind: str, value: str) -> bool:
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM idea_log WHERE kind = ? AND norm_value = ? LIMIT 1",
            (kind, _normalize(value)),
        ).fetchone()
    return row is not None


def max_similarity(
    kind: str, candidate: str, *, days: int | None = None
) -> tuple[float, IdeaRow | None]:
    """Return (max cosine similarity, nearest row) against recent same-kind entries."""
    settings = get_settings()
    days = days if days is not None else settings.runtime["similarity_gate"]["lookback_days"]
    try:
        cand = embed_one(candidate)
    except Exception:
        return 0.0, None
    rows = recent(kind, days=days, limit=1000)
    rows = [r for r in rows if r.embedding is not None]
    if not rows:
        return 0.0, None
    M = np.stack([r.embedding for r in rows])
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    cv = cand / (np.linalg.norm(cand) + 1e-9)
    sims = M @ cv
    idx = int(np.argmax(sims))
    return float(sims[idx]), rows[idx]


def is_too_similar(kind: str, candidate: str, *, threshold: float | None = None) -> bool:
    settings = get_settings()
    threshold = threshold if threshold is not None else settings.runtime["similarity_gate"]["threshold"]
    if exact_exists(kind, candidate):
        return True
    sim, _ = max_similarity(kind, candidate)
    return sim >= threshold


def forbidden_block(
    kinds: Iterable[str], *, per_kind: int = 25, days: int | None = None
) -> str:
    """Format a compact 'AVOID THESE' string for the LLM prompt."""
    settings = get_settings()
    days = days if days is not None else settings.runtime["similarity_gate"]["lookback_days"]
    chunks: list[str] = []
    for k in kinds:
        rows = recent(k, days=days, limit=per_kind)
        if not rows:
            continue
        bullets = "\n".join(f"  - {r.value}" for r in rows[:per_kind])
        chunks.append(f"[{k.upper()} — already used, do NOT repeat or paraphrase]\n{bullets}")
    return "\n\n".join(chunks)
