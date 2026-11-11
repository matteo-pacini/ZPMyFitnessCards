"""ZPMyFitnessCards: a food diary and weight tracking for each person."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import services, websocket
from .const import CARDS_URL, CONF_DB_URL, DB_FILE, DOMAIN, SIGNAL_CHANGED, SUBENTRY_PERSON
from .coordinator import PersonCoordinator
from .data import FitnessData, Person
from .db import Database, sqlite_url
from .export import ExportView

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR]

CARDS_FILE = Path(__file__).parent / "frontend" / "zp-my-fitness-cards.js"


@dataclass
class RuntimeData:
    """What a loaded entry holds."""

    data: FitnessData
    coordinators: dict[str, PersonCoordinator]


type FitnessConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the cards and the export, and register the websocket commands and the actions."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(CARDS_FILE), cache_headers=True)]
    )
    if "frontend" in hass.config.components:
        # Cached for good, so the version in the URL is what makes browsers
        # fetch the cards again after an update.
        add_extra_js_url(hass, f"{CARDS_URL}?v={integration.version}")
    hass.http.register_view(ExportView())
    websocket.async_register(hass)
    services.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FitnessConfigEntry) -> bool:
    """Open the database and set up each person's sensors."""
    db = Database(entry.data.get(CONF_DB_URL) or sqlite_url(hass.config.path(DB_FILE)))
    await hass.async_add_executor_job(db.open)
    people = [
        Person.from_subentry(s)
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_PERSON
    ]
    await hass.async_add_executor_job(db.sync_people, [(p.key, p.name) for p in people])
    data = FitnessData(hass, db, people)
    coordinators = {p.key: PersonCoordinator(hass, data, p) for p in people}
    entry.runtime_data = RuntimeData(data, coordinators)

    async def close(_event: Event | None = None) -> None:
        await hass.async_add_executor_job(db.close)

    entry.async_on_unload(close)
    # Home Assistant does not unload entries when it stops, so close then too.
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, close))

    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    @callback
    def changed(person: str | None, _days: set[str]) -> None:
        if person in coordinators:
            hass.async_create_task(coordinators[person].async_refresh())

    @callback
    def midnight(_now: datetime) -> None:
        for coordinator in coordinators.values():
            hass.async_create_task(coordinator.async_refresh())

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CHANGED, changed))
    entry.async_on_unload(async_track_time_change(hass, midnight, hour=0, minute=0, second=0))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FitnessConfigEntry) -> bool:
    """Unload the sensors; the database closes with the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: FitnessConfigEntry) -> None:
    """Reload after a person is added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)
