"""Registry of available content types."""
from __future__ import annotations

from importlib import import_module
from types import ModuleType

_TYPES = [
    "cheat_codes",
    "puzzle",
    "product_demo",
    "opening_trap",
    "endgame",
    "meme",
    "quote",
    "mascot_scene",
]


def get(name: str) -> ModuleType:
    if name not in _TYPES:
        raise KeyError(f"Unknown content type: {name}. Known: {_TYPES}")
    return import_module(f"chessbrain.content_types.{name}")


def all_names() -> list[str]:
    return list(_TYPES)
