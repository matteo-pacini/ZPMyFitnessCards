"""Setting up and unloading the integration."""

import os
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.fork_and_scale import CARDS_FILE
from custom_components.fork_and_scale.const import (
    CARDS_URL,
    DB_FILE,
    LEGACY_DB_FILE,
    SUBENTRY_PERSON,
)
from custom_components.fork_and_scale.coordinator import PersonCoordinator
from custom_components.fork_and_scale.data import adopt_legacy_database
from custom_components.fork_and_scale.db import Database, sqlite_url

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
    with patch("custom_components.fork_and_scale.add_extra_js_url") as add:
        assert await hass.config_entries.async_setup(entry.entry_id)
    add.assert_called_once_with(hass, f"{CARDS_URL}?v=0.3.0")


async def test_leaves_the_frontend_alone_when_it_does_not_run(hass: HomeAssistant) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    with patch("custom_components.fork_and_scale.add_extra_js_url") as add:
        assert await hass.config_entries.async_setup(entry.entry_id)
    add.assert_not_called()


async def test_closes_the_database_when_home_assistant_stops(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    db = entry.runtime_data.data.db
    with patch.object(db, "close", wraps=db.close) as close:
        await hass.async_stop()
    close.assert_called_once()


async def test_a_person_added_while_setting_up_is_loaded_once_setup_ends(
    hass: HomeAssistant,
) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    first_refresh = PersonCoordinator.async_config_entry_first_refresh

    async def add_nora_meanwhile(coordinator: PersonCoordinator) -> None:
        # After setup has read its people, as when people are added one
        # after another and each reloads the entry.
        if not any(s.title == "Nora" for s in entry.subentries.values()):
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(person("Nora")),
                    subentry_type=SUBENTRY_PERSON,
                    title="Nora",
                    unique_id=None,
                ),
            )
        await first_refresh(coordinator)

    with patch.object(PersonCoordinator, "async_config_entry_first_refresh", add_nora_meanwhile):
        # Its result reports the reload that Nora started, already under way.
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.coordinators) == {"debora", "nora"}


def test_takes_over_the_files_zpmyfitnesscards_left(tmp_path) -> None:
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / f"{LEGACY_DB_FILE}{suffix}").write_text(suffix or "main")
    assert adopt_legacy_database(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        DB_FILE,
        f"{DB_FILE}-shm",
        f"{DB_FILE}-wal",
    ]
    assert (tmp_path / DB_FILE).read_text() == "main"
    # Nothing left to take over.
    assert not adopt_legacy_database(str(tmp_path))


def test_leaves_both_files_alone_when_fork_and_scale_has_its_own(tmp_path) -> None:
    (tmp_path / LEGACY_DB_FILE).write_text("old")
    (tmp_path / DB_FILE).write_text("new")
    assert not adopt_legacy_database(str(tmp_path))
    assert (tmp_path / LEGACY_DB_FILE).read_text() == "old"
    assert (tmp_path / DB_FILE).read_text() == "new"


async def test_setup_keeps_the_data_zpmyfitnesscards_left(hass: HomeAssistant) -> None:
    old = Database(sqlite_url(hass.config.path(LEGACY_DB_FILE)))
    old.open()
    old.sync_people([("debora", "Debora")])
    old.add_entry("debora", {"day": "2026-11-09", "meal": "lunch", "name": "Soup", "kcal": 250})
    old.close()
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not os.path.exists(hass.config.path(LEGACY_DB_FILE))
    db = entry.runtime_data.data.db
    assert [e["name"] for e in db.day_entries("debora", "2026-11-09")] == ["Soup"]


async def test_setup_on_postgres_leaves_an_old_sqlite_file_alone(
    hass: HomeAssistant, postgres_database: str
) -> None:
    Path(hass.config.path(LEGACY_DB_FILE)).touch()
    entry = mock_entry(person(), data={"engine": "postgresql", "db_url": postgres_database})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert os.path.exists(hass.config.path(LEGACY_DB_FILE))
    assert not os.path.exists(hass.config.path(DB_FILE))
