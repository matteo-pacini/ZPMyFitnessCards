"""Sensors for each person: today's food, goals and weight."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import goals as g
from .const import DOMAIN, MEALS, NUTRIENTS
from .coordinator import PersonCoordinator, Today

KCAL = "kcal"
GRAMS = "g"


@dataclass(frozen=True, kw_only=True)
class FitnessSensorDescription(SensorEntityDescription):
    """A sensor and how to read it from today's figures."""

    value: Callable[[Today, PersonCoordinator], float]
    attributes: Callable[[Today, PersonCoordinator], dict[str, Any]] | None = None
    # A total of today's entries, which starts again from 0 at midnight.
    daily_total: bool = False


def _daily(key: str, unit: str) -> FitnessSensorDescription:
    return FitnessSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0 if unit == KCAL else 1,
        value=lambda t, _c: round(t.sums[key], 2),
        daily_total=True,
    )


def _weight_attributes(t: Today, c: PersonCoordinator) -> dict[str, Any]:
    p = c.person
    return {
        **g.band_limits(p.height_cm),
        "bmi_band": g.bmi_band(t.weight_kg, p.height_cm),
        "goal_weight_kg": p.goal_weight_kg,
        "height_cm": p.height_cm,
        "weighed_on": t.weighed_on,
    }


def _goal(key: str, unit: str, field: str) -> FitnessSensorDescription:
    return FitnessSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda t, _c: getattr(t.goals, field),
    )


SENSORS: tuple[FitnessSensorDescription, ...] = (
    *(
        _daily(f"{n if n != 'kcal' else 'calories'}_today", KCAL if n == "kcal" else GRAMS)
        for n in NUTRIENTS
    ),
    *(_daily(f"{meal}_calories", KCAL) for meal in MEALS),
    FitnessSensorDescription(
        key="calories_remaining",
        translation_key="calories_remaining",
        native_unit_of_measurement=KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda t, _c: round(t.goals.kcal - t.sums["calories_today"], 2),
    ),
    _goal("calorie_goal", KCAL, "kcal"),
    _goal("protein_goal", GRAMS, "protein"),
    _goal("carbs_goal", GRAMS, "carbs"),
    _goal("fat_goal", GRAMS, "fat"),
    FitnessSensorDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda t, _c: t.weight_kg,
        attributes=_weight_attributes,
    ),
    FitnessSensorDescription(
        key="weight_change",
        translation_key="weight_change",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda t, c: round(t.weight_kg - c.person.start_weight_kg, 2),
    ),
    FitnessSensorDescription(
        key="daily_burn",
        translation_key="daily_burn",
        native_unit_of_measurement=KCAL,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda t, _c: round(t.burn),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add each person's sensors to their own device."""
    for coordinator in entry.runtime_data.coordinators.values():
        async_add_entities(
            [FitnessSensor(coordinator, description) for description in SENSORS],
            config_subentry_id=coordinator.person.subentry_id,
        )


class FitnessSensor(CoordinatorEntity[PersonCoordinator], SensorEntity):
    """One of a person's figures."""

    entity_description: FitnessSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: PersonCoordinator, description: FitnessSensorDescription):
        super().__init__(coordinator)
        self.entity_description = description
        person = coordinator.person
        # Keyed by the person's key, not their sub-entry, so a person removed
        # and added again keeps their entities and history.
        self._attr_unique_id = f"{person.key}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, person.key)},
            name=person.name,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float:
        return self.entity_description.value(self.coordinator.data, self.coordinator)

    @property
    def last_reset(self) -> datetime | None:
        if not self.entity_description.daily_total:
            return None
        return dt_util.start_of_local_day(self.coordinator.data.day)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(self.coordinator.data, self.coordinator)
