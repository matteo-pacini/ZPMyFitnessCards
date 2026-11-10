"""Actions for automations, scripts and Assist: log a weight, log food, read a day.

Each names a person by the device the integration makes for them, which the
device selector offers by name. Days are dates in Home Assistant's time zone,
today when left out, never in the future.
"""

from __future__ import annotations

from dataclasses import asdict
from functools import partial
from typing import Any

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MAX_KG, MEALS, MIN_KG, NUTRIENTS
from .data import FitnessData, Person, food_entry, loaded_data, today
from .schema import vol

SERVICE_LOG_WEIGHT = "log_weight"
SERVICE_LOG_FOOD = "log_food"
SERVICE_GET_DAY = "get_day"

# What a quick add takes, as the diary's Quick add tab does.
QUICK_NUTRIENTS = ("kcal", "protein", "carbs", "fat")

_TEXT = vol.All(cv.string, vol.Strip, vol.Length(min=1))

PERSON_AND_DAY = {vol.Required("device_id"): cv.string, vol.Optional("day"): cv.date}

LOG_WEIGHT_SCHEMA = vol.Schema(
    {
        **PERSON_AND_DAY,
        vol.Required("weight"): vol.All(vol.Coerce(float), vol.Range(min=MIN_KG, max=MAX_KG)),
    }
)

LOG_FOOD_SCHEMA = vol.Schema(
    {
        **PERSON_AND_DAY,
        vol.Required("meal"): vol.In(MEALS),
        vol.Optional("food"): _TEXT,
        vol.Optional("barcode"): _TEXT,
        vol.Optional("grams"): vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False)),
        vol.Optional("name"): _TEXT,
        **{vol.Optional(n): cv.positive_float for n in QUICK_NUTRIENTS},
    }
)

GET_DAY_SCHEMA = vol.Schema(PERSON_AND_DAY)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every action."""
    hass.services.async_register(
        DOMAIN, SERVICE_LOG_WEIGHT, partial(_log_weight, hass), schema=LOG_WEIGHT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LOG_FOOD, partial(_log_food, hass), schema=LOG_FOOD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DAY,
        partial(_get_day, hass),
        schema=GET_DAY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _error(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _target(hass: HomeAssistant, call: ServiceCall) -> tuple[FitnessData, Person, str]:
    """The loaded data, the person and the ISO day that an action is for."""
    data = loaded_data(hass)
    if data is None:
        raise _error("not_loaded")
    device = dr.async_get(hass).async_get(call.data["device_id"])
    keys = [key for domain, key in device.identifiers if domain == DOMAIN] if device else []
    person = next((data.people[k] for k in keys if k in data.people), None)
    if person is None:
        raise _error("unknown_person")
    now = today()
    day = call.data.get("day", now)
    if day > now:
        raise _error("future_day", day=day.isoformat())
    return data, person, day.isoformat()


async def _log_weight(hass: HomeAssistant, call: ServiceCall) -> None:
    """Record a weight, replacing the day's earlier one."""
    data, person, day = _target(hass, call)
    await data.async_set_weight(person, day, call.data["weight"])


async def _log_food(hass: HomeAssistant, call: ServiceCall) -> None:
    """Log a saved food, by name or barcode, and grams; or a quick add of a name and kcal."""
    data, person, day = _target(hass, call)
    fields = call.data
    if sum(k in fields for k in ("food", "barcode", "name")) != 1:
        raise _error("one_food")
    entry: dict[str, Any] = {"day": day, "meal": fields["meal"]}
    if "name" in fields:
        if "kcal" not in fields:
            raise _error("kcal_required")
        entry |= {"name": fields["name"], "grams": fields.get("grams")}
        entry |= {n: fields.get(n) for n in QUICK_NUTRIENTS}
    else:
        if any(n in fields for n in QUICK_NUTRIENTS):
            raise _error("nutrients_with_saved_food")
        if "grams" not in fields:
            raise _error("grams_required")
        entry |= food_entry(await _saved_food(data, fields), fields["grams"])
    await data.async_add_entry(person.key, entry)


async def _saved_food(data: FitnessData, fields: dict[str, Any]) -> dict[str, Any]:
    if "barcode" in fields:
        food = await data.async_read(data.db.food_by_barcode, fields["barcode"])
        if food is None:
            raise _error("unknown_barcode", barcode=fields["barcode"])
        return food
    foods = await data.async_read(data.db.foods_named, fields["food"])
    if not foods:
        raise _error("unknown_food", food=fields["food"])
    if len(foods) > 1:
        raise _error("ambiguous_food", food=fields["food"], count=len(foods))
    return foods[0]


async def _get_day(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """A person's day: each meal's entries and totals, the day's totals, goals and weight.

    Nutrients are rounded to one decimal. In totals, a missing value counts as 0.
    """
    data, person, day = _target(hass, call)
    entries = await data.async_read(data.db.day_entries, person.key, day)
    goals = await data.async_read(data.db.goal_on, person.key, day)
    weight = await data.async_read(data.db.weights, person.key, day, day)
    meals = {
        meal: {
            **_totals([e for e in entries if e["meal"] == meal]),
            "entries": [
                {
                    "name": e["name"],
                    "grams": e["grams"],
                    **{n: None if e[n] is None else round(e[n], 1) for n in NUTRIENTS},
                }
                for e in entries
                if e["meal"] == meal
            ],
        }
        for meal in MEALS
    }
    return {
        "person": person.name,
        "day": day,
        "totals": _totals(entries),
        "meals": meals,
        "goals": asdict(goals) if goals else None,
        "weight_kg": weight[0]["kg"] if weight else None,
    }


def _totals(entries: list[dict[str, Any]]) -> dict[str, float]:
    return {n: round(sum(e[n] or 0 for e in entries), 1) for n in NUTRIENTS}
