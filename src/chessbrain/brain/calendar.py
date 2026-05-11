"""Calendar planner — populates ``calendar`` rows N days ahead from the
weekday grid in ``config/calendar.yaml`` and the recurring-series engine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from chessbrain.brain import series as series_mod
from chessbrain.brain.db import connect, new_id, utc_now_iso
from chessbrain.settings import get_settings

WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]


@dataclass
class CalendarSlot:
    id: str
    date: str
    slot: int
    weekday: str
    content_type: str
    series: str | None
    series_param: Any
    status: str
    post_slug: str | None


def _row_to_slot(row) -> CalendarSlot:
    return CalendarSlot(
        id=row["id"],
        date=row["date"],
        slot=row["slot"],
        weekday=row["weekday"],
        content_type=row["content_type"],
        series=row["series"],
        series_param=json.loads(row["series_param"]) if row["series_param"] else None,
        status=row["status"],
        post_slug=row["post_slug"],
    )


def plan_days(start: date, days: int) -> list[CalendarSlot]:
    """Insert calendar rows for [start, start + days). Idempotent (skips
    rows that already exist for a given (date, slot)).
    """
    settings = get_settings()
    grid = settings.calendar_grid
    now = utc_now_iso()
    inserted: list[CalendarSlot] = []

    # Phase 1: figure out which (date, slot) pairs are missing — short read txn.
    missing: list[tuple[date, str, int, dict]] = []
    with connect() as c:
        for i in range(days):
            d = start + timedelta(days=i)
            wd = WEEKDAY_NAMES[d.weekday()]
            row_grid = grid.get(wd, [])
            for slot_idx, slot_def in enumerate(row_grid):
                exists = c.execute(
                    "SELECT id FROM calendar WHERE date = ? AND slot = ?",
                    (d.isoformat(), slot_idx),
                ).fetchone()
                if not exists:
                    missing.append((d, wd, slot_idx, slot_def))

    # Phase 2: resolve series picks (each opens its own write txn). No outer
    # connection held → no self-deadlock.
    resolved: list[tuple[date, str, int, str, str | None, Any]] = []
    for d, wd, slot_idx, slot_def in missing:
        content_type = slot_def["type"]
        series_name = slot_def.get("series")
        series_param: Any = None
        if series_name:
            pick = series_mod.pick_next(series_name)
            series_param = pick.param
        resolved.append((d, wd, slot_idx, content_type, series_name, series_param))

    # Phase 3: bulk insert.
    with connect() as c:
        for d, wd, slot_idx, content_type, series_name, series_param in resolved:
            rid = new_id()
            c.execute(
                """INSERT INTO calendar
                   (id, date, slot, weekday, content_type, series, series_param,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)""",
                (
                    rid,
                    d.isoformat(),
                    slot_idx,
                    wd,
                    content_type,
                    series_name,
                    json.dumps(series_param) if series_param is not None else None,
                    now,
                    now,
                ),
            )
            inserted.append(
                CalendarSlot(
                    id=rid,
                    date=d.isoformat(),
                    slot=slot_idx,
                    weekday=wd,
                    content_type=content_type,
                    series=series_name,
                    series_param=series_param,
                    status="planned",
                    post_slug=None,
                )
            )
    return inserted


def list_slots(
    start: date | None = None,
    days: int = 14,
    status: str | None = None,
) -> list[CalendarSlot]:
    start = start or date.today()
    end = start + timedelta(days=days)
    q = "SELECT * FROM calendar WHERE date >= ? AND date < ?"
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY date, slot"
    with connect() as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_slot(r) for r in rows]


def get_slot(d: date, slot_idx: int) -> CalendarSlot | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM calendar WHERE date = ? AND slot = ?",
            (d.isoformat(), slot_idx),
        ).fetchone()
    return _row_to_slot(row) if row else None


def update_status(slot_id: str, status: str, *, post_slug: str | None = None) -> None:
    with connect() as c:
        if post_slug is not None:
            c.execute(
                "UPDATE calendar SET status = ?, post_slug = ?, updated_at = ? WHERE id = ?",
                (status, post_slug, utc_now_iso(), slot_id),
            )
        else:
            c.execute(
                "UPDATE calendar SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now_iso(), slot_id),
            )


def edit_slot(d: date, slot_idx: int, **changes: Any) -> CalendarSlot | None:
    """Override content_type / series / series_param for a planned slot."""
    if not changes:
        return get_slot(d, slot_idx)
    fields = []
    params: list[Any] = []
    for k, v in changes.items():
        if k == "series_param":
            fields.append("series_param = ?")
            params.append(json.dumps(v) if v is not None else None)
        elif k in {"content_type", "series", "status"}:
            fields.append(f"{k} = ?")
            params.append(v)
    fields.append("updated_at = ?")
    params.append(utc_now_iso())
    params.extend([d.isoformat(), slot_idx])
    with connect() as c:
        c.execute(
            f"UPDATE calendar SET {', '.join(fields)} WHERE date = ? AND slot = ?",
            params,
        )
    return get_slot(d, slot_idx)
