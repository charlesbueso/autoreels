"""Groq JSON-mode client with retry + schema validation."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from chessbrain.settings import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def _client():
    s = get_settings()
    if not s.groq_api_key:
        raise RuntimeError("GROQ_API_KEY missing — set it in .env.local.")
    from groq import Groq

    return Groq(api_key=s.groq_api_key)


def call_json(
    *,
    system: str,
    user: str,
    schema: Type[T],
    temperature: float | None = None,
    max_tokens: int | None = None,
    retries: int | None = None,
) -> T:
    """Call Groq with JSON mode, validate against ``schema``."""
    s = get_settings()
    cfg = s.runtime["llm"]
    temperature = cfg["temperature"] if temperature is None else temperature
    max_tokens = cfg["max_tokens"] if max_tokens is None else max_tokens
    retries = cfg["json_retries"] if retries is None else retries

    schema_doc = json.dumps(schema.model_json_schema(), indent=2)
    full_system = (
        f"{system}\n\n"
        "You MUST reply with a single valid JSON object that matches this schema:\n"
        f"{schema_doc}\n"
        "No prose, no markdown fences, just JSON."
    )

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = _client().chat.completions.create(
                model=s.groq_model,
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or "{}"
            parsed = json.loads(content)
            return schema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            log.warning("Groq JSON parse/validate failed (attempt %d): %s", attempt + 1, e)
            user = (
                user
                + "\n\nPrevious response was invalid JSON for the schema. Return ONLY valid JSON."
            )
            continue
        except Exception as e:
            last_err = e
            log.warning("Groq call failed (attempt %d): %s", attempt + 1, e)
            continue
    raise RuntimeError(f"Groq call failed after {retries + 1} attempts: {last_err}")
