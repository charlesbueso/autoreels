"""Recurring weekday-series state — picks the next param without repeating
within a configured lookback window.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from chessbrain.brain.db import connect, utc_now_iso
from chessbrain.settings import get_settings


@dataclass
class SeriesPick:
    series: str
    iteration: int
    param: Any            # str or dict, depends on series


def _load_state(name: str) -> tuple[int, list[dict[str, Any]]]:
    with connect() as c:
        row = c.execute(
            "SELECT last_index, used_params FROM recurring_series WHERE name = ?", (name,)
        ).fetchone()
    if row is None:
        return -1, []
    return row["last_index"], json.loads(row["used_params"] or "[]")


def _save_state(name: str, last_index: int, used_params: list[dict[str, Any]]) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO recurring_series (name, last_index, used_params, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 last_index = excluded.last_index,
                 used_params = excluded.used_params,
                 updated_at = excluded.updated_at""",
            (name, last_index, json.dumps(used_params), utc_now_iso()),
        )


def pick_next(name: str, *, dry_run: bool = False) -> SeriesPick:
    """Pick the next param for a series, honoring rotation_floor_weeks."""
    settings = get_settings()
    spec = settings.series.get(name)
    if not spec:
        raise KeyError(f"Unknown series: {name}")
    params: list[Any] = spec["params"]
    floor_weeks: int = int(spec.get("rotation_floor_weeks", 8))

    last_index, used = _load_state(name)
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=floor_weeks)
    recently_used: set[int] = set()
    for u in used:
        try:
            ts = datetime.fromisoformat(u["used_at"])
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            recently_used.add(int(u["index"]))

    available = [i for i in range(len(params)) if i not in recently_used]
    if not available:
        # Everything has been used recently — fall back to least-recently-used.
        available = list(range(len(params)))

    # Prefer indices we haven't used at all over rotated ones.
    never_used = [i for i in available if not any(u["index"] == i for u in used)]
    pool = never_used or available
    # Avoid identical-to-last when possible.
    if len(pool) > 1 and last_index in pool:
        pool = [i for i in pool if i != last_index]

    idx = random.choice(pool)
    pick = SeriesPick(series=name, iteration=idx, param=params[idx])

    if not dry_run:
        used.append({"index": idx, "used_at": utc_now_iso()})
        # Trim very old history.
        used = used[-200:]
        _save_state(name, idx, used)

    return pick
