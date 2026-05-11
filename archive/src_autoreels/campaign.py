"""Campaign loader — reads YAML campaign configs and merges with global settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"


def _load_env() -> None:
    """Load .env.local (gitignored secrets)."""
    env_path = ROOT_DIR / ".env.local"
    if env_path.exists():
        load_dotenv(env_path)


def load_settings() -> dict[str, Any]:
    """Load global settings.yaml and inject env vars."""
    _load_env()
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    # Inject secrets from environment
    settings["discord"] = {
        "bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
        "review_channel_id": int(os.getenv("DISCORD_REVIEW_CHANNEL_ID", "0")),
    }
    settings["meta"] = {
        "page_access_token": os.getenv("META_PAGE_ACCESS_TOKEN", ""),
        "page_id": os.getenv("META_PAGE_ID", ""),
        "ig_account_id": os.getenv("META_IG_ACCOUNT_ID", ""),
    }
    settings["groq"]["api_key"] = os.getenv("GROQ_API_KEY", "")
    settings.setdefault("audio", {})["freesound_api_key"] = os.getenv("FREESOUND_API_KEY", "")
    settings["unsplash"] = {
        "access_key": os.getenv("UNSPLASH_ACCESS_KEY", ""),
    }
    return settings


def load_campaign(campaign_name: str) -> dict[str, Any]:
    """Load a campaign YAML by name (e.g., 'matra')."""
    campaign_path = CONFIG_DIR / "campaigns" / f"{campaign_name}.yaml"
    if not campaign_path.exists():
        raise FileNotFoundError(f"Campaign config not found: {campaign_path}")
    with open(campaign_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_output_dir(settings: dict, campaign_name: str) -> Path:
    """Return today's output directory for a campaign, creating it if needed."""
    from datetime import date

    base = ROOT_DIR / settings["output_dir"] / campaign_name / date.today().isoformat()
    base.mkdir(parents=True, exist_ok=True)
    return base
