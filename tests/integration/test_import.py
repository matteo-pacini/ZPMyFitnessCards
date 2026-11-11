"""Importing a person's history from the recorder's statistics of older sensors."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.fork_and_scale.const import SUBENTRY_PERSON

LONDON = ZoneInfo("Europe/London")


def hour(day: int, at: int) -> datetime:
    return datetime(2026, 11, day, at, tzinfo=LONDON)


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance: None) -> None:
    """Prepare the recorder's database before Home Assistant starts, as it requires."""


@pytest.fixture
async def old_sensors(hass: HomeAssistant, recorder_mock: Recorder) -> None:
    """An old weight helper and an old calories counter, with their statistics."""
    hass.states.async_set(
        "sensor.old_weight",
        "89",
        {"state_class": "measurement", "unit_of_measurement": "kg", "device_class": "weight"},
    )
    hass.states.async_set(
        "sensor.old_calories", "1700", {"state_class": "total", "unit_of_measurement": "kcal"}
    )
    hass.states.async_set("sensor.no_history", "1", {"unit_of_measurement": "kg"})
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
        [
            {"start": hour(5, 10), "mean": 90, "min": 90, "max": 90},
            {"start": hour(5, 11), "mean": 91, "min": 91, "max": 91},
            {"start": hour(7, 10), "mean": 89, "min": 89, "max": 89},
        ],
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
            {"start": hour(6, 12), "state": 0, "sum": 0},
            {"start": hour(7, 12), "state": 500, "sum": 500},
            {"start": hour(8, 12), "state": 1700, "sum": 1700},
        ],
    )
    await async_wait_recording_done(hass)


async def _import(hass: HomeAssistant, entry: MockConfigEntry, **fields) -> dict:
    debora = next(s for s in entry.subentries.values() if s.title == "Debora")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": debora.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "import_history"}
    )
    assert result["step_id"] == "import_history"
    return await hass.config_entries.subentries.async_configure(result["flow_id"], fields)


async def test_imports_daily_weights_and_calorie_totals_once(
    hass: HomeAssistant, old_sensors: None, entry: MockConfigEntry, ws
) -> None:
    # A weight logged by hand wins over the imported one.
    await ws("weight/set", person="debora", day="2026-11-07", kg=88)

    done = await _import(
        hass, entry, weight_sensor="sensor.old_weight", calories_sensor="sensor.old_calories"
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "imported"
    assert done["description_placeholders"] == {"weights": "1", "days": "2"}

    weights = (await ws("weights", person="debora"))["result"]
    assert weights == [{"day": "2026-11-05", "kg": 90.5}, {"day": "2026-11-07", "kg": 88}]
    days = (await ws("days", person="debora", start="2026-11-06", end="2026-11-08"))["result"]
    imported = {d["day"]: d["meals"].get("snacks", {}).get("kcal") for d in days["days"]}
    assert imported == {"2026-11-06": None, "2026-11-07": 500, "2026-11-08": 1200}
    entries = (await ws("day", person="debora", day="2026-11-08"))["result"]["entries"]
    assert [(e["name"], e["meal"]) for e in entries] == [("Imported total", "snacks")]

    again = await _import(
        hass, entry, weight_sensor="sensor.old_weight", calories_sensor="sensor.old_calories"
    )
    assert again["description_placeholders"] == {"weights": "0", "days": "0"}


async def test_asks_for_a_sensor_with_statistics(
    hass: HomeAssistant, old_sensors: None, entry: MockConfigEntry
) -> None:
    result = await _import(hass, entry)
    assert result["errors"] == {"base": "nothing_selected"}
    result = await _import(hass, entry, weight_sensor="sensor.no_history")
    assert result["errors"] == {"weight_sensor": "no_statistics"}
