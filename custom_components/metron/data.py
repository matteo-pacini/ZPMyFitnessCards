"""People and the database, for the rest of the integration.

Writes go through here so that each one also refreshes goals, corrects the
recorder's history for past days, and tells the sensors and cards.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from . import activity as a
from . import goals as g
from .const import (
    ACTIVE_CALORIES_DEFAULTS,
    CONF_ACTIVE_CALORIES_CAP,
    CONF_ACTIVE_CALORIES_ENABLED,
    CONF_ACTIVE_CALORIES_ENTITY,
    CONF_ACTIVE_CALORIES_SHARE,
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
    active_calories_enabled: bool
    active_calories_entity: str | None
    active_calories_share: float
    active_calories_cap: float

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
            active_calories_enabled=d.get(
                CONF_ACTIVE_CALORIES_ENABLED,
                ACTIVE_CALORIES_DEFAULTS[CONF_ACTIVE_CALORIES_ENABLED],
            ),
            active_calories_entity=d.get(CONF_ACTIVE_CALORIES_ENTITY),
            active_calories_share=d.get(
                CONF_ACTIVE_CALORIES_SHARE, ACTIVE_CALORIES_DEFAULTS[CONF_ACTIVE_CALORIES_SHARE]
            ),
            active_calories_cap=d.get(
                CONF_ACTIVE_CALORIES_CAP, ACTIVE_CALORIES_DEFAULTS[CONF_ACTIVE_CALORIES_CAP]
            ),
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
        """The person's estimated daily burn on `day`, before any activity."""
        weight, _ = await self.async_weight(person, day)
        age = g.age_on(person.birth_date, day)
        return g.daily_burn(person.sex, weight, person.height_cm, age, person.activity)

    async def _allowed(self, person: Person, day: date) -> float:
        """The kcal of activity the person's activity level allows for on `day`."""
        weight, _ = await self.async_weight(person, day)
        age = g.age_on(person.birth_date, day)
        resting = g.resting_burn(person.sex, weight, person.height_cm, age)
        return g.activity_allowed(resting, person.activity)

    async def _base(self, person: Person, day: date) -> float:
        """The calorie goal on `day` before activity: the typed one, else the suggested one."""
        if person.calorie_goal is not None:
            return person.calorie_goal
        return g.suggested_calories(await self.async_burn(person, day), person.pace)

    @staticmethod
    def _goals(person: Person, kcal: float) -> g.Goals:
        """`kcal` to the whole kcal, split into grams of each macro to 0.1 g."""
        goals = g.macro_grams(round(kcal), person.protein_pct, person.carbs_pct, person.fat_pct)
        return g.Goals(*(round(v, 1) for v in (goals.kcal, goals.protein, goals.carbs, goals.fat)))

    async def _activity_row(
        self, person: Person, day: date, source: str, measured: float
    ) -> dict[str, Any]:
        """A day's activity row for `measured` kcal from `source`, under the person's settings."""
        share, cap = person.active_calories_share, person.active_calories_cap
        counted = g.activity_counted(measured, share, cap)
        allowed = await self._allowed(person, day)
        return {
            "source": source,
            "measured": measured,
            "counted": counted,
            "added": g.activity_added(counted, allowed),
            "allowed": allowed,
            "share": share,
            "cap": cap,
        }

    async def _update_today(
        self,
        person: Person,
        change: Callable[[tuple[str, float] | None], tuple[str, float] | None] | None = None,
    ) -> tuple[g.Goals, bool]:
        """Bring today's activity and goals up to date; return the goals and whether they changed.

        Today's activity stays only while the box is ticked, and only if it
        came from the action or from the sensor the person has now. `change`
        is given what stays, as (source, measured kcal) or None, and returns
        what to keep instead. The rest of the row follows the person's
        settings and weight. The goals are the base plus what activity adds.
        It reads and writes under the lock, so no write meanwhile is lost.
        """
        day = today()
        key, iso = person.key, day.isoformat()
        async with self._write_lock:
            row = await self._read(self.db.activity, key, iso)
            kept = None
            if (
                row is not None
                and person.active_calories_enabled
                and row["source"] in (a.ACTION, person.active_calories_entity)
            ):
                kept = row["source"], row["measured"]
            if change is not None:
                kept = change(kept)
            new = None if kept is None else await self._activity_row(person, day, *kept)
            added = new["added"] if new else 0
            goals = self._goals(person, await self._base(person, day) + added)
            current = await self._read(self.db.goal_on, key, iso)
            changed = new != row or goals != current
            if changed:
                await self.hass.async_add_executor_job(
                    self.db.set_day, key, iso, new, None if goals == current else goals
                )
        return goals, changed

    async def async_refresh_goals(self, person: Person) -> g.Goals:
        """Work out today's goals and record them if they changed; return them.

        Today's activity follows the person's settings and weight first, as
        it is dropped when the box is unticked or the sensor changes, and
        what it adds depends on both. A change is announced.
        """
        goals, changed = await self._update_today(person)
        if changed:
            self._changed(person.key)
        return goals

    # Activity

    async def async_activity(self, person: Person, day: str) -> dict[str, Any] | None:
        """A day's activity as metron/day gives it, or None if the day has none.

        A past day has its stored row, with `status` None. Today has one
        whenever the box is ticked, with its status: with nothing measured
        yet, `measured` is None and nothing counts.
        """
        row = await self._read(self.db.activity, person.key, day)
        the_day = date.fromisoformat(day)
        if the_day != today():
            return None if row is None else {**row, "status": None}
        if not person.active_calories_enabled:
            return None
        sensor = person.active_calories_entity
        held = row
        if row is None:
            row = {
                "source": sensor or a.ACTION,
                "measured": None,
                "counted": 0.0,
                "added": 0.0,
                "allowed": await self._allowed(person, the_day),
                "share": person.active_calories_share,
                "cap": person.active_calories_cap,
            }
        state = self.hass.states.get(sensor) if sensor else None
        return {**row, "status": a.status(sensor, state, held)}

    async def async_sensor_reading(
        self, person: Person, state: State | None, before: State | None
    ) -> None:
        """Count `state`, the person's sensor's, for today if it is a reading from today.

        Today's measured only rises. Today's activity and goals are written
        if they change, and announced if they or today's status changed
        since `before`, the sensor's previous state.
        """
        sensor = person.active_calories_entity
        kcal = None if state is None else a.kcal_of(state)
        if kcal is not None:
            yesterday = (today() - timedelta(days=1)).isoformat()
            last = await self._read(self.db.activity, person.key, yesterday)
            if not a.counts_today(state, kcal, last and last["measured"]):
                kcal = None
        changed = False
        if kcal is not None:

            def rise(kept: tuple[str, float] | None) -> tuple[str, float] | None:
                return kept if kept is not None and kept[1] >= kcal else (sensor, kcal)

            _goals, changed = await self._update_today(person, rise)
        day = today().isoformat()
        if not changed:
            held = await self._read(self.db.activity, person.key, day)
            changed = a.status(sensor, before, held) != a.status(sensor, state, held)
        if changed:
            self._changed(person.key)

    async def async_log_activity(self, person: Person, day: str, kcal: float) -> None:
        """Set a person's measured active calories on `day`, replacing any, as the action does.

        Today's goals follow as for a reading. A past day's goal keeps its
        base, the goals in force less what activity added on the day they
        were set, which may be an earlier day's. The next day first gets a
        goals row of its own, so the change stops there. A past day with no
        goals in force is given none.
        """
        if day == today().isoformat():
            _goals, changed = await self._update_today(person, lambda _kept: (a.ACTION, kcal))
            if changed:
                self._changed(person.key)
            return
        the_day = date.fromisoformat(day)
        async with self._write_lock:
            old = await self._read(self.db.activity, person.key, day)
            new = await self._activity_row(person, the_day, a.ACTION, kcal)
            if new == old:
                return
            old_added = old["added"] if old else 0.0
            in_force = await self._read(self.db.goal_in_force, person.key, day)
            goals = pin = None
            if in_force is not None:
                set_on, kept = in_force
                carried = await self._read(self.db.activity, person.key, set_on)
                base = kept.kcal - (carried["added"] if carried else 0.0)
                goals = self._goals(person, base + new["added"])
                pin = (the_day + timedelta(days=1)).isoformat()
            await self.hass.async_add_executor_job(
                self.db.set_day, person.key, day, new, goals, pin
            )
        # As the Activity sensor reports it.
        delta = round(new["added"], 2) - round(old_added, 2)
        self._shift_history(person.key, day, {"activity": ("kcal", delta)})
        self._changed(person.key)

    # Changes

    def _changed(self, person: str | None, days: Iterable[str] = ()) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHANGED, person, set(days))

    async def _sums(self, person: str, day: str) -> dict[str, float]:
        meals = await self._read(self.db.meal_totals, person, day, day)
        return day_sums(meals.get(day, {}))

    def _correct_history(
        self, person: str, day: str, before: dict[str, float], after: dict[str, float]
    ) -> None:
        """Shift a past day's recorded totals, so long-term statistics match the diary."""
        deltas = {key: (unit, after[key] - before[key]) for key, (unit, _) in DAY_TOTALS.items()}
        self._shift_history(person, day, deltas)

    def _shift_history(
        self, person: str, day: str, deltas: Mapping[str, tuple[str, float]]
    ) -> None:
        """Shift the recorded totals of a person's sensors on a past day, by sensor key.

        `deltas` gives each sensor's unit and how much its total changed. The
        sensors only ever show today. For a past day the recorder already
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
        for key, (unit, delta) in deltas.items():
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
        await self._update_today(person)
        self._changed(person.key)

    async def async_add_weights(self, person: Person, weights: list[tuple[str, float]]) -> int:
        """Record weights for days that have none; return how many were added."""
        added = await self._write(self.db.add_weights, person.key, weights)
        if added:
            await self._update_today(person)
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
        await self._update_today(person)
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
