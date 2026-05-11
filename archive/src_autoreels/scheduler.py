"""Scheduler — APScheduler wrapper for automated daily reel generation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def start_scheduler(
    campaign_name: str,
    settings: dict[str, Any],
    campaign: dict[str, Any],
    generate_fn,
) -> AsyncIOScheduler:
    """Start the APScheduler with jobs for each configured time slot.

    Args:
        campaign_name: Name of the campaign (e.g., 'matra').
        settings: Global settings dict.
        campaign: Campaign config dict.
        generate_fn: Async callable that generates and posts one reel.

    Returns:
        The running scheduler instance.
    """
    scheduler = AsyncIOScheduler()
    schedule_cfg = campaign.get("schedule", settings.get("schedule", {}))
    tz = settings.get("schedule", {}).get("timezone", "America/New_York")

    times = schedule_cfg.get("times", ["08:00", "14:00", "20:00"])

    for time_str in times:
        hour, minute = time_str.split(":")
        trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)
        scheduler.add_job(
            generate_fn,
            trigger,
            args=[campaign_name],
            id=f"{campaign_name}_{time_str}",
            replace_existing=True,
        )
        logger.info("Scheduled reel generation: %s @ %s %s", campaign_name, time_str, tz)

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(times))
    return scheduler
