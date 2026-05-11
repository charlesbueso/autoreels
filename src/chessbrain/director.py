"""Director: dispatches a CalendarSlot to its content_type module."""
from __future__ import annotations

from types import ModuleType

from chessbrain.brain.calendar import CalendarSlot
from chessbrain.content_types import registry


def dispatch(slot: CalendarSlot) -> ModuleType:
    return registry.get(slot.content_type)
