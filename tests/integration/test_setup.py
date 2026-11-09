"""Setting up and unloading the integration."""

import os

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.zp_my_fitness import CARDS_FILE
from custom_components.zp_my_fitness.const import CARDS_URL, DB_FILE

from .conftest import mock_entry, person


async def test_serves_the_cards(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    response = await client.get(CARDS_URL)
    assert response.status == 200
    assert await response.text() == CARDS_FILE.read_text()


async def test_sqlite_keeps_the_database_in_the_config_folder(hass: HomeAssistant) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.data.db.url == f"sqlite:///{hass.config.path(DB_FILE)}"
    assert os.path.exists(hass.config.path(DB_FILE))


async def test_unloads_and_reloads_keeping_data(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await ws("weight/set", person="debora", day="2026-11-09", kg=68)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.debora_weight").state) == 68
