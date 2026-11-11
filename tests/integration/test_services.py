"""The actions: log_weight, log_food and get_day."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM, UnitSystem
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fork_and_scale import services
from custom_components.fork_and_scale.const import DOMAIN
from custom_components.fork_and_scale.schema import vol

from .test_translations import ENGLISH

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}
ACTIONS = Path(services.__file__).with_name("services.yaml")


def device(hass: HomeAssistant, key: str = "debora") -> str:
    devices = dr.async_get(hass).devices
    return next(d.id for d in devices if (DOMAIN, key) in d.identifiers)


async def act(hass: HomeAssistant, action: str, **data: Any) -> Any:
    data.setdefault("device_id", device(hass))
    response = await hass.services.async_call(
        DOMAIN, action, data, blocking=True, return_response=action == "get_day"
    )
    await hass.async_block_till_done()
    return response


async def refused(hass: HomeAssistant, action: str, **data: Any) -> ServiceValidationError:
    """The action's error. Home Assistant drops its message's final full stop."""
    with pytest.raises(ServiceValidationError) as caught:
        await act(hass, action, **data)
    return caught.value


async def save_food(entry: MockConfigEntry, **food: Any) -> dict[str, Any]:
    data = entry.runtime_data.data
    return await data.async_food_write(data.db.add_food, food)


def state(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


# log_weight


async def test_logs_today_s_weight_and_replaces_it(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    # A template renders the scale's state as text.
    await act(hass, "log_weight", weight="68.4")
    assert state(hass, "sensor.debora_weight") == 68.4
    await act(hass, "log_weight", weight=68.1)
    assert state(hass, "sensor.debora_weight") == 68.1
    data = entry.runtime_data.data
    assert await data.async_read(data.db.weights, "debora", "2026-11-01", "2026-11-09") == [
        {"day": "2026-11-09", "kg": 68.1}
    ]
    # Matteo is untouched.
    assert state(hass, "sensor.matteo_weight") == 89


async def test_logs_a_past_day_s_weight(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await act(hass, "log_weight", weight=69.5, day="2026-11-05", device_id=device(hass, "matteo"))
    data = entry.runtime_data.data
    assert await data.async_read(data.db.weights, "matteo", "2026-11-01", "2026-11-09") == [
        {"day": "2026-11-05", "kg": 69.5}
    ]


@pytest.mark.usefixtures("us_customary")
async def test_logs_a_weight_in_lb_on_a_us_install_unless_told_kg(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = entry.runtime_data.data
    await act(hass, "log_weight", weight=150)
    assert await data.async_read(data.db.weights, "debora", "2026-11-09", "2026-11-09") == [
        {"day": "2026-11-09", "kg": 68.04}
    ]
    await act(hass, "log_weight", weight=69.5, unit="kg")
    assert await data.async_read(data.db.weights, "debora", "2026-11-09", "2026-11-09") == [
        {"day": "2026-11-09", "kg": 69.5}
    ]


async def test_logs_a_weight_in_lb_on_a_metric_install_when_told(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await act(hass, "log_weight", weight=150, unit="lb")
    assert state(hass, "sensor.debora_weight") == 68.04


@pytest.mark.parametrize(
    ("units", "data", "message"),
    [
        (METRIC_SYSTEM, {"weight": 19.9}, "Give a weight from 20 to 400 kg"),
        (METRIC_SYSTEM, {"weight": 400.1}, "Give a weight from 20 to 400 kg"),
        (METRIC_SYSTEM, {"weight": 900, "unit": "lb"}, "Give a weight from 44.1 to 881.8 lb"),
        (US_CUSTOMARY_SYSTEM, {"weight": 44}, "Give a weight from 44.1 to 881.8 lb"),
        (US_CUSTOMARY_SYSTEM, {"weight": 881.9}, "Give a weight from 44.1 to 881.8 lb"),
        (US_CUSTOMARY_SYSTEM, {"weight": 401, "unit": "kg"}, "Give a weight from 20 to 400 kg"),
    ],
)
async def test_refuses_a_weight_out_of_range_in_its_unit(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    units: UnitSystem,
    data: dict[str, Any],
    message: str,
) -> None:
    hass.config.units = units
    err = await refused(hass, "log_weight", **data)
    assert err.translation_key == "weight_out_of_range"
    assert str(err) == message
    store = entry.runtime_data.data
    assert await store.async_read(store.db.weights, "debora", "2026-11-01", "2026-11-09") == []


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize("data", [{"weight": "unavailable"}, {"weight": 70, "unit": "st"}])
async def test_refuses_a_weight_that_is_not_one(hass: HomeAssistant, data: dict) -> None:
    with pytest.raises(vol.Invalid):
        await act(hass, "log_weight", **data)


@pytest.mark.usefixtures("entry")
async def test_refuses_a_future_day(hass: HomeAssistant) -> None:
    err = await refused(hass, "log_weight", weight=68, day="2026-11-10")
    assert err.translation_key == "future_day"
    assert str(err) == "2026-11-10 is in the future"


@pytest.mark.usefixtures("entry")
async def test_refuses_a_device_that_is_not_a_person(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    lamp = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "lamp")}
    )
    for device_id in (lamp.id, "no-such-device"):
        err = await refused(hass, "log_weight", weight=68, device_id=device_id)
        assert err.translation_key == "unknown_person"
        assert str(err) == "Choose a person added to Fork & Scale"


async def test_refuses_while_not_loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    debora = device(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    err = await refused(hass, "log_weight", weight=68, device_id=debora)
    assert err.translation_key == "not_loaded"
    assert str(err) == "Fork & Scale is not loaded"


# log_food


async def test_logs_a_saved_food_by_name_ignoring_case(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    food = await save_food(entry, **OATS)
    await act(hass, "log_food", meal="breakfast", food="  porridge OATS ", grams="60")
    data = entry.runtime_data.data
    [logged] = await data.async_read(data.db.day_entries, "debora", "2026-11-09")
    assert logged["food_id"] == food["id"]
    assert logged["name"] == "Porridge oats"
    assert logged["meal"] == "breakfast"
    assert logged["grams"] == 60
    assert logged["kcal"] == pytest.approx(233.4)
    assert logged["fibre"] is None
    assert state(hass, "sensor.debora_calories_today") == pytest.approx(233.4)
    assert state(hass, "sensor.debora_breakfast_calories") == pytest.approx(233.4)


async def test_logs_a_saved_food_by_barcode_on_a_past_day(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await save_food(entry, **OATS, barcode="5000168001142", fibre=10)
    await act(hass, "log_food", meal="snacks", barcode="5000168001142", grams=30, day="2026-11-08")
    data = entry.runtime_data.data
    [logged] = await data.async_read(data.db.day_entries, "debora", "2026-11-08")
    assert logged["name"] == "Porridge oats"
    assert logged["fibre"] == pytest.approx(3)
    assert state(hass, "sensor.debora_calories_today") == 0


async def test_quick_adds_a_name_and_kcal(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await act(hass, "log_food", meal="dinner", name="Restaurant pizza", kcal=900, protein="35")
    await act(hass, "log_food", meal="dinner", name="Garlic bread", kcal=300, grams=80)
    data = entry.runtime_data.data
    pizza, bread = await data.async_read(data.db.day_entries, "debora", "2026-11-09")
    assert pizza["food_id"] is None
    assert pizza["grams"] is None
    assert (pizza["kcal"], pizza["protein"], pizza["carbs"]) == (900, 35, None)
    assert bread["grams"] == 80
    assert state(hass, "sensor.debora_dinner_calories") == 1200


@pytest.mark.parametrize(
    ("data", "key", "message"),
    [
        ({}, "one_food", "Give exactly one of a saved food, a barcode or a name"),
        ({"food": "Porridge oats", "name": "Oats", "grams": 60}, "one_food", None),
        ({"food": "Porridge oats", "barcode": "123", "grams": 60}, "one_food", None),
        ({"name": "Pizza"}, "kcal_required", "A quick add needs the kcal"),
        ({"food": "Porridge oats"}, "grams_required", "Give the grams of the saved food"),
        (
            {"food": "Porridge oats", "grams": 60, "kcal": 200},
            "nutrients_with_saved_food",
            "kcal, protein, carbs and fat are for a quick add only. A saved food has its own",
        ),
        (
            {"food": "Muesli", "grams": 60},
            "unknown_food",
            "There is no saved food called Muesli",
        ),
        (
            {"barcode": "999", "grams": 60},
            "unknown_barcode",
            "No saved food has the barcode 999",
        ),
    ],
)
async def test_log_food_explains_what_is_wrong(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    data: dict[str, Any],
    key: str,
    message: str | None,
) -> None:
    await save_food(entry, **OATS)
    err = await refused(hass, "log_food", meal="lunch", **data)
    assert err.translation_key == key
    if message:
        assert str(err) == message
    store = entry.runtime_data.data
    assert await store.async_read(store.db.day_entries, "debora", "2026-11-09") == []


async def test_refuses_a_name_two_saved_foods_share(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await save_food(entry, **OATS)
    await save_food(entry, **OATS | {"name": "PORRIDGE OATS"})
    err = await refused(hass, "log_food", meal="breakfast", food="Porridge oats", grams=60)
    assert str(err) == "2 saved foods are called Porridge oats. Rename them, or use a barcode"


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "data",
    [
        {"meal": "brunch", "name": "Eggs", "kcal": 200},
        {"meal": "lunch", "name": "  ", "kcal": 200},
        {"meal": "lunch", "name": "Eggs", "kcal": -1},
        {"meal": "lunch", "food": "Eggs", "grams": 0},
    ],
)
async def test_log_food_refuses_invalid_values(hass: HomeAssistant, data: dict) -> None:
    with pytest.raises(vol.Invalid):
        await act(hass, "log_food", **data)


# get_day


async def test_gets_a_day(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await save_food(entry, **OATS, fibre=10)
    await act(hass, "log_food", meal="breakfast", food="Porridge oats", grams=60)
    await act(hass, "log_food", meal="breakfast", name="Coffee", kcal=2)
    await act(hass, "log_food", meal="dinner", name="Pizza", kcal=900, protein=35.04)
    await act(hass, "log_weight", weight=68.4)

    day = await act(hass, "get_day")

    assert day["person"] == "Debora"
    assert day["day"] == "2026-11-09"
    assert (day["weight_kg"], day["weight"], day["weight_unit"]) == (68.4, 68.4, "kg")
    assert day["goals"]["kcal"] == state(hass, "sensor.debora_calorie_goal")
    assert set(day["goals"]) == {"kcal", "protein", "carbs", "fat"}
    # Missing values count as 0 in totals, and every value is to 0.1.
    assert day["totals"] == {
        "kcal": 1135.4,
        "protein": 45.2,
        "carbs": 39.6,
        "fat": 4.1,
        "fibre": 6.0,
        "sugar": 0,
        "saturated_fat": 0,
        "salt": 0,
    }
    breakfast = day["meals"]["breakfast"]
    assert breakfast["kcal"] == 235.4
    assert breakfast["entries"] == [
        {
            "name": "Porridge oats",
            "grams": 60,
            "kcal": 233.4,
            "protein": 10.1,
            "carbs": 39.6,
            "fat": 4.1,
            "fibre": 6.0,
            "sugar": None,
            "saturated_fat": None,
            "salt": None,
        },
        {
            "name": "Coffee",
            "grams": None,
            "kcal": 2.0,
            "protein": None,
            "carbs": None,
            "fat": None,
            "fibre": None,
            "sugar": None,
            "saturated_fat": None,
            "salt": None,
        },
    ]
    assert day["meals"]["dinner"]["protein"] == 35.0
    assert day["meals"]["lunch"] == {
        "kcal": 0,
        "protein": 0,
        "carbs": 0,
        "fat": 0,
        "fibre": 0,
        "sugar": 0,
        "saturated_fat": 0,
        "salt": 0,
        "entries": [],
    }


@pytest.mark.usefixtures("entry")
async def test_gets_an_empty_day_before_any_goal(hass: HomeAssistant) -> None:
    day = await act(hass, "get_day", day="2026-10-01", device_id=device(hass, "matteo"))
    assert day["person"] == "Matteo"
    assert day["goals"] is None
    assert (day["weight_kg"], day["weight"], day["weight_unit"]) == (None, None, "kg")
    assert day["totals"]["kcal"] == 0
    assert all(meal["entries"] == [] for meal in day["meals"].values())


@pytest.mark.usefixtures("us_customary", "entry")
async def test_gets_a_day_s_weight_in_lb_on_a_us_install(hass: HomeAssistant) -> None:
    await act(hass, "log_weight", weight=68.44, unit="kg")
    day = await act(hass, "get_day")
    assert (day["weight_kg"], day["weight"], day["weight_unit"]) == (68.44, 150.9, "lb")
    day = await act(hass, "get_day", day="2026-11-08")
    assert (day["weight_kg"], day["weight"], day["weight_unit"]) == (None, None, "lb")


@pytest.mark.usefixtures("entry")
async def test_get_day_refuses_a_future_day(hass: HomeAssistant) -> None:
    err = await refused(hass, "get_day", day="2026-11-10")
    assert err.translation_key == "future_day"


# Descriptions


def test_every_action_field_is_described_and_validated() -> None:
    described = yaml.safe_load(ACTIONS.read_text())
    schemas = {
        "log_weight": services.LOG_WEIGHT_SCHEMA,
        "log_food": services.LOG_FOOD_SCHEMA,
        "get_day": services.GET_DAY_SCHEMA,
    }
    assert described.keys() == schemas.keys()
    for action, schema in schemas.items():
        fields = described[action]["fields"]
        assert {str(k) for k in schema.schema} == fields.keys(), action
        assert ENGLISH[f"services.{action}.name"]
        assert ENGLISH[f"services.{action}.description"]
        for field in fields:
            assert ENGLISH[f"services.{action}.fields.{field}.name"]
            assert ENGLISH[f"services.{action}.fields.{field}.description"]
        translated = {
            key.split(".")[3] for key in ENGLISH if key.startswith(f"services.{action}.fields.")
        }
        assert translated == fields.keys(), action
