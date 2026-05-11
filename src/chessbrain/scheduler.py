"""APScheduler-driven daily generation. Runs forever; one job per slot per day."""
from __future__ import annotations

import logging
from datetime import date as _date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from chessbrain.brain import calendar as cal_mod
from chessbrain.pipeline import generate_one_post
from chessbrain.settings import get_settings

log = logging.getLogger("chessbrain.scheduler")


def _job(slot_idx: int) -> None:
    today = _date.today()
    slot = cal_mod.get_slot(today, slot_idx)
    if slot is None:
        log.warning("No calendar slot for %s slot=%d", today, slot_idx)
        return
    if slot.status != "planned":
        log.info("Skipping %s slot=%d (status=%s)", today, slot_idx, slot.status)
        return
    log.info("Generating %s slot=%d (%s)", today, slot_idx, slot.content_type)
    try:
        out = generate_one_post(slot)
        log.info("Generated -> %s", out)
    except Exception:
        cal_mod.update_status(slot.id, status="error")
        log.exception("Generation failed for %s slot=%d", today, slot_idx)


def build() -> BlockingScheduler:
    s = get_settings()
    sched = BlockingScheduler(timezone=s.timezone)
    for i, hhmm in enumerate(s.slots):
        hh, mm = hhmm.split(":")
        sched.add_job(
            _job,
            CronTrigger(hour=int(hh), minute=int(mm), timezone=s.timezone),
            args=[i],
            id=f"slot_{i}",
            replace_existing=True,
        )
    return sched


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sched = build()
    log.info("Scheduler armed at %s ET", get_settings().slots)
    sched.start()
