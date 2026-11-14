"""Websocket commands the cards call.

People are identified by their key (the `id` that metron/people
returns). Days are ISO dates in Home Assistant's time zone, never in the
future. Any logged-in user may read and write; Home Assistant has no
per-person permissions to apply.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from sqlalchemy.exc import IntegrityError

from .const import (
    DOMAIN,
    MAX_KG,
    MEALS,
    MIN_KG,
    NUTRIENTS,
    REQUIRED_NUTRIENTS,
    SIGNAL_CHANGED,
    SIGNAL_PEOPLE,
)
from .data import FitnessData, Person, food_entry, loaded_data, today
from .db import EVERYONE, FoodGoneError, MealChangedError, MealExistsError
from .openfoodfacts import SearchError, async_search
from .schema import vol

# The longest range metron/days answers, in days.
MAX_RANGE = 400

ERR_NOT_LOADED = "not_loaded"
ERR_NOT_FOUND = "not_found"
ERR_BARCODE_TAKEN = "barcode_taken"
ERR_SEARCH_FAILED = "search_failed"
ERR_NAME_TAKEN = "name_taken"
ERR_MEAL_EXISTS = "meal_exists"
ERR_MEAL_CHANGED = "meal_changed"


def _day(value: Any) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as err:
        raise vol.Invalid("not an ISO date") from err
    if parsed > today():
        raise vol.Invalid("in the future")
    return parsed.isoformat()


def _number(value: Any) -> float:
    # Schemas turn a ValueError into Invalid, but not a TypeError, as float()
    # raises for None: then vol.Any would fail instead of trying the next.
    try:
        number = float(value)
    except TypeError as err:
        raise vol.Invalid("not a number") from err
    # float() reads "nan" and "inf" too.
    if not math.isfinite(number):
        raise vol.Invalid("not a number")
    return number


def _non_negative(value: Any) -> float:
    number = _number(value)
    if number < 0:
        raise vol.Invalid("negative")
    return number


def _positive(value: Any) -> float:
    number = _number(value)
    if number <= 0:
        raise vol.Invalid("not positive")
    return number


def _name(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise vol.Invalid("empty")
    return text


def _language(value: Any) -> str:
    text = str(value)
    if not re.fullmatch(r"[a-z]{2,3}", text):
        raise vol.Invalid("not a two- or three-letter language code")
    return text


NUTRIENT_FIELDS = {vol.Optional(n): vol.Any(None, _non_negative) for n in NUTRIENTS}

PORTIONS = [{vol.Required("name"): _name, vol.Required("grams"): _positive}]

FOOD_FIELDS = {
    vol.Optional("barcode"): vol.Any(None, _name),
    vol.Optional("portions"): PORTIONS,
    **NUTRIENT_FIELDS,
}

PERSON = {vol.Required("person"): str}

# A saved meal's item: a saved food and grams, or fixed values with a name.
MEAL_ITEM = vol.Any(
    {vol.Required("food_id"): int, vol.Required("grams"): _positive},
    {
        vol.Required("name"): _name,
        vol.Optional("grams"): vol.Any(None, _positive),
        # Not **NUTRIENT_FIELDS: its Optional("kcal") would keep kcal optional.
        vol.Required("kcal"): _non_negative,
        **{vol.Optional(n): vol.Any(None, _non_negative) for n in NUTRIENTS[1:]},
    },
)
MEAL_ITEMS = vol.All([MEAL_ITEM], vol.Length(min=1))

# A meal's owner: a person's key, or None for everyone.
OWNER = vol.Any(None, str)


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
        ws_search_open_food_facts,
        ws_food_meals,
        ws_meals,
        ws_add_meal,
        ws_update_meal,
        ws_delete_meal,
        ws_log_meal,
        ws_weights,
        ws_set_weight,
        ws_delete_weight,
    ):
        websocket_api.async_register_command(hass, command)


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
            data = loaded_data(hass)
            if data is None:
                connection.send_error(msg["id"], ERR_NOT_LOADED, "Metron is not loaded")
                return
            person = None
            if "person" in msg:
                person = data.people.get(msg["person"])
                if person is None:
                    connection.send_error(msg["id"], ERR_NOT_FOUND, "No such person")
                    return
            result = await handler(data, person, msg)
            if isinstance(result, _Error) and result.details is not None:
                # Details go in the translation placeholders, the only place
                # an error has for them; the integration's translations have
                # the code as an exception's key.
                connection.send_error(
                    msg["id"],
                    result.code,
                    result.message,
                    translation_key=result.code,
                    translation_domain=DOMAIN,
                    translation_placeholders=result.details,
                )
            elif isinstance(result, _Error):
                connection.send_error(msg["id"], result.code, result.message)
            else:
                connection.send_result(msg["id"], result)

        command.__name__ = handler.__name__
        return command

    return wrap


class _Error:
    def __init__(self, code: str, message: str, details: dict[str, str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details


def _food_details(food: dict[str, Any]) -> dict[str, str]:
    return {"food_id": str(food["id"]), "name": food["name"], "saved_by": food["saved_by"] or ""}


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
    entries changed, empty for weights, goals, activity and foods. Each
    person gets one too whenever the integration sets up, as it does after
    any change to a person, followed by one event with `people` true and no
    person: the people may have changed, one of them added, changed or removed.
    """

    @callback
    def changed(person: str | None, days: set[str]) -> None:
        connection.send_event(msg["id"], {"person": person, "days": sorted(days)})

    @callback
    def people() -> None:
        connection.send_event(msg["id"], {"person": None, "days": [], "people": True})

    stops = [
        async_dispatcher_connect(hass, SIGNAL_CHANGED, changed),
        async_dispatcher_connect(hass, SIGNAL_PEOPLE, people),
    ]

    @callback
    def stop() -> None:
        for each in stops:
            each()

    connection.subscriptions[msg["id"]] = stop
    connection.send_result(msg["id"])


# Days


@_command({vol.Required("type"): f"{DOMAIN}/day", **PERSON, vol.Required("day"): _day})
async def ws_day(data: FitnessData, person: Person, msg: dict) -> dict:
    """A person's day: entries, goals, weight and activity.

    `goals` are FitnessData.async_goal_on's: with what activity added that
    day. `activity` is FitnessData.async_activity's.
    """
    day = msg["day"]
    entries = await data.async_read(data.db.day_entries, person.key, day)
    goals = await data.async_goal_on(person, day)
    weight = await data.async_read(data.db.weights, person.key, day, day)
    return {
        "day": day,
        "entries": entries,
        "goals": asdict(goals) if goals else None,
        "weight_kg": weight[0]["kg"] if weight else None,
        "activity": await data.async_activity(person, day),
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
    """Totals by meal, goals and weight for each day from start to end.

    Each day's goals are as metron/day gives them.
    """
    start, end = date.fromisoformat(msg["start"]), date.fromisoformat(msg["end"])
    if not 0 <= (end - start).days < MAX_RANGE:
        return _Error("invalid_range", f"end must be on or after start, within {MAX_RANGE} days")
    meals = await data.async_read(data.db.meal_totals, person.key, msg["start"], msg["end"])
    weights = await data.async_read(data.db.weights, person.key, msg["start"], msg["end"])
    goals = await data.async_goals(person, start, end)
    weight_by_day = {w["day"]: w["kg"] for w in weights}
    days = [
        {
            "day": key,
            "meals": meals.get(key, {}),
            "goals": asdict(day_goals) if day_goals else None,
            "weight_kg": weight_by_day.get(key),
        }
        for key, day_goals in goals.items()
    ]
    return {"days": days}


# Entries


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
    """Log food: a saved food and grams, or a quick add of a name and kcal."""
    entry = {"day": msg["day"], "meal": msg["meal"]}
    if "food_id" in msg:
        if "grams" not in msg:
            return _Error("invalid_format", "grams is required with food_id")
        food = await data.async_read(data.db.food, msg["food_id"])
        if food is None:
            return NOT_FOUND
        entry |= food_entry(food, msg["grams"])
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
        vol.Optional("person"): str,
        vol.Optional("anyway", default=False): bool,
    }
)
async def ws_add_food(data: FitnessData, person: Person | None, msg: dict) -> dict | _Error:
    """Save a food, with nutrients per 100 g, saved by `person` if given.

    A food with no barcode whose name a saved food has is refused with
    name_taken, unless `anyway`. A barcode a saved food has is refused with
    barcode_taken. Both errors' details name that food: food_id, name and
    saved_by (a person's key, or "").
    """
    if any(msg.get(n) is None for n in REQUIRED_NUTRIENTS):
        return _Error("invalid_format", "kcal, protein, carbs and fat are required")
    if not msg.get("barcode") and not msg["anyway"]:
        same = await data.async_read(data.db.foods_named, msg["name"])
        if same:
            return _Error(ERR_NAME_TAKEN, "A saved food has this name", _food_details(same[0]))
    food = msg | {"saved_by": person.key if person else None}
    try:
        return await data.async_shared_write(data.db.add_food, food)
    except IntegrityError:
        taken = await data.async_read(data.db.food_by_barcode, msg["barcode"])
        # None only if that food was deleted since.
        details = _food_details(taken) if taken else None
        return _Error(ERR_BARCODE_TAKEN, "Another food has this barcode", details)


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
        food = await data.async_shared_write(data.db.update_food, msg["food_id"], changes)
    except IntegrityError:
        return _Error(ERR_BARCODE_TAKEN, "Another food has this barcode")
    return food or NOT_FOUND


@_command({vol.Required("type"): f"{DOMAIN}/food/delete", vol.Required("food_id"): int})
async def ws_delete_food(data: FitnessData, _person: None, msg: dict) -> _Error | None:
    """Delete a saved food. Entries logged from it keep their numbers."""
    if not await data.async_shared_write(data.db.delete_food, msg["food_id"]):
        return NOT_FOUND
    return None


@_command({vol.Required("type"): f"{DOMAIN}/food/meals", vol.Required("food_id"): int})
async def ws_food_meals(data: FitnessData, _person: None, msg: dict) -> list[dict]:
    """The saved meals a food is in, as {id, name, owner, emptied}, for deleting it."""
    return await data.async_read(data.db.meals_with_food, msg["food_id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/openfoodfacts/search",
        vol.Required("query"): _name,
        vol.Required("language"): _language,
        vol.Optional("page", default=1): vol.All(int, vol.Range(min=1)),
    }
)
@websocket_api.async_response
async def ws_search_open_food_facts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """A page of Open Food Facts products whose names match the query.

    Names come in `language` where products have one, and in English. The
    result is {products, more}, as openfoodfacts.async_search gives it.
    Needs no database, so it answers while the integration reloads.
    """
    try:
        found = await async_search(hass, msg["query"], msg["language"], msg["page"])
    except SearchError as err:
        connection.send_error(msg["id"], ERR_SEARCH_FAILED, str(err))
        return
    connection.send_result(msg["id"], found)


# Saved meals


def _owner(data: FitnessData, owner: str | None) -> str | None:
    """The stored owner for a message's `owner`, or None if no such person."""
    if owner is None:
        return EVERYONE
    return owner if owner in data.people else None


def _exists(err: MealExistsError) -> _Error:
    return _Error(ERR_MEAL_EXISTS, "A saved meal has this name", {"owner": err.owner})


MEAL_CHANGED = _Error(ERR_MEAL_CHANGED, "The meal was changed or deleted meanwhile")


@_command({vol.Required("type"): f"{DOMAIN}/meals", vol.Optional("person"): str})
async def ws_meals(data: FitnessData, person: Person | None, _msg: dict) -> list[dict]:
    """Saved meals A to Z with their items: everyone's and the person's own, or all.

    Each is {id, owner, name, version, items}; owner is a person's key, or
    None for everyone. An item is {id, food_id, name, grams, nutrients...}:
    a saved food's item has the food's values now, scaled to its grams.
    """
    return await data.async_read(data.db.meals, person.key if person else None)


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/add",
        vol.Required("name"): _name,
        vol.Required("owner"): OWNER,
        vol.Required("items"): MEAL_ITEMS,
    }
)
async def ws_add_meal(data: FitnessData, _person: None, msg: dict) -> dict | _Error:
    """Save a meal for its owner.

    A name that clashes is refused with meal_exists, whose details give the
    clashing meal's owner: a person's key, or "" for everyone.
    """
    owner = _owner(data, msg["owner"])
    if owner is None:
        return NOT_FOUND
    try:
        return await data.async_shared_write(data.db.add_meal, owner, msg["name"], msg["items"])
    except MealExistsError as err:
        return _exists(err)
    except FoodGoneError:
        return NOT_FOUND


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/update",
        vol.Required("meal_id"): int,
        vol.Required("version"): int,
        vol.Optional("name"): _name,
        vol.Optional("owner"): OWNER,
        vol.Optional("items"): MEAL_ITEMS,
    }
)
async def ws_update_meal(data: FitnessData, _person: None, msg: dict) -> dict | _Error:
    """Change a meal's name, owner or items, as it was at `version`.

    Refused with meal_changed if someone changed or deleted it since, and
    with meal_exists as metron/meal/add is.
    """
    changes = {k: msg[k] for k in ("name", "items") if k in msg}
    if "owner" in msg:
        changes["owner"] = _owner(data, msg["owner"])
        if changes["owner"] is None:
            return NOT_FOUND
    try:
        return await data.async_shared_write(
            data.db.update_meal, msg["meal_id"], msg["version"], changes
        )
    except MealChangedError:
        return MEAL_CHANGED
    except MealExistsError as err:
        return _exists(err)
    except FoodGoneError:
        return NOT_FOUND


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/delete",
        vol.Required("meal_id"): int,
        vol.Required("version"): int,
    }
)
async def ws_delete_meal(data: FitnessData, _person: None, msg: dict) -> _Error | None:
    """Delete a meal as it was at `version`; entries logged from it stay."""
    try:
        await data.async_shared_write(data.db.delete_meal, msg["meal_id"], msg["version"])
    except MealChangedError:
        return MEAL_CHANGED
    return None


@_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal/log",
        **PERSON,
        vol.Required("day"): _day,
        vol.Required("meal"): vol.In(MEALS),
        vol.Required("meal_id"): int,
        vol.Required("version"): int,
        vol.Required("items"): vol.All([int], vol.Length(min=1)),
    }
)
async def ws_log_meal(data: FitnessData, person: Person, msg: dict) -> list[dict] | _Error:
    """Log some of a saved meal's items, by their IDs, as entries; return them.

    All or nothing: refused with meal_changed if the meal changed or went
    since `version`, or is another person's own.
    """
    try:
        return await data.async_log_meal(
            person.key, msg["day"], msg["meal"], msg["meal_id"], msg["version"], msg["items"]
        )
    except MealChangedError:
        return MEAL_CHANGED


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
        vol.Required("kg"): vol.All(vol.Coerce(float), vol.Range(min=MIN_KG, max=MAX_KG)),
    }
)
async def ws_set_weight(data: FitnessData, person: Person, msg: dict) -> None:
    """Record a weight for a day, replacing that day's earlier one."""
    await data.async_set_weight(person, msg["day"], msg["kg"])


@_command({vol.Required("type"): f"{DOMAIN}/weight/delete", **PERSON, vol.Required("day"): _day})
async def ws_delete_weight(data: FitnessData, person: Person, msg: dict) -> None:
    """Delete a day's weight."""
    await data.async_delete_weight(person, msg["day"])
