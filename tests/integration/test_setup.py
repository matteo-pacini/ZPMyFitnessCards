"""Setting up and unloading the integration."""

import os
from unittest.mock import patch

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


async def test_registers_the_cards_with_the_frontend_when_it_runs(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    with patch("custom_components.zp_my_fitness.add_extra_js_url") as add:
        assert await hass.config_entries.async_setup(entry.entry_id)
    add.assert_called_once_with(hass, f"{CARDS_URL}?v=0.1.0")


async def test_leaves_the_frontend_alone_when_it_does_not_run(hass: HomeAssistant) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    with patch("custom_components.zp_my_fitness.add_extra_js_url") as add:
        assert await hass.config_entries.async_setup(entry.entry_id)
    add.assert_not_called()


async def test_closes_the_database_when_home_assistant_stops(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    db = entry.runtime_data.data.db
    with patch.object(db, "close", wraps=db.close) as close:
        await hass.async_stop()
    close.assert_called_once()
