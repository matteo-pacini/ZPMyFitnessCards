"""Each person's sensors."""

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.zp_my_fitness.const import DOMAIN


def state(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


async def test_each_person_is_a_device_with_their_sensors(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert sorted(d.name for d in devices) == ["Debora", "Matteo"]
    device = next(d for d in devices if (DOMAIN, "debora") in d.identifiers)
    entities = er.async_entries_for_device(er.async_get(hass), device.id)
    assert sorted(e.entity_id for e in entities) == sorted(
        f"sensor.debora_{key}"
        for key in (
            "calories_today",
            "protein_today",
            "carbs_today",
            "fat_today",
            "fibre_today",
            "sugar_today",
            "saturated_fat_today",
            "salt_today",
            "breakfast_calories",
            "lunch_calories",
            "dinner_calories",
            "snacks_calories",
            "calories_remaining",
            "calorie_goal",
            "protein_goal",
            "carbs_goal",
            "fat_goal",
            "weight",
            "weight_change",
            "daily_burn",
        )
    )


async def test_goals_come_from_the_person(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    # Debora: 30, 165 cm, 70 kg, moderate: burns 2201 a day; losing 0.5 kg a
    # week takes 550 off.
    assert state(hass, "sensor.debora_daily_burn") == 2201
    assert state(hass, "sensor.debora_calorie_goal") == 1651
    # Grams to 0.1: 20% protein at 4 kcal/g, 50% carbs at 4, 30% fat at 9.
    assert state(hass, "sensor.debora_protein_goal") == pytest.approx(82.55, abs=0.05)
    assert state(hass, "sensor.debora_carbs_goal") == pytest.approx(206.375, abs=0.05)
    assert state(hass, "sensor.debora_fat_goal") == pytest.approx(55.03, abs=0.05)
    assert state(hass, "sensor.debora_calories_remaining") == 1651
    assert state(hass, "sensor.matteo_calorie_goal") == 1980


async def test_food_adds_up_by_nutrient_and_meal(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await ws(
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="breakfast",
        name="Oats",
        kcal=233.4,
        protein=10.1,
        carbs=39.6,
        fat=4.1,
        salt=0.01,
    )
    await ws(
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="lunch",
        name="Pasta",
        kcal=500,
        protein=18,
    )
    await ws("entry/add", person="debora", day="2026-11-08", meal="lunch", name="Old", kcal=999)
    assert state(hass, "sensor.debora_calories_today") == 733.4
    assert state(hass, "sensor.debora_protein_today") == 28.1
    assert state(hass, "sensor.debora_salt_today") == 0.01
    assert state(hass, "sensor.debora_fibre_today") == 0
    assert state(hass, "sensor.debora_breakfast_calories") == 233.4
    assert state(hass, "sensor.debora_lunch_calories") == 500
    assert state(hass, "sensor.debora_dinner_calories") == 0
    assert state(hass, "sensor.debora_calories_remaining") == 1651 - 733.4
    assert state(hass, "sensor.matteo_calories_today") == 0


async def test_daily_totals_start_again_at_midnight(
    hass: HomeAssistant, entry: MockConfigEntry, ws, freezer: FrozenDateTimeFactory
) -> None:
    await ws("entry/add", person="debora", day="2026-11-09", meal="dinner", name="Soup", kcal=300)
    attributes = hass.states.get("sensor.debora_calories_today").attributes
    assert attributes["state_class"] == "total"
    assert attributes["last_reset"] == "2026-11-09T00:00:00+00:00"

    freezer.move_to("2026-11-10T00:00:01+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "sensor.debora_calories_today") == 0
    attributes = hass.states.get("sensor.debora_calories_today").attributes
    assert attributes["last_reset"] == "2026-11-10T00:00:00+00:00"


async def test_weight_follows_the_last_weigh_in_with_bands(
    hass: HomeAssistant, entry: MockConfigEntry, ws, freezer: FrozenDateTimeFactory
) -> None:
    weight = hass.states.get("sensor.debora_weight")
    assert float(weight.state) == 70  # the starting weight
    assert weight.attributes["weighed_on"] is None
    assert weight.attributes["overweight_from_kg"] == 68.1
    assert weight.attributes["bmi_band"] == "overweight"

    await ws("weight/set", person="debora", day="2026-11-09", kg=67.5)
    weight = hass.states.get("sensor.debora_weight")
    assert float(weight.state) == 67.5
    assert weight.attributes["weighed_on"] == "2026-11-09"
    assert weight.attributes["bmi_band"] == "healthy"
    assert state(hass, "sensor.debora_weight_change") == -2.5
    # A lower weight lowers the burn, and the goal follows it.
    assert state(hass, "sensor.debora_calorie_goal") == round(
        (10 * 67.5 + 6.25 * 165 - 5 * 30 - 161) * 1.55 - 550
    )

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.debora_weight").state) == 67.5


async def test_a_typed_calorie_goal_overrides_the_suggestion(hass: HomeAssistant) -> None:
    from .conftest import mock_entry, person

    entry = mock_entry(person(calorie_goal=2000, protein_pct=30, carbs_pct=40, fat_pct=30))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor.debora_calorie_goal") == 2000
    assert state(hass, "sensor.debora_protein_goal") == 150
