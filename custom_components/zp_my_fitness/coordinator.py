"""Today's figures for one person, which the sensors show."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

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
    goals: g.Goals
    weight_kg: float
    weighed_on: str | None
    burn: float


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
        return Today(
            day=day,
            sums=day_sums(meals.get(day.isoformat(), {})),
            goals=await self.fitness.async_refresh_goals(self.person),
            weight_kg=weight,
            weighed_on=weighed_on,
            burn=await self.fitness.async_burn(self.person, day),
        )
