"""Metron: a food diary and weight tracking for each person."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from sqlalchemy.exc import OperationalError

from . import services, websocket
from .const import CARDS_URL, DOMAIN, SIGNAL_CHANGED, SIGNAL_PEOPLE, SUBENTRY_PERSON
from .coordinator import PersonCoordinator
from .data import FitnessData, Person, database_url
from .db import MIGRATIONS, Database, NewerSchemaError
from .export import ExportView

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR]

CARDS_FILE = Path(__file__).parent / "frontend" / "metron-cards.js"


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
    # Before reading the people: one added while this runs, as when people are
    # added one after another, must reload the entry again once it is set up.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    db = Database(database_url(hass, entry.data))
    try:
        await hass.async_add_executor_job(db.open)
    except NewerSchemaError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="newer_database",
            translation_placeholders={"version": str(err.version), "latest": str(len(MIGRATIONS))},
        ) from err
    except OperationalError as err:
        # As when Postgres starts after Home Assistant: Home Assistant tries again.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="database_unavailable",
            translation_placeholders={"error": str(err.orig).strip()},
        ) from err
    people = [
        Person.from_subentry(s)
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_PERSON
    ]
    await hass.async_add_executor_job(db.sync_people, [(p.key, p.name) for p in people])
    # People removed since the last setup leave their meals to everyone.
    await hass.async_add_executor_job(db.adopt_removed, [p.key for p in people])
    data = FitnessData(hass, db, people)
    coordinators = {p.key: PersonCoordinator(hass, data, p) for p in people}
    entry.runtime_data = RuntimeData(data, coordinators)

    async def close(_event: Event | None = None) -> None:
        await hass.async_add_executor_job(db.close)

    entry.async_on_unload(close)
    # Home Assistant does not unload entries when it stops, so close then too.
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, close))

    # Active calories sensors, read as they change, and once now, before the
    # sensors' first figures.
    sensors = {
        p.key: p.active_calories_entity
        for p in people
        if p.active_calories_enabled and p.active_calories_entity
    }

    @callback
    def reading(key: str, event: Event[EventStateChangedData]) -> None:
        new, old = event.data["new_state"], event.data["old_state"]
        hass.async_create_task(data.async_sensor_reading(data.people[key], new, old))

    for key, sensor in sensors.items():
        entry.async_on_unload(async_track_state_change_event(hass, sensor, partial(reading, key)))
        state = hass.states.get(sensor)
        await data.async_sensor_reading(data.people[key], state, state)

    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    @callback
    def changed(person: str | None, _days: set[str]) -> None:
        if person in coordinators:
            hass.async_create_task(coordinators[person].async_refresh())

    async def new_day(coordinator: PersonCoordinator) -> None:
        if sensor := sensors.get(coordinator.person.key):
            state = hass.states.get(sensor)
            await data.async_sensor_reading(coordinator.person, state, state)
        await coordinator.async_refresh()
        # Today shows yesterday's base until something changes it, so its goals
        # may need no write: tell the cards all the same.
        async_dispatcher_send(hass, SIGNAL_CHANGED, coordinator.person.key, set())

    @callback
    def midnight(_now: datetime) -> None:
        for coordinator in coordinators.values():
            hass.async_create_task(new_day(coordinator))

    # A reload follows every change to a person, which can change what their
    # day shows, such as whether it has activity, without a write.
    for key in coordinators:
        async_dispatcher_send(hass, SIGNAL_CHANGED, key, set())
    # The people themselves may be why: one added, changed or removed. No
    # person's change says that someone is new, or gone.
    async_dispatcher_send(hass, SIGNAL_PEOPLE)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CHANGED, changed))
    entry.async_on_unload(async_track_time_change(hass, midnight, hour=0, minute=0, second=0))

    @callback
    def started(_hass: HomeAssistant) -> None:
        # Until now a sensor with no state might still have been setting up;
        # one that has none yet is missing.
        for key, sensor in sensors.items():
            if hass.states.get(sensor) is None:
                async_dispatcher_send(hass, SIGNAL_CHANGED, key, set())

    entry.async_on_unload(async_at_started(hass, started))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FitnessConfigEntry) -> bool:
    """Unload the sensors; the database closes with the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: FitnessConfigEntry) -> None:
    """Reload after a person is added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)
