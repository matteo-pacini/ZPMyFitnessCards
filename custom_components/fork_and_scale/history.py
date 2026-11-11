"""Importing a person's history from the recorder's long-term statistics.

Weights come from a weight sensor's daily means. Calories come from the
daily change of a sensor that counts calories eaten, and land as one
"Imported total" entry per day, since the sensor knows totals but not foods.
Importing again adds only what is missing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import IMPORTED_ENTRY, IMPORTED_MEAL
from .data import FitnessData, Person

START = datetime(1970, 1, 1, tzinfo=UTC)


async def _daily(hass: HomeAssistant, entity_id: str, kind: str, units: dict) -> list[dict]:
    # Imported here: the recorder is optional, and only loaded when it runs.
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import (
        statistics_during_period,
    )

    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, START, None, {entity_id}, "day", units, {kind}
    )
    return rows.get(entity_id, [])


def _day(row: dict[str, Any]) -> str:
    """The local day a daily statistics row covers."""
    return dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date().isoformat()


def has_statistics(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether the recorder keeps long-term statistics for this entity."""
    state = hass.states.get(entity_id)
    return state is not None and "state_class" in state.attributes


async def async_import_weights(
    hass: HomeAssistant, data: FitnessData, person: Person, entity_id: str
) -> int:
    """Add each day's mean weight in kg that the person has no weight for; return how many."""
    rows = await _daily(hass, entity_id, "mean", {"mass": "kg"})
    weights = [(_day(r), round(r["mean"], 2)) for r in rows if r.get("mean") is not None]
    return await data.async_add_weights(person, weights)


async def async_import_calories(
    hass: HomeAssistant, data: FitnessData, person: Person, entity_id: str
) -> int:
    """Log each day's calories as an imported total, unless that day has one; return how many."""
    rows = await _daily(hass, entity_id, "change", {})
    done = await data.async_read(data.db.days_with_entry_named, person.key, IMPORTED_ENTRY)
    today = dt_util.now().date().isoformat()
    totals: dict[str, float] = {}
    for row in rows:
        day = _day(row)
        if row.get("change") and day not in done and day <= today:
            totals[day] = totals.get(day, 0.0) + row["change"]
    entries = [
        {"day": day, "meal": IMPORTED_MEAL, "name": IMPORTED_ENTRY, "kcal": round(kcal, 1)}
        for day, kcal in sorted(totals.items())
        if kcal > 0
    ]
    return await data.async_import_entries(person.key, entries)
