"""Active calories from a sensor: which readings count, the day's status, goals and sensors.

Most tests follow Anna, the spec's worked example: female, 35, 165 cm, 70 kg,
Light, losing 0.5 kg a week, with Garmin Connect's active calories and the
defaults of 75% counted and at most 1,500 kcal a day. Her resting burn is
1,395.25 kcal, her level allows for 244.17 kcal of activity, and her goal
without activity is 1,368 kcal. A test of one of the draft's flows starts
with its ID, such as H1 or E3; the action's flows are in test_services.py.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.metron.const import DOMAIN
from custom_components.metron.data import FitnessData

from .conftest import mock_entry, person
from .test_config_flow import GARMIN, TICKED, _edit, _submit

TODAY = "2026-11-09"
YESTERDAY = "2026-11-08"
TOMORROW = "2026-11-10"
GARMIN_2 = f"{GARMIN}_2"
KCAL = {"unit_of_measurement": "kcal", "state_class": "total_increasing"}

# Anna's figures, from goals.py's maths. Replies give kcal to 0.01 kcal.
ALLOWED = 244.17
BASE = 1368


def anna(**changes: Any) -> dict[str, Any]:
    """Anna's sub-entry: active calories allowed, from her Garmin unless `changes` say."""
    details = {"birth_date": "1991-03-15", "activity": "light", "active_calories_entity": GARMIN}
    return person("Anna", **(TICKED | details | changes))


def figures(
    measured: float | None, counted: float, added: float, status: str | None, **more: Any
) -> dict[str, Any]:
    """metron/day's activity for Anna's Garmin, at her settings unless `more` says."""
    return {
        "source": GARMIN,
        "measured": None if measured is None else pytest.approx(measured, abs=0.005),
        "counted": counted,
        "added": pytest.approx(added, abs=0.005),
        "allowed": ALLOWED,
        "share": 75,
        "cap": 1500,
        "status": status,
        **more,
    }


@pytest.fixture
def set_up(hass: HomeAssistant, entry_data: dict[str, Any]):
    """Set the integration up with these people, on SQLite then Postgres."""

    async def go(*people: dict[str, Any]) -> MockConfigEntry:
        entry = mock_entry(*people, data=entry_data)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return go


@pytest.fixture
async def day(hass: HomeAssistant, hass_ws_client: WebSocketGenerator):
    """Ask metron/day for a person's day, Anna's today unless told.

    Connected first, while its sign-in is valid: tests move the clock on.
    Metron is set up before, as its routes must be in place before a client.
    """
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)

    async def get(day: str = TODAY, who: str = "anna") -> dict[str, Any]:
        await client.send_json_auto_id({"type": "metron/day", "person": who, "day": day})
        reply = await client.receive_json()
        assert reply["success"], reply
        return reply["result"]

    return get


async def subscribed(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> Any:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    return client


async def reading(
    hass: HomeAssistant, value: str | float, entity: str = GARMIN, **attributes: Any
) -> None:
    """Give the sensor a new state, in kcal unless `attributes` say otherwise."""
    hass.states.async_set(entity, str(value), KCAL | attributes)
    await hass.async_block_till_done()


def state(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


async def midnight(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(f"{TOMORROW}T00:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# The draft's flows


async def test_h1_ticking_the_box_and_picking_a_sensor_shows_activity_within_the_level(
    hass: HomeAssistant, set_up, day
) -> None:
    await reading(hass, 120)
    entry = await set_up(anna(active_calories_enabled=False, active_calories_entity=None))
    assert (await day())["activity"] is None

    result = await _edit(hass, entry, "Anna")
    done = await _submit(hass, result, TICKED | {"active_calories_entity": GARMIN})
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    # 75% of 120 is 90, within the 244 her level allows for: nothing is added.
    found = await day()
    assert found["activity"] == figures(120, 90, 0, "level")
    assert found["goals"]["kcal"] == BASE
    assert state(hass, "sensor.anna_activity") == 0


async def test_h2_readings_through_the_day_raise_the_goal_live(
    hass: HomeAssistant, set_up, day, hass_ws_client: WebSocketGenerator
) -> None:
    await reading(hass, 120)
    entry = await set_up(anna())
    assert (await day())["activity"] == figures(120, 90, 0, "level")
    assert state(hass, "sensor.anna_activity") == 0
    client = await subscribed(hass, hass_ws_client)
    await entry.runtime_data.data.async_add_entry(
        "anna", {"day": TODAY, "meal": "lunch", "name": "Wrap", "kcal": 850}
    )
    assert (await client.receive_json())["event"] == {"person": "anna", "days": [TODAY]}

    for measured, counted, added, total in ((500, 380, 135.83, 1504), (906, 680, 435.83, 1804)):
        await reading(hass, measured)
        assert (await client.receive_json())["event"] == {"person": "anna", "days": []}
        found = await day()
        assert found["activity"] == figures(measured, counted, added, "counting")
        assert found["goals"]["kcal"] == total
        # The goal sensor reports the base, and the Activity sensor what it adds.
        assert state(hass, "sensor.anna_calorie_goal") == BASE
        assert state(hass, "sensor.anna_activity") == round(added, 2)
        assert state(hass, "sensor.anna_calories_remaining") == total - 850
        assert state(hass, "sensor.anna_daily_burn") == round(1395.25 * 1.375 + added)


async def test_h3_sedentary_counts_every_kcal(hass: HomeAssistant, set_up, day) -> None:
    await reading(hass, 120)
    await set_up(anna(activity="sedentary"))
    activity = (await day())["activity"]
    # Exactly 0, which the diary's line tells apart.
    assert activity["allowed"] == 0
    assert (activity["counted"], activity["added"], activity["status"]) == (90, 90, "counting")


async def test_h4_a_past_day_keeps_its_row_and_a_day_before_has_none(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    await midnight(hass, freezer)
    past = await day(TODAY)
    assert past["activity"] == figures(906, 680, 435.83, None)
    assert past["goals"]["kcal"] == 1804
    assert (await day(YESTERDAY))["activity"] is None


# Which readings count


async def test_e1_after_midnight_a_reading_from_before_does_not_count(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    await midnight(hass, freezer)
    found = await day(TOMORROW)
    assert found["activity"] == figures(None, 0, 0, "waiting")
    assert found["goals"]["kcal"] == BASE
    assert state(hass, "sensor.anna_activity") == 0
    # Its attributes change, but not its state: still yesterday's reading.
    freezer.tick(timedelta(hours=8))
    await reading(hass, 906, friendly_name="Garmin Connect Active calories")
    assert (await day(TOMORROW))["activity"]["status"] == "waiting"
    assert (await day(TODAY))["activity"]["measured"] == 906

    await reading(hass, 50)
    assert (await day(TOMORROW))["activity"] == figures(50, 40, 0, "level")


async def test_e1_a_reading_that_last_changed_before_midnight_does_not_count(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    # Before Metron ran, so there is no figure from yesterday to equal.
    freezer.move_to(f"{YESTERDAY}T23:00:00+00:00")
    await reading(hass, 906)
    freezer.move_to(f"{TODAY}T12:00:00+00:00")
    await set_up(anna())
    assert (await day())["activity"] == figures(None, 0, 0, "waiting")
    # Its attributes change, but not its state: still yesterday's reading.
    await reading(hass, 906, friendly_name="Garmin Connect Active calories")
    assert (await day())["activity"] == figures(None, 0, 0, "waiting")


async def test_e2_after_a_restart_past_midnight_yesterday_s_figure_does_not_count(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    freezer.move_to(f"{TOMORROW}T07:00:00+00:00")
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Restored as Home Assistant starts, so it last changed now.
    hass.states.async_remove(GARMIN)
    await reading(hass, 906)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await day(TOMORROW))["activity"]["status"] == "waiting"

    await reading(hass, 907)
    assert (await day(TOMORROW))["activity"]["measured"] == 907


async def test_e2_yesterday_s_last_reading_does_not_count_though_the_action_changed_the_figure(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    data = entry.runtime_data.data
    # An automation logged another figure for the day than the watch's last.
    await data.async_log_activity(data.people["anna"], TODAY, 950)
    await hass.async_block_till_done()
    freezer.move_to(f"{TOMORROW}T07:00:00+00:00")
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Restored as Home Assistant starts, so it last changed now.
    hass.states.async_remove(GARMIN)
    await reading(hass, 906)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await day(TOMORROW))["activity"]["status"] == "waiting"


async def test_e3_unavailable_keeps_the_held_value_and_recovery_counts_again(
    hass: HomeAssistant, set_up, day, hass_ws_client: WebSocketGenerator
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    client = await subscribed(hass, hass_ws_client)

    await reading(hass, "unavailable")
    # Only the status changed, and the cards hear of it.
    assert (await client.receive_json())["event"] == {"person": "anna", "days": []}
    found = await day()
    assert found["activity"] == figures(906, 680, 435.83, "unavailable")
    assert found["goals"]["kcal"] == 1804
    assert hass.states.get("sensor.anna_activity").attributes["status"] == "unavailable"

    await reading(hass, 1000)
    assert (await day())["activity"] == figures(1000, 750, 505.83, "counting")


async def test_e4_over_the_cap_the_cap_counts(hass: HomeAssistant, set_up, day) -> None:
    # 75% of 2,400 is 1,800.
    await reading(hass, 2400)
    await set_up(anna())
    found = await day()
    assert found["activity"] == figures(2400, 1500, 1500 - ALLOWED, "capped")
    assert found["goals"]["kcal"] == round(1368.46875 + 1500 - ALLOWED)


async def test_within_the_level_wins_over_capped(hass: HomeAssistant, set_up, day) -> None:
    # The spec's order: 75% of 906 is over a cap of 100, which her level covers.
    await reading(hass, 906)
    await set_up(anna(active_calories_cap=100))
    assert (await day())["activity"] == figures(906, 100, 0, "level", cap=100)


async def test_e5_a_kj_sensor_counts_in_kcal(hass: HomeAssistant, set_up, day) -> None:
    await reading(hass, 3790, unit_of_measurement="kJ")
    await set_up(anna())
    assert (await day())["activity"] == figures(3790 / 4.184, 680, 435.83, "counting")


async def test_replies_and_attributes_give_the_figures_to_0_01_kcal(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 3790, unit_of_measurement="kJ")
    entry = await set_up(anna())
    figures = {"measured": 905.83, "counted": 680, "added": 435.83, "allowed": 244.17}
    activity = (await day())["activity"]
    assert {key: activity[key] for key in figures} == figures
    attributes = hass.states.get("sensor.anna_activity").attributes
    assert {key: attributes[key] for key in ("measured", "counted")} == {
        "measured": 905.83,
        "counted": 680,
    }
    # Stored as measured.
    data = entry.runtime_data.data
    assert (await data.async_read(data.db.activity, "anna", TODAY))["measured"] == 3790 / 4.184

    await midnight(hass, freezer)
    past = (await day(TODAY))["activity"]
    assert {key: past[key] for key in figures} == figures


async def test_e7_a_typed_calorie_goal_gets_activity_on_top(
    hass: HomeAssistant, set_up, day
) -> None:
    await reading(hass, 906)
    await set_up(anna(calorie_goal=2000))
    goals = (await day())["goals"]
    assert goals == {"kcal": 2436, "protein": 121.8, "carbs": 304.5, "fat": 81.2}
    assert state(hass, "sensor.anna_calorie_goal") == 2000
    # The macro goals split the total.
    assert state(hass, "sensor.anna_protein_goal") == 121.8


async def test_e9_a_removed_sensor_keeps_its_figure_for_the_day_only(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    hass.states.async_remove(GARMIN)
    await hass.async_block_till_done()
    found = await day()
    assert found["activity"] == figures(906, 680, 435.83, "missing")
    assert found["goals"]["kcal"] == 1804

    await midnight(hass, freezer)
    assert (await day(TOMORROW))["activity"] == figures(None, 0, 0, "missing")


async def test_e10_a_sensor_that_stops_changing_keeps_counting(
    hass: HomeAssistant, set_up, day, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(f"{TODAY}T08:00:00+00:00")
    await reading(hass, 906)
    entry = await set_up(anna())
    freezer.move_to(f"{TODAY}T23:00:00+00:00")
    data = entry.runtime_data.data
    await data.async_add_entry("anna", {"day": TODAY, "meal": "dinner", "name": "Soup", "kcal": 1})
    await hass.async_block_till_done()
    assert (await day())["activity"] == figures(906, 680, 435.83, "counting")


@pytest.mark.parametrize("now", ["unavailable", "unknown"])
async def test_e11_unavailable_or_unknown_with_nothing_held_is_waiting(
    hass: HomeAssistant, set_up, day, now: str
) -> None:
    # As the iPhone app before the day's first sample, and Withings after midnight.
    hass.states.async_set(GARMIN, now)
    await set_up(anna())
    assert (await day())["activity"] == figures(None, 0, 0, "waiting")
    await reading(hass, 300)
    assert (await day())["activity"]["measured"] == 300


async def test_a_lower_reading_keeps_the_higher_one(hass: HomeAssistant, set_up, day) -> None:
    await reading(hass, 906)
    await set_up(anna())
    await reading(hass, 500)
    assert (await day())["activity"]["measured"] == 906


async def test_a_restart_mid_day_keeps_today_s_figure(hass: HomeAssistant, set_up, day) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await reading(hass, "unavailable")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await day())["activity"] == figures(906, 680, 435.83, "unavailable")
    # A phone that restarts from 0 doesn't lower it either.
    await reading(hass, 0)
    assert (await day())["activity"]["measured"] == 906


# The spec's units table, runtime column: the sensor's state and attributes,
# then the kcal measured, or None when it doesn't count.
WITHINGS = {"unit_of_measurement": "calories", "state_class": "total"}
ENERGY = {"device_class": "energy"}
UNITS = {
    "kcal, Garmin": ("906", {}, 906),
    "kcal, energy": ("906", ENERGY, 906),
    "calories, Withings": ("906", WITHINGS | {"last_reset": f"{TODAY}T00:00:00+00:00"}, 906),
    "calories, reset before midnight": (
        "906",
        WITHINGS | {"last_reset": f"{YESTERDAY}T23:59:59+00:00"},
        None,
    ),
    # Naive, so in Home Assistant's time zone.
    "reset at midnight, no time zone": ("906", {"last_reset": f"{TODAY}T00:00:00"}, 906),
    "reset that is not a time": ("906", {"last_reset": "today"}, None),
    "E5 kJ": ("3790", {"unit_of_measurement": "kJ"}, 3790 / 4.184),
    "kJ, energy": ("3790", {"unit_of_measurement": "kJ"} | ENERGY, 3790 / 4.184),
    "W": ("120", {"unit_of_measurement": "W"}, None),
    "cal": ("906000", {"unit_of_measurement": "cal"} | ENERGY, None),
    "no unit": ("906", {"unit_of_measurement": None}, None),
    "below 0": ("-5", {}, None),
    "not a number": ("nan", {}, None),
    "infinite": ("inf", {}, None),
    "0": ("0", {}, 0),
}


@pytest.mark.parametrize(("value", "attributes", "measured"), UNITS.values(), ids=UNITS)
async def test_the_units_table_at_runtime(
    hass: HomeAssistant,
    set_up,
    day,
    value: str,
    attributes: dict[str, Any],
    measured: float | None,
) -> None:
    await set_up(anna())
    await reading(hass, value, **attributes)
    activity = (await day())["activity"]
    if measured is None:
        assert (activity["measured"], activity["status"]) == (None, "waiting")
    else:
        assert activity["measured"] == pytest.approx(measured, abs=0.005)


async def test_a_unit_changed_after_saving_is_read_in_its_new_unit(
    hass: HomeAssistant, set_up, day
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    # 4,000 kJ is 956 kcal.
    await reading(hass, 4000, unit_of_measurement="kJ")
    assert (await day())["activity"]["measured"] == pytest.approx(956.02, abs=0.005)
    await reading(hass, 4100, unit_of_measurement="W")
    activity = (await day())["activity"]
    assert activity["measured"] == pytest.approx(956.02, abs=0.005)
    assert activity["status"] == "unavailable"


# Goals


@pytest.mark.parametrize(
    ("level", "multiplier", "status"),
    [
        ("sedentary", 1.2, "counting"),
        ("light", 1.375, "counting"),
        ("moderate", 1.55, "counting"),
        ("active", 1.725, "level"),
        ("very_active", 1.9, "level"),
    ],
)
async def test_the_activity_level_is_a_floor(
    hass: HomeAssistant, set_up, day, level: str, multiplier: float, status: str
) -> None:
    await reading(hass, 906)
    await set_up(anna(activity=level))
    allowed = 1395.25 * (multiplier - 1.2)
    added = max(0, 680 - allowed)
    found = await day()
    assert found["activity"]["allowed"] == pytest.approx(allowed, abs=0.005)
    assert found["activity"]["added"] == pytest.approx(added, abs=0.005)
    assert found["activity"]["status"] == status
    assert found["goals"]["kcal"] == round(1395.25 * multiplier - 550 + added)


async def test_share_and_cap_follow_the_person(hass: HomeAssistant, set_up, day) -> None:
    # 50% of 906 is 453, to the nearest 10 is 450, over a cap of 300.
    await reading(hass, 906)
    await set_up(anna(active_calories_share=50, active_calories_cap=300))
    activity = (await day())["activity"]
    assert (activity["share"], activity["cap"], activity["counted"]) == (50, 300, 300)
    assert activity["added"] == 55.83
    assert activity["status"] == "capped"


async def test_a_weight_changes_what_today_s_activity_adds(
    hass: HomeAssistant, set_up, day, hass_ws_client: WebSocketGenerator
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    client = await subscribed(hass, hass_ws_client)
    await entry.runtime_data.data.async_set_weight(
        entry.runtime_data.data.people["anna"], TODAY, 60
    )
    # One change, announced once.
    assert (await client.receive_json())["event"] == {"person": "anna", "days": []}
    resting = 1395.25 - 100
    found = await day()
    assert found["activity"]["allowed"] == pytest.approx(resting * 0.175, abs=0.005)
    assert found["goals"]["kcal"] == round(resting * 1.375 - 550 + 680 - resting * 0.175)


# Sensors


async def test_the_sensors_take_the_goal_and_the_activity_from_one_moment(
    hass: HomeAssistant, set_up
) -> None:
    await reading(hass, 120)
    entry = await set_up(anna())
    data = entry.runtime_data.data
    real = FitnessData.async_burn
    landed = []

    async def burn_as_a_reading_lands(self: FitnessData, *args: Any) -> float:
        # A reading that raises the goal, while the sensors' figures are read;
        # not during a write, which holds the lock the reading waits for.
        if not landed and not self._write_lock.locked():
            landed.append(True)
            new = State(GARMIN, "906", KCAL)
            await data.async_sensor_reading(data.people["anna"], new, None)
        return await real(self, *args)

    with patch.object(FitnessData, "async_burn", burn_as_a_reading_lands):
        figures = await entry.runtime_data.coordinators["anna"]._async_update_data()
    assert landed
    # Both from before it, or the goal sensor would report 1,368 less 436.
    assert (figures.goals.kcal, figures.added) == (BASE, 0)


async def test_the_activity_sensor_reports_what_activity_added(hass: HomeAssistant, set_up) -> None:
    await reading(hass, 906)
    await set_up(anna())
    activity = hass.states.get("sensor.anna_activity")
    assert float(activity.state) == 435.83
    assert activity.attributes == {
        "state_class": "total",
        "last_reset": f"{TODAY}T00:00:00+00:00",
        "unit_of_measurement": "kcal",
        "friendly_name": "Anna Activity",
        "measured": 906,
        "counted": 680,
        "share": 75,
        "cap": 1500,
        "source": GARMIN,
        "status": "counting",
    }
    # The macro goals keep the total's split.
    assert state(hass, "sensor.anna_protein_goal") == round(1804 * 0.2 / 4, 1)


async def test_the_activity_sensor_is_there_only_while_the_box_is_ticked(
    hass: HomeAssistant, set_up
) -> None:
    entry = await set_up(anna(active_calories_entity=None))
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", "metron", "anna_activity")
    assert hass.states.get("sensor.anna_activity").attributes["source"] == "action"

    subentry = next(iter(entry.subentries.values()))
    data = {**subentry.data, "active_calories_enabled": False}
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_activity") is None
    assert registry.async_get_entity_id("sensor", "metron", "anna_activity") is None
    assert state(hass, "sensor.anna_calorie_goal") == BASE


async def test_a_person_saved_before_active_calories_loads_with_the_defaults(
    hass: HomeAssistant, entry: MockConfigEntry, day
) -> None:
    debora = entry.runtime_data.data.people["debora"]
    assert (
        debora.active_calories_enabled,
        debora.active_calories_entity,
        debora.active_calories_share,
        debora.active_calories_cap,
    ) == (False, None, 75, 1500)
    assert (await day(who="debora"))["activity"] is None
    assert hass.states.get("sensor.debora_activity") is None


# Changes to the sensor and the box


async def test_e9_choosing_another_sensor_restarts_today_s_figure(
    hass: HomeAssistant, set_up, day
) -> None:
    await reading(hass, 906)
    await reading(hass, 120, entity=GARMIN_2)
    entry = await set_up(anna())
    result = await _edit(hass, entry, "Anna")
    done = await _submit(hass, result, TICKED | {"active_calories_entity": GARMIN_2})
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    activity = (await day())["activity"]
    assert (activity["source"], activity["measured"]) == (GARMIN_2, 120)
    # The old sensor is no longer read.
    await reading(hass, 2000)
    assert (await day())["activity"]["measured"] == 120


@pytest.mark.parametrize(
    ("changes", "activity"),
    [
        ({"active_calories_enabled": False, "active_calories_entity": None}, None),
        ({"active_calories_entity": None}, {"source": "action", "status": "waiting"}),
    ],
    ids=["unticked", "sensor cleared"],
)
async def test_unticking_or_clearing_the_sensor_drops_today_s_activity_only(
    hass: HomeAssistant,
    set_up,
    day,
    freezer: FrozenDateTimeFactory,
    changes: dict[str, Any],
    activity: dict[str, Any] | None,
) -> None:
    freezer.move_to(f"{YESTERDAY}T12:00:00+00:00")
    await reading(hass, 500)
    entry = await set_up(anna())
    freezer.move_to(f"{TODAY}T12:00:00+00:00")
    await reading(hass, 906)
    await hass.async_block_till_done()
    assert (await day())["goals"]["kcal"] == 1804

    subentry = next(iter(entry.subentries.values()))
    data = {k: v for k, v in (subentry.data | changes).items() if v is not None}
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()
    found = await day()
    if activity is None:
        assert found["activity"] is None
    else:
        assert {k: found["activity"][k] for k in activity} == activity
        assert found["activity"]["measured"] is None
    assert found["goals"]["kcal"] == BASE
    # Yesterday keeps its row and its goal.
    past = await day(YESTERDAY)
    assert past["activity"]["measured"] == 500
    assert past["goals"]["kcal"] == round(1368.46875 + 380 - ALLOWED)


async def test_no_sensor_is_read_while_the_box_is_unticked(
    hass: HomeAssistant, set_up, day
) -> None:
    # Not a combination the form saves: the box alone decides.
    await reading(hass, 906)
    await set_up(anna(active_calories_enabled=False))
    await reading(hass, 1000)
    assert (await day())["activity"] is None
    assert (await day())["goals"]["kcal"] == BASE


async def test_the_sensor_is_read_only_while_the_entry_is_loaded(
    hass: HomeAssistant, set_up
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    calls = []
    real = FitnessData.async_sensor_reading

    async def counted(self: FitnessData, *args: Any) -> None:
        calls.append(args[1].state)
        await real(self, *args)

    with patch.object(FitnessData, "async_sensor_reading", counted):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        # Once as it set up again, then once for the new reading: the
        # listener from before the reload is gone.
        await reading(hass, 950)
        assert calls == ["906", "950"]
        assert await hass.config_entries.async_unload(entry.entry_id)
        await reading(hass, 960)
        assert calls == ["906", "950"]


# While Home Assistant starts


async def started(hass: HomeAssistant) -> None:
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


async def test_a_sensor_with_no_state_is_waiting_until_home_assistant_has_started(
    hass: HomeAssistant, set_up, day, hass_ws_client: WebSocketGenerator
) -> None:
    # Metron set up before the watch's integration has.
    hass.set_state(CoreState.starting)
    await set_up(anna())
    assert (await day())["activity"] == figures(None, 0, 0, "waiting")
    assert hass.states.get("sensor.anna_activity").attributes["status"] == "waiting"
    client = await subscribed(hass, hass_ws_client)

    # Started, and still none: missing, and the cards hear of it.
    await started(hass)
    assert (await client.receive_json())["event"] == {"person": "anna", "days": []}
    assert (await day())["activity"] == figures(None, 0, 0, "missing")
    assert hass.states.get("sensor.anna_activity").attributes["status"] == "missing"


async def test_a_sensor_that_appears_while_home_assistant_starts_counts(
    hass: HomeAssistant, set_up, day
) -> None:
    hass.set_state(CoreState.starting)
    await set_up(anna())
    await reading(hass, 906)
    assert (await day())["activity"] == figures(906, 680, 435.83, "counting")
    await started(hass)
    assert (await day())["activity"] == figures(906, 680, 435.83, "counting")


async def test_a_held_figure_is_unavailable_until_home_assistant_has_started(
    hass: HomeAssistant, set_up, day
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna())
    # Home Assistant restarts, and Metron sets up before the watch's integration.
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_remove(GARMIN)
    hass.set_state(CoreState.starting)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await day())["activity"] == figures(906, 680, 435.83, "unavailable")
    await started(hass)
    assert (await day())["activity"] == figures(906, 680, 435.83, "missing")


# Telling the cards


async def test_midnight_tells_the_cards(
    hass: HomeAssistant, set_up, freezer: FrozenDateTimeFactory, hass_ws_client
) -> None:
    await reading(hass, 906)
    await set_up(anna())
    client = await subscribed(hass, hass_ws_client)
    await midnight(hass, freezer)
    assert (await client.receive_json())["event"] == {"person": "anna", "days": []}


async def test_a_reading_that_changes_nothing_tells_no_one(
    hass: HomeAssistant, set_up, day, hass_ws_client
) -> None:
    await reading(hass, 906)
    entry = await set_up(anna(), person("Nora"))
    client = await subscribed(hass, hass_ws_client)
    await reading(hass, 906, friendly_name="Garmin")
    await reading(hass, 500)
    data = entry.runtime_data.data
    await data.async_set_weight(data.people["nora"], TODAY, 60)
    # Nora's weight is the first thing the subscriber hears of.
    assert (await client.receive_json())["event"] == {"person": "nora", "days": []}


async def test_a_reload_tells_the_cards_about_everyone(
    hass: HomeAssistant, set_up, hass_ws_client
) -> None:
    entry = await set_up(anna(), person("Nora"))
    client = await subscribed(hass, hass_ws_client)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    heard = {(await client.receive_json())["event"]["person"] for _ in range(2)}
    assert heard == {"anna", "nora"}
