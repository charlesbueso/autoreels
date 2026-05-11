"""Download Lichess puzzle DB and ingest it into the local SQLite cache.

Usage:
    python -m scripts.download_lichess_puzzles           # full ingest
    python -m scripts.download_lichess_puzzles --limit 50000   # quick test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress

from chessbrain import puzzle
from chessbrain.settings import get_settings

URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N rows (for quick tests). Omit for full ingest.",
    )
    ap.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Use an already-downloaded file instead of re-downloading.",
    )
    args = ap.parse_args()

    s = get_settings()
    con = Console()

    if args.path:
        out = args.path
    else:
        out = s.data_dir / "lichess_db_puzzle.csv.zst"
        if not out.exists():
            con.print(f"[cyan]Downloading[/cyan] {URL}")
            with httpx.stream("GET", URL, follow_redirects=True, timeout=None) as r:
                total = int(r.headers.get("Content-Length", 0))
                with Progress() as prog:
                    tid = prog.add_task("download", total=total)
                    with out.open("wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
                            prog.update(tid, advance=len(chunk))
        else:
            con.print(f"[green]Already downloaded[/green] {out}")

    if args.limit:
        con.print(f"[yellow]Limiting ingest to {args.limit:,} rows (test mode).[/yellow]")

    n = puzzle.ingest_csv_path(out, limit=args.limit)
    con.print(f"[green]Ingested[/green] {n:,} puzzles. Stats: {puzzle.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
