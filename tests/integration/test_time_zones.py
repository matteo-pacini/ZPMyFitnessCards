"""Days follow Home Assistant's time zone, never UTC.

The other tests run in London in November, where the two are the same. These
run in Los Angeles at 19:00 on Monday 9 November, already the 10th in UTC, so
a day taken from UTC instead of the local clock shows. Los Angeles leaves
summer time on 1 November 2026. History is imported in Sydney, ahead of UTC.
"""

from datetime import datetime
from unittest.mock import MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.metron.const import SUBENTRY_PERSON

from .conftest import mock_entry, person
from .test_activity import GARMIN, KCAL, anna
from .test_config_flow import _add, _fields
from .test_import import _import
from .test_services import act

LOS_ANGELES = ZoneInfo("America/Los_Angeles")
EVENING = "2026-11-10T03:00:00+00:00"


@pytest.fixture(autouse=True)
async def los_angeles(hass: HomeAssistant, freezer: FrozenDateTimeFactory, london: None) -> None:
    await hass.config.async_set_time_zone("America/Los_Angeles")
    freezer.move_to(EVENING)


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance: None) -> None:
    """Prepare the recorder's database before Home Assistant starts, as it requires."""


async def test_today_is_the_local_day(hass: HomeAssistant, entry: MockConfigEntry, ws) -> None:
    lunch = {"person": "debora", "meal": "lunch", "name": "Soup", "kcal": 300}
    assert not (await ws("entry/add", **lunch, day="2026-11-10"))["success"]
    assert (await ws("entry/add", **lunch, day="2026-11-09"))["success"]
    assert not (await ws("weight/set", person="debora", day="2026-11-10", kg=69))["success"]
    assert (await act(hass, "get_day"))["day"] == "2026-11-09"
    calories = hass.states.get("sensor.debora_calories_today")
    assert float(calories.state) == 300
    assert calories.attributes["last_reset"] == "2026-11-09T00:00:00-08:00"


async def test_the_person_form_takes_the_local_day(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    assert _fields(result)["start_date"][1] == "2026-11-09"
    result = await _add(hass, entry, name="Nora", birth_date="2026-11-09")
    assert result["errors"] == {"birth_date": "birth_date_future"}


async def test_on_the_day_summer_time_ends_totals_start_at_its_local_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # Noon on 1 November, after the clocks went back at 02:00.
    freezer.move_to("2026-11-01T20:00:00+00:00")
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calories = "sensor.debora_calories_today"
    assert hass.states.get(calories).attributes["last_reset"] == "2026-11-01T00:00:00-07:00"

    freezer.move_to("2026-11-02T08:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(calories).attributes["last_reset"] == "2026-11-02T00:00:00-08:00"


async def test_a_past_day_s_statistics_are_shifted_from_its_local_last_hour(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    recorder = MagicMock()
    hass.config.components.add("recorder")
    with patch("homeassistant.components.recorder.get_instance", return_value=recorder):
        await ws(
            "entry/add", person="debora", day="2026-11-07", meal="lunch", name="Pasta", kcal=500
        )
        # Today's totals are the sensors' own, with nothing to correct.
        await ws(
            "entry/add", person="debora", day="2026-11-09", meal="lunch", name="Soup", kcal=100
        )
    at = datetime(2026, 11, 7, 23, tzinfo=LOS_ANGELES)
    assert recorder.async_adjust_statistics.call_args_list == [
        call("sensor.debora_calories_today", at, 500, "kcal"),
        call("sensor.debora_lunch_calories", at, 500, "kcal"),
    ]


async def test_history_is_imported_on_the_local_day_it_was_recorded(
    hass: HomeAssistant, recorder_mock: Recorder, entry: MockConfigEntry, ws
) -> None:
    # Ahead of UTC, as a daily row's local midnight falls on the UTC day before.
    await hass.config.async_set_time_zone("Australia/Sydney")
    hass.states.async_set(
        "sensor.old_weight",
        "89",
        {"state_class": "measurement", "unit_of_measurement": "kg", "device_class": "weight"},
    )
    hass.states.async_set(
        "sensor.old_calories", "1700", {"state_class": "total", "unit_of_measurement": "kcal"}
    )

    def morning(day: int) -> datetime:
        # 08:00 in Sydney: 21:00 the day before in UTC.
        return datetime(2026, 11, day, 8, tzinfo=ZoneInfo("Australia/Sydney"))

    async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.ARITHMETIC,
            "has_sum": False,
            "name": None,
            "source": "recorder",
            "statistic_id": "sensor.old_weight",
            "unit_class": "mass",
            "unit_of_measurement": "kg",
        },
        [{"start": morning(7), "mean": 88.4, "min": 88.4, "max": 88.4}],
    )
    async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": "sensor.old_calories",
            "unit_class": None,
            "unit_of_measurement": "kcal",
        },
        [
            {"start": morning(6), "state": 0, "sum": 0},
            {"start": morning(7), "state": 500, "sum": 500},
            {"start": morning(8), "state": 1700, "sum": 1700},
        ],
    )
    await async_wait_recording_done(hass)

    done = await _import(
        hass, entry, weight_sensor="sensor.old_weight", calories_sensor="sensor.old_calories"
    )
    assert done["reason"] == "imported"
    weights = (await ws("weights", person="debora"))["result"]
    assert weights == [{"day": "2026-11-07", "kg": 88.4}]
    days = (await ws("days", person="debora", start="2026-11-06", end="2026-11-09"))["result"]
    imported = {d["day"]: d["meals"].get("snacks", {}).get("kcal") for d in days["days"]}
    assert imported == {
        "2026-11-06": None,
        "2026-11-07": 500,
        "2026-11-08": 1200,
        "2026-11-09": None,
    }


async def test_e1_a_reading_from_before_local_midnight_does_not_count(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entry_data: dict,
    hass_ws_client: WebSocketGenerator,
) -> None:
    # 20:00 on the 8th here, though already the 9th in UTC.
    freezer.move_to("2026-11-09T04:00:00+00:00")
    hass.states.async_set(GARMIN, "906", KCAL)
    freezer.move_to(EVENING)
    entry = mock_entry(anna(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "metron/day", "person": "anna", "day": "2026-11-09"})
    activity = (await client.receive_json())["result"]["activity"]
    assert (activity["measured"], activity["status"]) == (None, "waiting")


async def test_e1_active_calories_count_from_local_midnight(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entry_data: dict,
    hass_ws_client: WebSocketGenerator,
) -> None:
    # Noon in Los Angeles: still the 9th in UTC too, before UTC's midnight.
    freezer.move_to("2026-11-09T20:00:00+00:00")
    hass.states.async_set(GARMIN, "906", KCAL)
    freezer.move_to(EVENING)
    entry = mock_entry(anna(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    async def activity(day: str) -> dict | None:
        await client.send_json_auto_id({"type": "metron/day", "person": "anna", "day": day})
        return (await client.receive_json())["result"]["activity"]

    assert (await activity("2026-11-09"))["measured"] == 906
    sensor = hass.states.get("sensor.anna_activity")
    assert sensor.attributes["last_reset"] == "2026-11-09T00:00:00-08:00"

    # Reset at UTC's midnight, which was 16:00 the day before here.
    hass.states.async_set(GARMIN, "1000", KCAL | {"last_reset": "2026-11-09T00:00:00+00:00"})
    await hass.async_block_till_done()
    assert (await activity("2026-11-09"))["measured"] == 906
    hass.states.async_set(GARMIN, "1000", KCAL | {"last_reset": "2026-11-09T00:00:00-08:00"})
    await hass.async_block_till_done()
    assert (await activity("2026-11-09"))["measured"] == 1000

    # Local midnight: yesterday keeps its figure, and today waits for one.
    freezer.move_to("2026-11-10T08:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    today = await activity("2026-11-10")
    assert (today["measured"], today["status"]) == (None, "waiting")
    past = await activity("2026-11-09")
    assert (past["measured"], past["status"]) == (1000, None)
