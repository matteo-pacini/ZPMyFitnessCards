"""Websocket commands the cards call.

People are identified by their key (the `id` that zp_my_fitness/people
returns). Days are ISO dates in Home Assistant's time zone, never in the
future. Any logged-in user may read and write; Home Assistant has no
per-person permissions to apply.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, MEALS, NUTRIENTS, REQUIRED_NUTRIENTS, SIGNAL_CHANGED
from .data import FitnessData, Person, today
from .schema import vol

# The longest range zp_my_fitness/days answers, in days.
MAX_RANGE = 400

ERR_NOT_LOADED = "not_loaded"
ERR_NOT_FOUND = "not_found"
ERR_BARCODE_TAKEN = "barcode_taken"


def _day(value: Any) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as err:
        raise vol.Invalid("not an ISO date") from err
    if parsed > today():
        raise vol.Invalid("in the future")
    return parsed.isoformat()


def _non_negative(value: Any) -> float:
    number = float(value)
    if number < 0:
        raise vol.Invalid("negative")
    return number


def _positive(value: Any) -> float:
    number = float(value)
    if number <= 0:
        raise vol.Invalid("not positive")
    return number


def _name(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise vol.Invalid("empty")
    return text


NUTRIENT_FIELDS = {vol.Optional(n): vol.Any(None, _non_negative) for n in NUTRIENTS}

PORTIONS = [{vol.Required("name"): _name, vol.Required("grams"): _positive}]

FOOD_FIELDS = {
    vol.Optional("barcode"): vol.Any(None, _name),
    vol.Optional("portions"): PORTIONS,
    **NUTRIENT_FIELDS,
}

PERSON = {vol.Required("person"): str}


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every command."""
    for command in (
        ws_people,
        ws_subscribe,
        ws_day,
        ws_days,
        ws_add_entry,
        ws_update_entry,
        ws_delete_entry,
        ws_copy_meal,
        ws_search_foods,
        ws_recent_foods,
        ws_food_by_barcode,
        ws_add_food,
        ws_update_food,
        ws_delete_food,
        ws_weights,
        ws_set_weight,
        ws_delete_weight,
    ):
        websocket_api.async_register_command(hass, command)


def _data(hass: HomeAssistant) -> FitnessData | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data.data
    return None


def _command(schema: dict) -> Callable:
    """Register an async command that needs the loaded integration.

    The handler gets the FitnessData, and the Person when the message names
    one. A missing integration or person is answered with an error here.
    """

    def wrap(handler: Callable) -> Callable:
        @websocket_api.websocket_command(schema)
        @websocket_api.async_response
        async def command(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
        ) -> None:
            data = _data(hass)
            if data is None:
                connection.send_error(msg["id"], ERR_NOT_LOADED, "ZPMyFitnessCards is not loaded")
                return
            person = None
            if "person" in msg:
                person = data.people.get(msg["person"])
                if person is None:
                    connection.send_error(msg["id"], ERR_NOT_FOUND, "No such person")
                    return
            result = await handler(data, person, msg)
            if isinstance(result, _Error):
                connection.send_error(msg["id"], result.code, result.message)
            else:
                connection.send_result(msg["id"], result)

        command.__name__ = handler.__name__
        return command

    return wrap


class _Error:
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


NOT_FOUND = _Error(ERR_NOT_FOUND, "Not found")


# People and changes


@_command({vol.Required("type"): f"{DOMAIN}/people"})
async def ws_people(data: FitnessData, _person: None, _msg: dict) -> list[dict]:
    """List the people."""
    return [p.as_json() for p in data.people.values()]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send an event after every change: {person, days}.

    `person` is None for changes to saved foods. `days` lists the days whose
    entries changed, empty for weights and foods.
    """

    @callback
    def changed(person: str | None, days: set[str]) -> None:
        connection.send_event(msg["id"], {"person": person, "days": sorted(days)})

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_CHANGED, changed)
    connection.send_result(msg["id"])


# Days


@_command({vol.Required("type"): f"{DOMAIN}/day", **PERSON, vol.Required("day"): _day})
async def ws_day(data: FitnessData, person: Person, msg: dict) -> dict:
    """A person's day: entries, goals and weight."""
    day = msg["day"]
    entries = await data.async_read(data.db.day_entries, person.key, day)
    goals = await data.async_read(data.db.goal_on, person.key, day)
    weight = await data.async_read(data.db.weights, person.key, day, day)
    return {
        "day": day,
        "entries": entries,
        "goals": asdict(goals) if goals else None,
        "weight_kg": weight[0]["kg"] if weight else None,
    }


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/days",
        **PERSON,
        vol.Required("start"): _day,
        vol.Required("end"): _day,
    }
)
async def ws_days(data: FitnessData, person: Person, msg: dict) -> dict | _Error:
    """Totals by meal, goals and weight for each day from start to end."""
    start, end = date.fromisoformat(msg["start"]), date.fromisoformat(msg["end"])
    if not 0 <= (end - start).days < MAX_RANGE:
        return _Error("invalid_range", f"end must be on or after start, within {MAX_RANGE} days")
    meals = await data.async_read(data.db.meal_totals, person.key, msg["start"], msg["end"])
    weights = await data.async_read(data.db.weights, person.key, msg["start"], msg["end"])
    changes = await data.async_read(data.db.goal_changes, person.key, msg["end"])
    days = []
    goals = None
    pending = iter(changes)
    upcoming = next(pending, None)
    weight_by_day = {w["day"]: w["kg"] for w in weights}
    day = start
    while day <= end:
        key = day.isoformat()
        while upcoming and upcoming[0] <= key:
            goals = upcoming[1]
            upcoming = next(pending, None)
        days.append(
            {
                "day": key,
                "meals": meals.get(key, {}),
                "goals": asdict(goals) if goals else None,
                "weight_kg": weight_by_day.get(key),
            }
        )
        day += timedelta(days=1)
    return {"days": days}


# Entries


def _scaled(food: dict, grams: float) -> dict[str, float | None]:
    return {n: None if food[n] is None else food[n] * grams / 100 for n in NUTRIENTS}


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/entry/add",
        **PERSON,
        vol.Required("day"): _day,
        vol.Required("meal"): vol.In(MEALS),
        vol.Optional("food_id"): int,
        vol.Optional("grams"): _positive,
        vol.Optional("name"): _name,
        **NUTRIENT_FIELDS,
    }
)
async def ws_add_entry(data: FitnessData, person: Person, msg: dict) -> dict | _Error:
    """Log food: a saved food and grams, or a quick add of a name and kcal.

    For a saved food, the entry copies its name and its nutrients scaled to
    the grams, so later changes to the food leave the entry as it was.
    """
    entry = {"day": msg["day"], "meal": msg["meal"]}
    if "food_id" in msg:
        if "grams" not in msg:
            return _Error("invalid_format", "grams is required with food_id")
        food = await data.async_read(data.db.food, msg["food_id"])
        if food is None:
            return NOT_FOUND
        entry |= {"food_id": food["id"], "name": food["name"], "grams": msg["grams"]}
        entry |= _scaled(food, msg["grams"])
    else:
        if "name" not in msg or msg.get("kcal") is None:
            return _Error("invalid_format", "name and kcal are required without food_id")
        entry |= {"name": msg["name"], "grams": msg.get("grams")}
        entry |= {n: msg.get(n) for n in NUTRIENTS}
    return await data.async_add_entry(person.key, entry)


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/entry/update",
        vol.Required("entry_id"): int,
        vol.Optional("day"): _day,
        vol.Optional("meal"): vol.In(MEALS),
        vol.Optional("grams"): _positive,
        vol.Optional("name"): _name,
        **NUTRIENT_FIELDS,
    }
)
async def ws_update_entry(data: FitnessData, _person: None, msg: dict) -> dict | _Error:
    """Change an entry. New grams scale its nutrients unless they are given too."""
    old = await data.async_read(data.db.entry, msg["entry_id"])
    if old is None:
        return NOT_FOUND
    changes = {k: msg[k] for k in ("day", "meal", "grams", "name", *NUTRIENTS) if k in msg}
    if "grams" in changes and old["grams"] and not any(n in msg for n in NUTRIENTS):
        ratio = changes["grams"] / old["grams"]
        changes |= {n: None if old[n] is None else old[n] * ratio for n in NUTRIENTS}
    if changes.get("kcal", 0) is None:
        return _Error("invalid_format", "kcal cannot be empty")
    return await data.async_update_entry(old, changes)


@_command({vol.Required("type"): f"{DOMAIN}/entry/delete", vol.Required("entry_id"): int})
async def ws_delete_entry(data: FitnessData, _person: None, msg: dict) -> _Error | None:
    """Delete an entry."""
    old = await data.async_read(data.db.entry, msg["entry_id"])
    if old is None:
        return NOT_FOUND
    await data.async_delete_entry(old)
    return None


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/copy",
        **PERSON,
        vol.Required("from_day"): _day,
        vol.Required("from_meal"): vol.In(MEALS),
        vol.Required("to_day"): _day,
        vol.Required("to_meal"): vol.In(MEALS),
    }
)
async def ws_copy_meal(data: FitnessData, person: Person, msg: dict) -> list[dict]:
    """Copy one meal's entries to another day and meal; return the new entries."""
    entries = await data.async_read(data.db.day_entries, person.key, msg["from_day"])
    copies = [
        {
            **{k: e[k] for k in ("food_id", "name", "grams", *NUTRIENTS)},
            "day": msg["to_day"],
            "meal": msg["to_meal"],
        }
        for e in entries
        if e["meal"] == msg["from_meal"]
    ]
    return await data.async_add_entries(person.key, msg["to_day"], copies)


# Foods


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/food/search",
        vol.Required("query"): str,
        vol.Optional("limit", default=20): vol.All(int, vol.Range(min=1, max=100)),
    }
)
async def ws_search_foods(data: FitnessData, _person: None, msg: dict) -> list[dict]:
    """Saved foods whose name contains the query, or whose barcode is the query."""
    return await data.async_read(data.db.search_foods, msg["query"].strip(), msg["limit"])


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/food/recent",
        **PERSON,
        vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=100)),
    }
)
async def ws_recent_foods(data: FitnessData, person: Person, msg: dict) -> list[dict]:
    """The saved foods a person logged most recently."""
    return await data.async_read(data.db.recent_foods, person.key, msg["limit"])


@_command({vol.Required("type"): f"{DOMAIN}/food/barcode", vol.Required("barcode"): _name})
async def ws_food_by_barcode(data: FitnessData, _person: None, msg: dict) -> dict | None:
    """The saved food with this barcode, or None."""
    return await data.async_read(data.db.food_by_barcode, msg["barcode"])


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/food/add",
        vol.Required("name"): _name,
        **FOOD_FIELDS,
    }
)
async def ws_add_food(data: FitnessData, _person: None, msg: dict) -> dict | _Error:
    """Save a food, with nutrients per 100 g."""
    if any(msg.get(n) is None for n in REQUIRED_NUTRIENTS):
        return _Error("invalid_format", "kcal, protein, carbs and fat are required")
    try:
        return await data.async_food_write(data.db.add_food, msg)
    except sqlite3.IntegrityError:
        return _Error(ERR_BARCODE_TAKEN, "Another food has this barcode")


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/food/update",
        vol.Required("food_id"): int,
        vol.Optional("name"): _name,
        **FOOD_FIELDS,
    }
)
async def ws_update_food(data: FitnessData, _person: None, msg: dict) -> dict | _Error:
    """Change a saved food. Entries already logged from it stay as they are."""
    if any(n in msg and msg[n] is None for n in REQUIRED_NUTRIENTS):
        return _Error("invalid_format", "kcal, protein, carbs and fat cannot be empty")
    changes = {k: v for k, v in msg.items() if k not in ("id", "type", "food_id")}
    try:
        food = await data.async_food_write(data.db.update_food, msg["food_id"], changes)
    except sqlite3.IntegrityError:
        return _Error(ERR_BARCODE_TAKEN, "Another food has this barcode")
    return food or NOT_FOUND


@_command({vol.Required("type"): f"{DOMAIN}/food/delete", vol.Required("food_id"): int})
async def ws_delete_food(data: FitnessData, _person: None, msg: dict) -> _Error | None:
    """Delete a saved food. Entries logged from it keep their numbers."""
    if not await data.async_food_write(data.db.delete_food, msg["food_id"]):
        return NOT_FOUND
    return None


# Weights


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/weights",
        **PERSON,
        vol.Optional("start", default="0001-01-01"): _day,
        vol.Optional("end"): _day,
    }
)
async def ws_weights(data: FitnessData, person: Person, msg: dict) -> list[dict]:
    """A person's weights, oldest first, as {day, kg}."""
    end = msg.get("end", today().isoformat())
    return await data.async_read(data.db.weights, person.key, msg["start"], end)


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/weight/set",
        **PERSON,
        vol.Required("day"): _day,
        vol.Required("kg"): vol.All(vol.Coerce(float), vol.Range(min=20, max=400)),
    }
)
async def ws_set_weight(data: FitnessData, person: Person, msg: dict) -> None:
    """Record a weight for a day, replacing that day's earlier one."""
    await data.async_set_weight(person, msg["day"], msg["kg"])


@_command({vol.Required("type"): f"{DOMAIN}/weight/delete", **PERSON, vol.Required("day"): _day})
async def ws_delete_weight(data: FitnessData, person: Person, msg: dict) -> None:
    """Delete a day's weight."""
    await data.async_delete_weight(person, msg["day"])
