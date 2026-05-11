"""Prompt generator — picks themes and optionally uses Groq to create unique prompts."""

from __future__ import annotations

import json
import random
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def pick_theme(campaign: dict[str, Any], *, exclude: list[str] | None = None) -> dict:
    """Pick a random theme, optionally excluding recently used ones."""
    themes = campaign["themes"]
    if exclude:
        available = [t for t in themes if t["name"] not in exclude]
        if not available:
            available = themes  # all used, reset
    else:
        available = themes
    return random.choice(available)


def build_base_prompt(theme: dict) -> str:
    """Return the raw prompt template from a theme."""
    return theme["prompt_template"].strip()


async def expand_prompt_with_groq(
    theme: dict,
    campaign: dict[str, Any],
    settings: dict[str, Any],
) -> str:
    """Use Groq LLM to create a unique variation of a theme prompt.

    Falls back to the base prompt template if Groq is unavailable.
    """
    api_key = settings.get("groq", {}).get("api_key", "")
    if not api_key:
        logger.warning("No GROQ_API_KEY set — using base prompt template")
        return build_base_prompt(theme)

    groq_cfg = settings.get("groq", {})
    campaign_groq = campaign.get("groq", {})
    system_prompt = campaign_groq.get("system_prompt", "You generate cinematic video prompts.")

    user_msg = (
        f"Theme name: {theme['name']}\n"
        f"Mood: {theme.get('mood', 'cinematic')}\n"
        f"Base concept: {theme['prompt_template'].strip()}\n\n"
        "Generate ONE unique variation of this concept as a text-to-video prompt. "
        "CRITICAL: The prompt MUST be 60-90 words maximum (the model truncates at 128 tokens). "
        "Pack maximum visual detail into minimal words. Use dense, comma-separated descriptors. "
        "Describe a single continuous 5-second camera shot. "
        "Include: camera angle/movement, lighting, textures, color palette, depth of field. "
        "Do NOT include text overlays, UI elements, logos, or any written words in the scene. "
        "Return ONLY the prompt text, no explanation or preamble."
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": groq_cfg.get("model", "llama-3.3-70b-versatile"),
                    "max_tokens": groq_cfg.get("max_tokens", 512),
                    "temperature": 0.9,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            prompt = data["choices"][0]["message"]["content"].strip()
            logger.info("Groq generated prompt: %s", prompt[:100])
            return prompt
    except Exception:
        logger.exception("Groq prompt expansion failed — using base template")
        return build_base_prompt(theme)


def pick_overlay_text(campaign: dict[str, Any]) -> dict[str, str]:
    """Pick random CTA line and hashtag set for overlay."""
    overlays = campaign.get("text_overlays", {})
    cta = random.choice(overlays.get("cta_lines", [""])) if overlays.get("cta_lines") else ""
    tags = random.choice(overlays.get("hashtag_sets", [""])) if overlays.get("hashtag_sets") else ""
    return {"cta": cta, "hashtags": tags}
