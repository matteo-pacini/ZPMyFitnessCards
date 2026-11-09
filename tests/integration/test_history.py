"""Fixing a past day corrects the recorder's long-term statistics."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_past_day_changes_shift_that_day_s_sums(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    recorder = MagicMock()
    hass.config.components.add("recorder")
    with patch("homeassistant.components.recorder.get_instance", return_value=recorder):
        await ws(
            "entry/add",
            person="debora",
            day="2026-11-07",
            meal="lunch",
            name="Pasta",
            kcal=500,
            protein=18,
        )
        await ws(
            "entry/add", person="debora", day="2026-11-09", meal="lunch", name="Today", kcal=100
        )

    at = datetime(2026, 11, 7, 23, tzinfo=ZoneInfo("Europe/London"))
    calls = {c.args[0]: c.args[1:] for c in recorder.async_adjust_statistics.call_args_list}
    assert calls == {
        "sensor.debora_calories_today": (at, 500, "kcal"),
        "sensor.debora_lunch_calories": (at, 500, "kcal"),
        "sensor.debora_protein_today": (at, 18, "g"),
    }


async def test_moving_an_entry_between_past_days_shifts_both(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    added = await ws(
        "entry/add", person="debora", day="2026-11-06", meal="dinner", name="Soup", kcal=300
    )
    recorder = MagicMock()
    hass.config.components.add("recorder")
    with patch("homeassistant.components.recorder.get_instance", return_value=recorder):
        await ws("entry/update", entry_id=added["result"]["id"], day="2026-11-07")

    london = ZoneInfo("Europe/London")
    calls = {
        (c.args[0], c.args[1]): c.args[2]
        for c in recorder.async_adjust_statistics.call_args_list
        if c.args[0] == "sensor.debora_calories_today"
    }
    assert calls == {
        ("sensor.debora_calories_today", datetime(2026, 11, 6, 23, tzinfo=london)): -300,
        ("sensor.debora_calories_today", datetime(2026, 11, 7, 23, tzinfo=london)): 300,
    }
