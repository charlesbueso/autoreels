"""Lichess Puzzle DB ingest + querying.

CSV format (CC0): PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,
NbPlays,Themes,GameUrl,OpeningTags
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import zstandard as zstd

from chessbrain.settings import get_settings

log = logging.getLogger(__name__)

PUZZLE_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"


def db_path() -> Path:
    return get_settings().data_dir / "lichess_puzzles.sqlite"


def init() -> None:
    with sqlite3.connect(db_path()) as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS puzzles (
                id TEXT PRIMARY KEY,
                fen TEXT NOT NULL,
                moves TEXT NOT NULL,
                rating INTEGER NOT NULL,
                popularity INTEGER NOT NULL,
                nb_plays INTEGER NOT NULL,
                themes TEXT NOT NULL,
                opening TEXT,
                game_url TEXT
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_rating ON puzzles(rating)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_themes ON puzzles(themes)")


def ingest_csv_path(path: Path, limit: int | None = None, show_progress: bool = True) -> int:
    """Ingest puzzles from a CSV or .csv.zst file.

    Args:
        path: Path to the file.
        limit: Stop after this many rows (useful for quick tests).
        show_progress: Print a Rich progress bar while ingesting.
    """
    init()
    count = 0
    BATCH = 5000

    def _open(p: Path):
        if p.suffix == ".zst":
            f = open(p, "rb")
            dctx = zstd.ZstdDecompressor()
            return io.TextIOWrapper(dctx.stream_reader(f), encoding="utf-8")
        return open(p, "r", encoding="utf-8", newline="")

    if show_progress:
        try:
            from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, MofNCompleteColumn
            progress_ctx: Any = Progress(
                SpinnerColumn(),
                "[cyan]{task.description}",
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
            )
        except ImportError:
            progress_ctx = None
    else:
        progress_ctx = None

    with _open(path) as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        with sqlite3.connect(db_path()) as c:
            cur = c.cursor()
            batch: list = []

            def _flush():
                nonlocal count
                cur.executemany(
                    "INSERT OR IGNORE INTO puzzles VALUES (?,?,?,?,?,?,?,?,?)", batch
                )
                count += len(batch)
                batch.clear()

            def _process():
                for row in reader:
                    if len(row) < 8:
                        continue
                    pid, fen, moves, rating, _rd, pop, plays, themes = row[:8]
                    game_url = row[8] if len(row) > 8 else None
                    opening = row[9] if len(row) > 9 else None
                    batch.append(
                        (pid, fen, moves, int(rating), int(pop), int(plays), themes, opening, game_url)
                    )
                    if len(batch) >= BATCH:
                        _flush()
                        if progress_ctx is not None:
                            task and progress_ctx.update(task, advance=BATCH)
                        if limit and count >= limit:
                            break
                if batch:
                    _flush()
                c.commit()

            if progress_ctx is not None:
                with progress_ctx as prog:
                    task = prog.add_task(f"Ingesting {path.name}", total=limit)
                    _process()
                    prog.update(task, completed=count)
            else:
                task = None
                _process()

    log.info("Ingested %d puzzles from %s", count, path)
    return count


def pick(
    *,
    rating_min: int = 1300,
    rating_max: int = 1700,
    theme: str | None = None,
    exclude_ids: Iterable[str] = (),
    min_popularity: int = 80,
) -> dict | None:
    q = (
        "SELECT id, fen, moves, rating, popularity, themes, opening, game_url "
        "FROM puzzles WHERE rating BETWEEN ? AND ? AND popularity >= ?"
    )
    params: list = [rating_min, rating_max, min_popularity]
    if theme:
        q += " AND themes LIKE ?"
        params.append(f"%{theme}%")
    excl = list(exclude_ids)
    if excl:
        q += f" AND id NOT IN ({','.join('?' * len(excl))})"
        params.extend(excl)
    q += " ORDER BY RANDOM() LIMIT 1"
    with sqlite3.connect(db_path()) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(q, params).fetchone()
    return dict(row) if row else None


def stats() -> dict:
    with sqlite3.connect(db_path()) as c:
        n = c.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
    return {"count": n}
