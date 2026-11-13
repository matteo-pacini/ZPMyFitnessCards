"""The actions: log_weight, log_food, log_meal, log_active_calories and get_day."""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM, UnitSystem
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.metron import services
from custom_components.metron.const import DOMAIN
from custom_components.metron.schema import vol

from .conftest import mock_entry, person
from .test_activity import ALLOWED, BASE, GARMIN, anna, figures, reading
from .test_translations import ENGLISH

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}
ACTIONS = Path(services.__file__).with_name("services.yaml")


def device(hass: HomeAssistant, key: str = "debora") -> str:
    devices = dr.async_get(hass).devices
    return next(d.id for d in devices if (DOMAIN, key) in d.identifiers)


async def act(hass: HomeAssistant, action: str, **data: Any) -> Any:
    if "device_id" not in data:
        data["device_id"] = device(hass)
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
    return await data.async_shared_write(data.db.add_food, food)


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
        assert str(err) == "Choose a person added to Metron"


async def test_refuses_while_not_loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    debora = device(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    err = await refused(hass, "log_weight", weight=68, device_id=debora)
    assert err.translation_key == "not_loaded"
    assert str(err) == "Metron is not loaded"


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
        {"meal": "lunch", "name": "Eggs", "kcal": float("nan")},
        {"meal": "lunch", "name": "Eggs", "kcal": 200, "fat": float("inf")},
        {"meal": "lunch", "food": "Eggs", "grams": float("nan")},
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


# log_active_calories


@pytest.fixture
async def anna_entry(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory
) -> MockConfigEntry:
    """Anna, with active calories allowed and no sensor, and Debora, without them.

    Added yesterday, so the action takes yesterday too.
    """
    people = (anna(active_calories_entity=None), person())
    return await added_on(hass, freezer, "2026-11-08", mock_entry(*people, data=entry_data))


async def added_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, day: str, entry: MockConfigEntry
) -> MockConfigEntry:
    """Set `entry` up at noon on `day`, when Metron first works out its people's goals.

    Then it is noon on 9 November again, the tests' today, after midnight passed.
    """
    freezer.move_to(f"{day}T12:00:00+00:00")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to("2026-11-09T12:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return entry


async def log_active(hass: HomeAssistant, kcal: Any, **data: Any) -> None:
    await act(hass, "log_active_calories", kcal=kcal, device_id=device(hass, "anna"), **data)


async def anna_s_day(hass: HomeAssistant, day: str | None = None) -> dict[str, Any]:
    fields = {"device_id": device(hass, "anna")} | ({"day": day} if day else {})
    return await act(hass, "get_day", **fields)


def logged(measured: float | None, counted: float, added: float, status: str | None) -> dict:
    """get_day's activity for a figure Anna logged with the action."""
    return figures(measured, counted, added, status, source="action")


@pytest.mark.usefixtures("anna_entry")
async def test_h5_with_no_sensor_the_action_sets_today_s_figure(hass: HomeAssistant) -> None:
    day = await anna_s_day(hass)
    # "No active calories logged for today yet."
    assert day["activity"] == logged(None, 0, 0, "waiting")
    assert day["goals"]["kcal"] == BASE

    # A template renders a sensor's state as text.
    await log_active(hass, "906")
    day = await anna_s_day(hass)
    assert day["activity"] == logged(906, 680, 435.83, "counting")
    assert day["goals"]["kcal"] == 1804
    assert float(hass.states.get("sensor.anna_activity").state) == 435.83
    assert float(hass.states.get("sensor.anna_calorie_goal").state) == BASE

    # A lower figure replaces it, as a correction.
    await log_active(hass, 500)
    day = await anna_s_day(hass)
    assert day["activity"] == logged(500, 380, 135.83, "counting")
    assert day["goals"]["kcal"] == 1504


@pytest.mark.usefixtures("anna_entry")
async def test_today_s_figure_again_tells_no_one(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await log_active(hass, 500)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    await log_active(hass, 500)
    await act(hass, "log_weight", weight=69)
    # Debora's weight is the first change.
    assert (await client.receive_json())["event"] == {"person": "debora", "days": []}


@pytest.mark.parametrize("own_row", [False, True], ids=["today inherits", "today has its own"])
async def test_h6_a_past_day_s_figure_changes_that_day_s_goal_and_no_other(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    own_row: bool,
) -> None:
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    await added_on(hass, freezer, "2026-11-08", entry)
    if own_row:
        await act(hass, "log_weight", weight=69, device_id=device(hass, "anna"))
    data = entry.runtime_data.data
    set_on = [d for d, _ in await data.async_read(data.db.goal_changes, "anna", "2026-11-09")]
    assert ("2026-11-09" in set_on) is own_row
    today = await anna_s_day(hass)

    await log_active(hass, 906, day="2026-11-08")
    past = await anna_s_day(hass, "2026-11-08")
    assert past["activity"] == logged(906, 680, 435.83, None)
    # Its base stays: 1,368 and what activity adds, split as her goals are.
    assert past["goals"] == {"kcal": 1804, "protein": 90.2, "carbs": 225.5, "fat": 60.1}
    assert await anna_s_day(hass) == today
    set_on = [d for d, _ in await data.async_read(data.db.goal_changes, "anna", "2026-11-09")]
    assert set_on == ["2026-11-08", "2026-11-09"]

    # Again, lower: the same base, with less added.
    await log_active(hass, 500, day="2026-11-08")
    assert (await anna_s_day(hass, "2026-11-08"))["goals"]["kcal"] == 1504
    assert await anna_s_day(hass) == today


@pytest.mark.parametrize("before", [906, None], ids=["with activity", "without"])
async def test_h6_a_past_day_with_goals_carried_from_an_earlier_day_keeps_its_base(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    before: float | None,
) -> None:
    freezer.move_to("2026-11-07T12:00:00+00:00")
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if before is not None:
        await log_active(hass, before)
    seventh = (await anna_s_day(hass))["goals"]["kcal"]
    # Home Assistant is off for all of the 8th, which gets no goals of its own:
    # the 7th's, with any activity, are in force on it.
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to("2026-11-09T12:00:00+00:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    set_on = [d for d, _ in await data.async_read(data.db.goal_changes, "anna", "2026-11-09")]
    assert "2026-11-08" not in set_on
    # Not the 7th's activity: the 7th's base.
    assert (await anna_s_day(hass, "2026-11-08"))["goals"]["kcal"] == BASE

    await log_active(hass, 500, day="2026-11-08")
    day = await anna_s_day(hass, "2026-11-08")
    # Her base, 1,368, and what 500 adds.
    assert day["goals"]["kcal"] == 1504
    assert day["goals"]["kcal"] - round(day["activity"]["added"]) == BASE
    assert (await anna_s_day(hass, "2026-11-07"))["goals"]["kcal"] == seventh
    assert (await anna_s_day(hass))["goals"]["kcal"] == BASE


async def test_a_past_day_s_figure_corrects_the_activity_sensor_s_statistics(
    hass: HomeAssistant, anna_entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    recorder = MagicMock()
    hass.config.components.add("recorder")
    at = datetime(2026, 11, 8, 23, tzinfo=ZoneInfo("Europe/London"))
    with patch("homeassistant.components.recorder.get_instance", return_value=recorder):
        await log_active(hass, 906, day="2026-11-08")
        assert (await client.receive_json())["event"] == {"person": "anna", "days": []}
        await log_active(hass, 500, day="2026-11-08")
        # The same figure again changes nothing.
        await log_active(hass, 500, day="2026-11-08")
    assert recorder.async_adjust_statistics.call_args_list == [
        call("sensor.anna_activity", at, 435.83, "kcal"),
        call("sensor.anna_activity", at, pytest.approx(-300), "kcal"),
    ]
    await act(hass, "log_weight", weight=69, device_id=device(hass, "anna"))
    events = [(await client.receive_json())["event"] for _ in range(2)]
    # The second figure, then the weight: nothing for the third.
    assert events == [{"person": "anna", "days": []}] * 2


async def test_share_and_cap_apply_to_the_action(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    entry = mock_entry(
        anna(active_calories_entity=None, active_calories_share=50, active_calories_cap=300),
        data=entry_data,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await log_active(hass, 906)
    activity = (await anna_s_day(hass))["activity"]
    assert (activity["counted"], activity["status"]) == (300, "capped")


async def test_with_a_sensor_and_the_action_the_latest_write_wins(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    await reading(hass, 906)
    entry = mock_entry(anna(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    async def held() -> tuple[str, float]:
        activity = (await anna_s_day(hass))["activity"]
        return activity["source"], activity["measured"]

    await log_active(hass, 500)
    assert await held() == ("action", 500)
    # Afterwards the sensor only raises it.
    await reading(hass, 450)
    assert await held() == ("action", 500)
    await reading(hass, 600)
    assert await held() == (GARMIN, 600)


async def test_only_a_new_reading_from_the_sensor_raises_the_action_s_figure(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    await reading(hass, 906)
    entry = mock_entry(anna(), person("Ben"), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    async def held() -> tuple[str, float]:
        activity = (await anna_s_day(hass))["activity"]
        return activity["source"], activity["measured"]

    # A correction below the watch's figure.
    await log_active(hass, 500)
    # Ben's details change, so the entry reloads and reads Anna's sensor again.
    ben = next(s for s in entry.subentries.values() if s.title == "Ben")
    hass.config_entries.async_update_subentry(entry, ben, data={**ben.data, "goal_weight_kg": 60})
    await hass.async_block_till_done()
    assert await held() == ("action", 500)
    # Back from a moment unavailable, with the figure it had.
    await reading(hass, "unavailable")
    await reading(hass, 906)
    assert await held() == ("action", 500)
    await reading(hass, 910)
    assert await held() == (GARMIN, 910)


async def test_readings_apply_in_order_whatever_order_they_reach_the_lock(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-09T10:00:00+00:00")
    older = State(GARMIN, "500", {"unit_of_measurement": "kcal"})
    freezer.move_to("2026-11-09T11:00:00+00:00")
    await reading(hass, 600)
    entry = mock_entry(anna(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    # The 500's task reaches the lock after the 600's, read as Metron set up.
    await data.async_sensor_reading(data.people["anna"], older, None)

    async def held() -> tuple[str, float]:
        activity = (await anna_s_day(hass))["activity"]
        return activity["source"], activity["measured"]

    assert await held() == (GARMIN, 600)
    await log_active(hass, 300)
    # Read again as the entry reloads, the 600 is no new reading.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await held() == ("action", 300)


@pytest.mark.usefixtures("anna_entry")
async def test_the_action_trusts_its_caller_on_which_day_a_figure_is_for(
    hass: HomeAssistant,
) -> None:
    # The same as yesterday's: a sensor's reading would not count.
    await log_active(hass, 906, day="2026-11-08")
    await log_active(hass, 906)
    assert (await anna_s_day(hass))["activity"]["measured"] == 906


async def test_h6_a_past_day_keeps_the_settings_it_had(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    await added_on(hass, freezer, "2026-11-07", entry)
    await log_active(hass, 500, day="2026-11-08")
    # Then she changes her level, share, cap and macros.
    subentry = next(iter(entry.subentries.values()))
    changes = {
        "activity": "moderate",
        "active_calories_share": 50,
        "active_calories_cap": 300,
        "protein_pct": 40,
        "carbs_pct": 30,
    }
    hass.config_entries.async_update_subentry(entry, subentry, data=subentry.data | changes)
    await hass.async_block_till_done()

    await log_active(hass, 906, day="2026-11-08")
    day = await anna_s_day(hass, "2026-11-08")
    # Light's allowance, 75% and 1,500 kcal, as the day had them.
    assert day["activity"] == logged(906, 680, 435.83, None)
    # Its base and its split: 20% protein, 50% carbs, 30% fat.
    assert day["goals"] == {"kcal": 1804, "protein": 90.2, "carbs": 225.5, "fat": 60.1}

    # A day with no activity yet keeps the level its goals had, Light's, and
    # takes today's share and cap.
    await log_active(hass, 906, day="2026-11-07")
    activity = (await anna_s_day(hass, "2026-11-07"))["activity"]
    assert activity["allowed"] == ALLOWED
    assert (activity["share"], activity["cap"], activity["counted"]) == (50, 300, 300)


@pytest.mark.parametrize("level", ["sedentary", "moderate"])
async def test_h6_a_past_day_without_activity_keeps_the_level_its_goals_had(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory, level: str
) -> None:
    # Light on the 8th, when Metron worked out that day's goals.
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    await added_on(hass, freezer, "2026-11-08", entry)
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry, subentry, data=subentry.data | {"activity": level}
    )
    await hass.async_block_till_done()

    await log_active(hass, 906, day="2026-11-08")
    day = await anna_s_day(hass, "2026-11-08")
    assert day["activity"] == logged(906, 680, 435.83, None)
    assert day["goals"]["kcal"] == 1804


async def test_a_past_day_whose_goals_are_from_before_version_5_takes_today_s_level(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    data = (await added_on(hass, freezer, "2026-11-08", entry)).runtime_data.data
    # Goals set before version 5 stored no allowance.
    goals = await data.async_goal_on(data.people["anna"], "2026-11-08")
    await data.async_read(data.db.set_day, "anna", "2026-11-08", None, goals)
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry, subentry, data=subentry.data | {"activity": "moderate"}
    )
    await hass.async_block_till_done()

    await log_active(hass, 906, day="2026-11-08")
    activity = (await anna_s_day(hass, "2026-11-08"))["activity"]
    assert activity["allowed"] == pytest.approx(1395.25 * 0.35, abs=0.005)


async def test_the_action_takes_days_from_metron_s_first_goals_for_the_person(
    hass: HomeAssistant, entry_data: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    # She started a week ago; Metron first worked out her goals 3 days ago.
    started = anna(active_calories_entity=None, start_date="2026-11-02")
    entry = await added_on(hass, freezer, "2026-11-06", mock_entry(started, data=entry_data))

    # The diary would show no goal on that day, and so no activity either.
    err = await refused(
        hass, "log_active_calories", kcal=300, day="2026-11-04", device_id=device(hass, "anna")
    )
    assert err.translation_key == "day_before_person"
    assert str(err) == "2026-11-04 is before Anna was added to Metron"
    assert (await anna_s_day(hass, "2026-11-04"))["activity"] is None
    await log_active(hass, 300, day="2026-11-06")
    assert (await anna_s_day(hass, "2026-11-06"))["activity"]["measured"] == 300

    # With no goals worked out yet, only today.
    data = entry.runtime_data.data
    await data.async_read(data.db.delete_person, "anna")
    err = await refused(
        hass, "log_active_calories", kcal=300, day="2026-11-08", device_id=device(hass, "anna")
    )
    assert err.translation_key == "day_before_person"
    await log_active(hass, 300)
    assert (await anna_s_day(hass))["activity"]["measured"] == 300


@pytest.mark.usefixtures("anna_entry")
async def test_e12_the_action_is_refused_while_the_box_is_unticked(hass: HomeAssistant) -> None:
    err = await refused(hass, "log_active_calories", kcal=300)
    assert err.translation_key == "active_calories_disabled"
    assert str(err) == (
        "Active calories are not allowed for Debora. Tick Allow active calories in Debora's"
        " details, under Settings, Devices & services, Metron"
    )
    assert (await act(hass, "get_day"))["activity"] is None


@pytest.mark.usefixtures("anna_entry")
@pytest.mark.parametrize(
    ("data", "key", "message"),
    [
        ({"kcal": 300, "day": "2026-11-10"}, "future_day", "2026-11-10 is in the future"),
        (
            {"kcal": 300, "day": "2026-10-31"},
            "day_before_person",
            "2026-10-31 is before Anna was added to Metron",
        ),
        (
            {"kcal": -1},
            "active_calories_out_of_range",
            "Give active calories from 0 to 10,000 kcal",
        ),
        ({"kcal": 10000.1}, "active_calories_out_of_range", None),
        ({"kcal": "nan"}, "active_calories_out_of_range", None),
        ({"kcal": 300, "device_id": "no-such-device"}, "unknown_person", None),
    ],
)
async def test_the_action_explains_what_is_wrong(
    hass: HomeAssistant, data: dict[str, Any], key: str, message: str | None
) -> None:
    err = await refused(hass, "log_active_calories", **{"device_id": device(hass, "anna")} | data)
    assert err.translation_key == key
    if message:
        assert str(err) == message
    assert (await anna_s_day(hass))["activity"]["status"] == "waiting"


@pytest.mark.usefixtures("anna_entry")
@pytest.mark.parametrize(("kcal", "day"), [(0, "2026-11-08"), (10000, "2026-11-09")])
async def test_the_action_takes_0_to_10000_kcal_from_the_day_the_person_was_added(
    hass: HomeAssistant, kcal: float, day: str
) -> None:
    await log_active(hass, kcal, day=day)
    assert (await anna_s_day(hass, day))["activity"]["measured"] == kcal


@pytest.mark.usefixtures("anna_entry")
async def test_the_action_refuses_kcal_that_are_not_a_number(hass: HomeAssistant) -> None:
    with pytest.raises(vol.Invalid):
        await log_active(hass, "unavailable")


# Descriptions


def test_every_action_field_is_described_and_validated() -> None:
    described = yaml.safe_load(ACTIONS.read_text())
    schemas = {
        "log_weight": services.LOG_WEIGHT_SCHEMA,
        "log_food": services.LOG_FOOD_SCHEMA,
        "log_meal": services.LOG_MEAL_SCHEMA,
        "log_active_calories": services.LOG_ACTIVE_CALORIES_SCHEMA,
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
