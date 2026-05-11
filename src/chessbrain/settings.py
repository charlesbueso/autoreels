"""Centralized config + secret loader.

Loads YAML configs from ``config/`` and environment variables from ``.env.local``.
Exposes a single ``get_settings()`` cached accessor.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings:
    """Lightweight bag-of-attributes settings object."""

    def __init__(self) -> None:
        load_dotenv(ROOT / ".env.local", override=False)
        load_dotenv(ROOT / ".env", override=False)

        self.root: Path = ROOT
        self.config_dir: Path = CONFIG_DIR
        self.assets_dir: Path = ASSETS_DIR
        self.data_dir: Path = DATA_DIR
        self.output_dir: Path = OUTPUT_DIR
        self.image_cache_dir: Path = DATA_DIR / "image_cache"

        self.runtime: dict[str, Any] = _load_yaml(CONFIG_DIR / "settings.yaml")
        self.brand: dict[str, Any] = _load_yaml(CONFIG_DIR / "brand.yaml")
        self.voice: dict[str, Any] = _load_yaml(CONFIG_DIR / "voice.yaml")
        self.visual_style: dict[str, Any] = _load_yaml(CONFIG_DIR / "visual_style.yaml")
        self.series: dict[str, Any] = _load_yaml(CONFIG_DIR / "series.yaml")
        self.calendar_grid: dict[str, Any] = _load_yaml(CONFIG_DIR / "calendar.yaml")

        self.content_types: dict[str, dict[str, Any]] = {}
        for p in sorted((CONFIG_DIR / "content_types").glob("*.yaml")):
            self.content_types[p.stem] = _load_yaml(p)

        # Secrets
        self.groq_api_key: str | None = os.getenv("GROQ_API_KEY")
        self.groq_model: str = os.getenv("GROQ_MODEL", self.runtime["llm"]["model"])
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        self.fal_key: str | None = os.getenv("FAL_KEY")
        self.google_ai_key: str | None = os.getenv("GOOGLE_AI_API_KEY")
        self.timezone: str = os.getenv("TIMEZONE", self.runtime["schedule"]["timezone"])

        # Ensure data/output dirs exist.
        for d in (self.data_dir, self.image_cache_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    # convenience
    @property
    def slots(self) -> list[str]:
        return list(self.runtime["schedule"]["slots"])

    @property
    def carousel_size(self) -> tuple[int, int]:
        c = self.runtime["canvas"]["carousel"]
        return c["width"], c["height"]

    @property
    def reel_size(self) -> tuple[int, int]:
        c = self.runtime["canvas"]["reel"]
        return c["width"], c["height"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
