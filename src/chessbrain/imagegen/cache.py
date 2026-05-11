"""SHA-keyed image cache backed by ``assets`` table + ``data/image_cache/``."""
from __future__ import annotations

import hashlib
from pathlib import Path

from chessbrain.brain.db import connect, utc_now_iso
from chessbrain.settings import get_settings


def cache_key(model: str, prompt: str, seed: int | None, refs: list[Path]) -> str:
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(b"\x00")
    h.update(prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(seed if seed is not None else "").encode())
    for r in refs:
        h.update(b"\x00")
        try:
            h.update(Path(r).read_bytes())
        except Exception:
            h.update(str(r).encode())
    return h.hexdigest()


def cache_dir() -> Path:
    d = get_settings().image_cache_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def lookup(sha: str) -> Path | None:
    with connect() as c:
        row = c.execute("SELECT path FROM assets WHERE sha = ?", (sha,)).fetchone()
    if not row:
        return None
    p = Path(row["path"])
    return p if p.exists() else None


def store(
    *,
    sha: str,
    path: Path,
    model: str,
    prompt: str,
    seed: int | None,
    cost_usd: float,
    kind: str = "image",
) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO assets (sha, kind, model, prompt, seed, path, cost_usd, reuse_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(sha) DO UPDATE SET reuse_count = reuse_count + 1""",
            (sha, kind, model, prompt, seed, str(path), cost_usd, utc_now_iso()),
        )
