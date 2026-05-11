"""Pre-seed the marketing brain with ~100 hooks per content type so the
similarity gate has a reasonable floor BEFORE the first real post ships.

Usage:
    python -m scripts.seed_idea_pools [--per-type 100]
"""
from __future__ import annotations

import argparse

from pydantic import BaseModel, Field
from rich.console import Console

from chessbrain.brain import memory
from chessbrain.content_types import registry
from chessbrain.content_types.planner import voice_block
from chessbrain.llm import call_json

con = Console()


class _HookList(BaseModel):
    hooks: list[str] = Field(..., description="distinct hooks, ≤8 words each")


SYSTEM = voice_block() + "\n\nProduce a long list of distinct hooks."


def seed_one(content_type: str, n: int) -> int:
    user = (
        f"Generate {n} distinct hooks for {content_type} posts about chess and Lichess. "
        "Hooks must be ≤8 words, varied in opening word, no clickbait clichés. "
        "Return JSON: {\"hooks\": [...]}"
    )
    out = call_json(system=SYSTEM, user=user, schema=_HookList, temperature=0.95, max_tokens=4096)
    written = 0
    for h in out.hooks:
        try:
            memory.log_idea("hook", h, post_slug=f"seed_{content_type}", content_type=content_type)
            written += 1
        except Exception:
            pass
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=80)
    args = ap.parse_args()
    grand = 0
    for ct in registry.all_names():
        n = seed_one(ct, args.per_type)
        con.print(f"[green]{ct}[/green]: {n} hooks")
        grand += n
    con.print(f"[bold]Total seeded:[/bold] {grand}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
