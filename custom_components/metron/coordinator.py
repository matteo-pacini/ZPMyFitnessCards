"""Today's figures for one person, which the sensors show."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import goals as g
from .const import DOMAIN
from .data import FitnessData, Person, day_sums, today

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Today:
    """One person's figures for one day."""

    day: date
    sums: dict[str, float]
    # Including what activity added.
    goals: g.Goals
    weight_kg: float
    weighed_on: str | None
    # Before any activity.
    burn: float
    # As metron/day gives it: None unless the box is ticked.
    activity: dict[str, Any] | None

    @property
    def added(self) -> float:
        """The kcal activity added to today's goal."""
        return self.activity["added"] if self.activity else 0.0


class PersonCoordinator(DataUpdateCoordinator[Today]):
    """Works out a person's figures when their data changes, and at midnight."""

    def __init__(self, hass: HomeAssistant, data: FitnessData, person: Person) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {person.name}",
            update_interval=None,
            always_update=False,
        )
        self.fitness = data
        self.person = person

    async def _async_update_data(self) -> Today:
        day = today()
        meals = await self.fitness.async_read(
            self.fitness.db.meal_totals, self.person.key, day.isoformat(), day.isoformat()
        )
        weight, weighed_on = await self.fitness.async_weight(self.person, day)
        # Together, or the calorie goal sensor could take a reading's activity
        # off a goal from before it.
        goals, activity = await self.fitness.async_refresh_goals(self.person)
        return Today(
            day=day,
            sums=day_sums(meals.get(day.isoformat(), {})),
            goals=goals,
            weight_kg=weight,
            weighed_on=weighed_on,
            burn=await self.fitness.async_burn(self.person, day),
            activity=activity,
        )
