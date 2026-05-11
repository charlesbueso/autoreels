"""Typer CLI: chessbrain ..."""
from __future__ import annotations

import json
import webbrowser
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from chessbrain.brain import calendar as cal_mod
from chessbrain.brain import memory
from chessbrain.brain.db import connect, init_db
from chessbrain.pipeline import generate_one_post
from chessbrain.publish import manifest
from chessbrain.settings import get_settings

app = typer.Typer(help="Chess Brain content engine.", no_args_is_help=True)
calendar_app = typer.Typer(help="Inspect / edit the planned calendar.")
brain_app = typer.Typer(help="Inspect the marketing-brain memory.")
puzzles_app = typer.Typer(help="Lichess puzzle DB management.")
imagegen_app = typer.Typer(help="Image generation utilities.")
app.add_typer(calendar_app, name="calendar")
app.add_typer(brain_app, name="brain")
app.add_typer(puzzles_app, name="puzzles")
app.add_typer(imagegen_app, name="imagegen")

con = Console()


@app.command()
def init() -> None:
    """Initialize SQLite databases and required directories."""
    s = get_settings()
    init_db()
    (s.assets_dir / "mascot").mkdir(parents=True, exist_ok=True)
    (s.assets_dir / "logos").mkdir(parents=True, exist_ok=True)
    (s.output_dir).mkdir(parents=True, exist_ok=True)
    con.print("[green]Initialized.[/green]")


@app.command("plan-month")
def plan_month(
    start: str = typer.Option(None, help="YYYY-MM-DD; defaults to today."),
    days: int = typer.Option(30, help="Days to plan."),
) -> None:
    """Populate the calendar grid for the next N days."""
    d = _date.fromisoformat(start) if start else _date.today()
    inserted = cal_mod.plan_days(d, days)
    con.print(f"[green]Planned {len(inserted)} new slots[/green] from {d} for {days} days.")


@app.command()
def generate(
    slot: str = typer.Option(None, help="DATE:SLOT, e.g. 2025-11-12:1"),
    content_type: str = typer.Option(None, "--type", help="Override slot's content type."),
    dry_run: bool = typer.Option(False),
) -> None:
    """Generate a single post."""
    if slot:
        d_s, idx_s = slot.split(":")
        target = cal_mod.get_slot(_date.fromisoformat(d_s), int(idx_s))
    else:
        # Next planned slot today.
        slots = [x for x in cal_mod.list_slots(_date.today(), 1) if x.status == "planned"]
        if not slots:
            con.print("[yellow]No planned slots today.[/yellow]")
            raise typer.Exit(1)
        target = slots[0]
    if target is None:
        con.print("[red]Slot not found.[/red]")
        raise typer.Exit(1)
    if content_type:
        cal_mod.edit_slot(_date.fromisoformat(target.date), target.slot, content_type=content_type)
        target = cal_mod.get_slot(_date.fromisoformat(target.date), target.slot)
    if dry_run:
        con.print(f"[cyan]Would generate:[/cyan] {target}")
        return
    out = generate_one_post(target)
    con.print(f"[green]Generated[/green] -> {out}")


@app.command()
def regenerate(slug: str) -> None:
    """Regenerate the post matching a slug (clears its outputs first)."""
    s = get_settings()
    matches = list(s.output_dir.rglob(slug))
    for m in matches:
        if m.is_dir():
            for f in m.iterdir():
                f.unlink()
            m.rmdir()
    # Find the slot owning this slug.
    with connect() as c:
        row = c.execute("SELECT * FROM calendar WHERE post_slug = ?", (slug,)).fetchone()
    if row is None:
        con.print(f"[red]No calendar slot owns slug {slug}[/red]")
        raise typer.Exit(1)
    cal_mod.update_status(row["id"], status="planned", post_slug=None)
    target = cal_mod.get_slot(_date.fromisoformat(row["date"]), row["slot"])
    out = generate_one_post(target)
    con.print(f"[green]Regenerated[/green] -> {out}")


@app.command()
def schedule() -> None:
    """Run the scheduler forever (blocks)."""
    from chessbrain.scheduler import run_forever

    run_forever()


@app.command()
def today() -> None:
    """Open today's manifest in the browser."""
    p = manifest.render_day(_date.today())
    webbrowser.open(p.as_uri())
    con.print(f"[green]Opened[/green] {p}")


@app.command()
def week(start: str = typer.Option(None, help="YYYY-MM-DD; defaults to Monday of this week.")) -> None:
    """Render & open a week manifest."""
    if start:
        d = _date.fromisoformat(start)
    else:
        t = _date.today()
        d = t - timedelta(days=t.weekday())
    p = manifest.render_week(d)
    webbrowser.open(p.as_uri())
    con.print(f"[green]Opened[/green] {p}")


# -------- calendar subcommands --------
@calendar_app.command("list")
def calendar_list(days: int = 14, start: str = typer.Option(None)) -> None:
    d = _date.fromisoformat(start) if start else _date.today()
    rows = cal_mod.list_slots(d, days)
    t = Table(title=f"Calendar from {d} (+{days}d)")
    for col in ("date", "slot", "weekday", "type", "series", "param", "status", "post_slug"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            r.date,
            str(r.slot),
            r.weekday,
            r.content_type,
            r.series or "",
            json.dumps(r.series_param) if r.series_param is not None else "",
            r.status,
            r.post_slug or "",
        )
    con.print(t)


@calendar_app.command("edit")
def calendar_edit(
    date_: str = typer.Argument(..., metavar="DATE"),
    slot: int = typer.Argument(...),
    content_type: str = typer.Option(None, "--type"),
    series: str = typer.Option(None),
    param: str = typer.Option(None, help="JSON-encoded series_param"),
) -> None:
    changes: dict = {}
    if content_type:
        changes["content_type"] = content_type
    if series:
        changes["series"] = series
    if param:
        changes["series_param"] = json.loads(param)
    out = cal_mod.edit_slot(_date.fromisoformat(date_), slot, **changes)
    con.print(out)


# -------- brain subcommands --------
@brain_app.command("stats")
def brain_stats() -> None:
    with connect() as c:
        rows = c.execute(
            "SELECT kind, COUNT(*) AS n FROM idea_log GROUP BY kind ORDER BY n DESC"
        ).fetchall()
        total = c.execute("SELECT COUNT(*) AS n FROM idea_log").fetchone()["n"]
        posts = c.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        spend = c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM spend_log"
        ).fetchone()["s"]
    t = Table(title=f"Brain — {total} ideas · {posts} posts · ${spend:.2f} spent")
    t.add_column("kind")
    t.add_column("count", justify="right")
    for r in rows:
        t.add_row(r["kind"], str(r["n"]))
    con.print(t)


@brain_app.command("forbid")
def brain_forbid(
    kind: str = typer.Option(...),
    value: str = typer.Option(...),
) -> None:
    """Manually log an idea so it acts as a forbidden seed."""
    memory.log_idea(kind=kind, value=value, post_slug="manual", content_type="manual")
    con.print(f"[green]Forbidden[/green] {kind}: {value}")


# -------- puzzles --------
@puzzles_app.command("ingest")
def puzzles_ingest(
    path: Path,
    limit: int = typer.Option(None, help="Stop after N rows (for quick tests)."),
) -> None:
    from chessbrain import puzzle

    n = puzzle.ingest_csv_path(path, limit=limit)
    con.print(f"[green]Ingested {n:,} puzzles[/green]")


@puzzles_app.command("stats")
def puzzles_stats() -> None:
    from chessbrain import puzzle

    s = puzzle.stats()
    con.print(s)


# -------- imagegen --------
@imagegen_app.command("cost")
def imagegen_cost(days: int = 30) -> None:
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    with connect() as c:
        rows = c.execute(
            "SELECT model, COUNT(*) AS n, SUM(cost_usd) AS s FROM spend_log "
            "WHERE created_at >= ? GROUP BY model ORDER BY s DESC",
            (cutoff,),
        ).fetchall()
        total = c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM spend_log WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()["s"]
    t = Table(title=f"Spend last {days} days — total ${total:.2f}")
    for col in ("model", "calls", "$"):
        t.add_column(col)
    for r in rows:
        t.add_row(r["model"], str(r["n"]), f"${r['s']:.2f}")
    con.print(t)


@imagegen_app.command("calibrate")
def imagegen_calibrate() -> None:
    """Generate 8 sample images to verify style + spend."""
    from chessbrain.imagegen import client as ig
    from chessbrain.imagegen.base import RenderRequest

    prompts = [
        "a knight piece studying a chessboard, single subject, centered",
        "a bishop holding a candle in a library, dramatic lighting",
        "a rook standing watch on a castle wall at sunrise",
        "a pawn marching forward in a wheat field",
        "the chess-piece mascot giving a thumbs up, simple background",
        "a queen pondering on a balcony overlooking mountains",
        "two pieces having coffee at an outdoor cafe",
        "a chessboard with floating pieces in space",
    ]
    for p in prompts:
        out = ig.render(RenderRequest(prompt=p, aspect="4:5", model="nano_banana"), post_slug="calibrate")
        con.print(out.path)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
