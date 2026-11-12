"""People and the database, for the rest of the integration.

Writes go through here so that each one also refreshes goals, corrects the
recorder's history for past days, and tells the sensors and cards.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from . import goals as g
from .const import (
    CONF_ACTIVITY,
    CONF_BIRTH_DATE,
    CONF_CALORIE_GOAL,
    CONF_CARBS_PCT,
    CONF_DB_URL,
    CONF_FAT_PCT,
    CONF_GOAL_WEIGHT,
    CONF_HEIGHT,
    CONF_KEY,
    CONF_NAME,
    CONF_PACE,
    CONF_PERSON_ENTITY,
    CONF_PROTEIN_PCT,
    CONF_SEX,
    CONF_START_DATE,
    CONF_START_WEIGHT,
    DB_FILE,
    DOMAIN,
    MEALS,
    NUTRIENTS,
    SIGNAL_CHANGED,
)
from .db import Database, sqlite_url

# The daily total sensors, each as (key, unit, how to read it from one day's
# meal totals). Fixing a past day corrects their recorded history.
DAY_TOTALS: dict[str, tuple[str, Callable[[Mapping[str, Mapping[str, float]]], float]]] = {
    **{
        f"{n if n != 'kcal' else 'calories'}_today": (
            "kcal" if n == "kcal" else "g",
            lambda meals, n=n: sum(m[n] for m in meals.values()),
        )
        for n in NUTRIENTS
    },
    **{
        f"{meal}_calories": ("kcal", lambda meals, meal=meal: meals.get(meal, {}).get("kcal", 0.0))
        for meal in MEALS
    },
}


@dataclass(frozen=True)
class Person:
    """A person's settings, from their sub-entry."""

    key: str
    subentry_id: str
    name: str
    person_entity: str | None
    sex: str
    birth_date: date
    height_cm: float
    start_weight_kg: float
    start_date: date
    goal_weight_kg: float
    activity: str
    pace: str
    calorie_goal: float | None
    protein_pct: float
    carbs_pct: float
    fat_pct: float

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Person:
        d = subentry.data
        return cls(
            key=d[CONF_KEY],
            subentry_id=subentry.subentry_id,
            name=d[CONF_NAME],
            person_entity=d.get(CONF_PERSON_ENTITY),
            sex=d[CONF_SEX],
            birth_date=date.fromisoformat(d[CONF_BIRTH_DATE]),
            height_cm=d[CONF_HEIGHT],
            start_weight_kg=d[CONF_START_WEIGHT],
            start_date=date.fromisoformat(d[CONF_START_DATE]),
            goal_weight_kg=d[CONF_GOAL_WEIGHT],
            activity=d[CONF_ACTIVITY],
            pace=d[CONF_PACE],
            calorie_goal=d.get(CONF_CALORIE_GOAL),
            protein_pct=d[CONF_PROTEIN_PCT],
            carbs_pct=d[CONF_CARBS_PCT],
            fat_pct=d[CONF_FAT_PCT],
        )

    def as_json(self) -> dict[str, Any]:
        """What the cards get."""
        return {
            "id": self.key,
            "name": self.name,
            "person_entity": self.person_entity,
            "height_cm": self.height_cm,
            "start_weight_kg": self.start_weight_kg,
            "start_date": self.start_date.isoformat(),
            "goal_weight_kg": self.goal_weight_kg,
            **g.band_limits(self.height_cm),
        }


def today() -> date:
    """Today in Home Assistant's time zone."""
    return dt_util.now().date()


def database_url(hass: HomeAssistant, entry_data: Mapping[str, Any]) -> str:
    """The database of the entry with `entry_data`: Postgres if it has a URL, else SQLite."""
    return entry_data.get(CONF_DB_URL) or sqlite_url(hass.config.path(DB_FILE))


def uses_pounds(hass: HomeAssistant) -> bool:
    """Whether Home Assistant's unit system is US customary, which weighs in lb.

    People then see and type weights in lb and heights in feet and inches.
    Everything is still stored in kg and cm.
    """
    return hass.config.units.mass_unit == UnitOfMass.POUNDS


def day_sums(meals: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    """Each daily total sensor's value for one day's meal totals."""
    return {key: read(meals) for key, (_unit, read) in DAY_TOTALS.items()}


def food_entry(food: Mapping[str, Any], grams: float) -> dict[str, Any]:
    """An entry's fields for `grams` of a saved food.

    The entry copies the food's name and its nutrients scaled to the grams,
    so later changes to the food leave the entry as it was.
    """
    return {
        "food_id": food["id"],
        "name": food["name"],
        "grams": grams,
        **{n: None if food[n] is None else food[n] * grams / 100 for n in NUTRIENTS},
    }


def loaded_data(hass: HomeAssistant) -> FitnessData | None:
    """The loaded integration's FitnessData, or None while it is not loaded."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data.data
    return None


class FitnessData:
    """The database and the people, shared by the integration's parts."""

    def __init__(self, hass: HomeAssistant, db: Database, people: Iterable[Person]) -> None:
        self.hass = hass
        self.db = db
        self.people = {p.key: p for p in people}
        # Held for every write, and for the whole of a backup.
        self._write_lock = asyncio.Lock()
        # Whether a backup holds the lock.
        self._paused = False

    async def _read(self, func: Callable[..., Any], *args: Any) -> Any:
        return await self.hass.async_add_executor_job(func, *args)

    async def _write(self, func: Callable[..., Any], *args: Any) -> Any:
        async with self._write_lock:
            return await self.hass.async_add_executor_job(func, *args)

    # Backups

    async def async_pause_for_backup(self) -> None:
        """Hold writes and make the file complete on its own, until resumed."""
        await self._write_lock.acquire()
        try:
            await self.hass.async_add_executor_job(self.db.checkpoint)
        except Exception:
            self._write_lock.release()
            raise
        self._paused = True

    def resume_after_backup(self) -> None:
        """Let writes continue, if a backup held them."""
        # Not whether the lock is held: a write holds it too, as Home Assistant
        # resumes after a backup whose pause failed.
        if self._paused:
            self._paused = False
            self._write_lock.release()

    # Goals and weight

    async def async_weight(self, person: Person, day: date) -> tuple[float, str | None]:
        """The weight in force on `day` and the day it was logged.

        Before the first weigh-in that is the starting weight, with no day.
        """
        latest = await self._read(self.db.latest_weight, person.key, day.isoformat())
        if latest:
            return latest["kg"], latest["day"]
        return person.start_weight_kg, None

    async def async_burn(self, person: Person, day: date) -> float:
        """The person's estimated daily burn on `day`."""
        weight, _ = await self.async_weight(person, day)
        age = g.age_on(person.birth_date, day)
        return g.daily_burn(person.sex, weight, person.height_cm, age, person.activity)

    async def async_refresh_goals(self, person: Person) -> g.Goals:
        """Work out today's goals and record them if they changed; return them."""
        day = today()
        if person.calorie_goal is not None:
            kcal = person.calorie_goal
        else:
            kcal = g.suggested_calories(await self.async_burn(person, day), person.pace)
        goals = g.macro_grams(round(kcal), person.protein_pct, person.carbs_pct, person.fat_pct)
        goals = g.Goals(*(round(v, 1) for v in (goals.kcal, goals.protein, goals.carbs, goals.fat)))
        current = await self._read(self.db.goal_on, person.key, day.isoformat())
        if current != goals:
            await self._write(self.db.set_goal, person.key, day.isoformat(), goals)
        return goals

    # Changes

    def _changed(self, person: str | None, days: Iterable[str] = ()) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHANGED, person, set(days))

    async def _sums(self, person: str, day: str) -> dict[str, float]:
        meals = await self._read(self.db.meal_totals, person, day, day)
        return day_sums(meals.get(day, {}))

    def _correct_history(
        self, person: str, day: str, before: dict[str, float], after: dict[str, float]
    ) -> None:
        """Shift a past day's recorded totals, so long-term statistics match the diary.

        The sensors only ever show today. For a past day the recorder already
        holds hourly sums, so each changes by the difference from that day's
        last hour on, which moves that day's total and no other.
        """
        the_day = date.fromisoformat(day)
        if the_day >= today() or "recorder" not in self.hass.config.components:
            return
        from homeassistant.components.recorder import get_instance

        recorder = get_instance(self.hass)
        registry = er.async_get(self.hass)
        start = datetime.combine(the_day, time(23), tzinfo=dt_util.get_default_time_zone())
        for key, (unit, _read) in DAY_TOTALS.items():
            delta = after[key] - before[key]
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{person}_{key}")
            if entity_id and abs(delta) > 1e-9:
                recorder.async_adjust_statistics(entity_id, start, delta, unit)

    async def _edit_days(self, person: str, days: Iterable[str], write: Callable[[], Any]) -> Any:
        """Run `write`, then correct history for `days` and announce them."""
        days = sorted(set(days))
        before = {d: await self._sums(person, d) for d in days}
        result = await self._write(write)
        for d in days:
            self._correct_history(person, d, before[d], await self._sums(person, d))
        self._changed(person, days)
        return result

    # Entries

    async def async_add_entry(self, person: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Log an entry."""
        return await self._edit_days(
            person, [entry["day"]], lambda: self.db.add_entry(person, entry)
        )

    async def async_update_entry(self, old: dict[str, Any], changes: dict[str, Any]) -> Any:
        """Change an entry; `old` is the entry as it is now."""
        days = {old["day"], changes.get("day", old["day"])}
        return await self._edit_days(
            old["person"], days, lambda: self.db.update_entry(old["id"], changes)
        )

    async def async_delete_entry(self, old: dict[str, Any]) -> None:
        """Delete an entry; `old` is the entry as it is now."""
        await self._edit_days(old["person"], [old["day"]], lambda: self.db.delete_entry(old["id"]))

    async def async_add_entries(self, person: str, day: str, entries: list[dict]) -> list[dict]:
        """Log several entries on one day, all or none."""
        return await self._edit_days(person, [day], lambda: self.db.add_entries(person, entries))

    async def async_log_meal(
        self,
        person: str,
        day: str,
        meal: str,
        meal_id: int,
        version: int | None = None,
        item_ids: list[int] | None = None,
    ) -> list[dict]:
        """Log a saved meal's items under `meal` on `day`, all or none.

        Raises db.MealChangedError, logging nothing, as Database.log_meal does.
        """
        return await self._edit_days(
            person,
            [day],
            lambda: self.db.log_meal(person, day, meal, meal_id, version, item_ids),
        )

    # Weights

    async def async_set_weight(self, person: Person, day: str, kg: float) -> None:
        """Record a weight, then follow it with today's goals."""
        await self._write(self.db.set_weight, person.key, day, kg)
        await self.async_refresh_goals(person)
        self._changed(person.key)

    async def async_add_weights(self, person: Person, weights: list[tuple[str, float]]) -> int:
        """Record weights for days that have none; return how many were added."""
        added = await self._write(self.db.add_weights, person.key, weights)
        if added:
            await self.async_refresh_goals(person)
            self._changed(person.key)
        return added

    async def async_import_entries(self, person: str, entries: list[dict]) -> int:
        """Log entries across many past days; return how many.

        Their days' recorded history is left alone: it already holds the
        totals these entries came from.
        """
        if not entries:
            return 0
        await self._write(lambda: [self.db.add_entry(person, e) for e in entries])
        self._changed(person, {e["day"] for e in entries})
        return len(entries)

    async def async_replace_entries(
        self, person: str, source: str, start: str, end: str, entries: list[dict]
    ) -> None:
        """Replace a person's entries from `source` on the days from `start` to `end`.

        Entries from elsewhere, such as those logged in Home Assistant, stay.
        History is corrected for each past day whose totals changed.
        """
        before = await self._read(self.db.meal_totals, person, start, end)
        await self._write(self.db.replace_entries, person, source, start, end, entries)
        after = await self._read(self.db.meal_totals, person, start, end)
        days = sorted(before.keys() | after.keys())
        for day in days:
            self._correct_history(
                person, day, day_sums(before.get(day, {})), day_sums(after.get(day, {}))
            )
        self._changed(person, days)

    async def async_delete_weight(self, person: Person, day: str) -> None:
        """Delete a weight, then follow it with today's goals."""
        await self._write(self.db.delete_weight, person.key, day)
        await self.async_refresh_goals(person)
        self._changed(person.key)

    # Foods

    async def async_shared_write(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run a write to saved foods or saved meals, and announce it.

        Changes to either are everyone's, so they are announced for no person.
        """
        result = await self._write(func, *args)
        self._changed(None)
        return result

    # People

    async def async_delete_person_data(self, person: str) -> None:
        """Delete everything stored for a person, as Database.delete_person does."""
        await self._write(self.db.delete_person, person)
        self._changed(person)
        # Their meals, and foods only they used, went too.
        self._changed(None)

    async def async_read(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run a read in the executor."""
        return await self._read(func, *args)
