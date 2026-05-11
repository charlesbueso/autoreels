"""Shared planning helpers for content types: build the LLM context (voice +
forbidden block), call Groq with retries, validate against the similarity gate.
"""
from __future__ import annotations

import logging
from typing import Iterable, Type, TypeVar

from pydantic import BaseModel

from chessbrain.brain import memory
from chessbrain.llm import call_json
from chessbrain.settings import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def voice_block() -> str:
    v = get_settings().voice
    parts = [
        "BRAND PERSONA:",
        v.get("persona", "").strip(),
        "",
        "STRICT RULES:",
        *(f"- {r}" for r in v.get("rules", [])),
        "",
        "FORBIDDEN PHRASES (never use): " + ", ".join(v.get("forbidden_phrases", [])),
        "",
        "EXAMPLE HOOKS (style only — do NOT copy):",
        *(f"- {h}" for h in v.get("exemplar_hooks", [])),
    ]
    return "\n".join(parts)


def build_user_prompt(
    *,
    task: str,
    context_lines: Iterable[str] = (),
    forbidden_kinds: Iterable[str] = ("hook", "image_prompt", "scene", "slide_line"),
    extra_instructions: str = "",
) -> str:
    forbidden = memory.forbidden_block(list(forbidden_kinds), per_kind=20)
    lines = [task.strip(), ""]
    ctx = [c for c in context_lines if c]
    if ctx:
        lines += ["CONTEXT:", *(f"- {c}" for c in ctx), ""]
    if forbidden:
        lines += [
            "AVOID — these have been used recently. Do NOT repeat the topic, phrasing, or core idea:",
            forbidden,
            "",
        ]
    if extra_instructions:
        lines += [extra_instructions.strip(), ""]
    return "\n".join(lines)


def plan_with_retry(
    *,
    system: str,
    user: str,
    schema: Type[T],
    novelty_check: tuple[str, str] | None = None,
    max_attempts: int = 3,
) -> T:
    """Call Groq, optionally re-roll if `novelty_check=(kind, attribute_name)`
    is too similar to recent entries.
    """
    last: T | None = None
    threshold = get_settings().runtime["similarity_gate"]["threshold"]
    loose = get_settings().runtime["similarity_gate"]["loosened"]
    for attempt in range(max_attempts):
        plan = call_json(system=system, user=user, schema=schema)
        last = plan
        if novelty_check is None:
            return plan
        kind, attr = novelty_check
        candidate = getattr(plan, attr, "")
        if not candidate:
            return plan
        sim, near = memory.max_similarity(kind, candidate)
        if sim < threshold:
            return plan
        log.info("Novelty rejected (sim=%.3f, near='%s'); attempt %d", sim, near.value if near else "?", attempt + 1)
        user = (
            user
            + f"\n\nThe previous attempt was too similar (cosine={sim:.2f}) to a recent post: "
            f"\"{near.value if near else ''}\". Take a completely different angle."
        )
    # Loosen on final fallback.
    if last is not None:
        log.warning("Novelty gate loosened to %.2f after %d attempts", loose, max_attempts)
        return last
    raise RuntimeError("plan_with_retry exhausted attempts with no plan")
