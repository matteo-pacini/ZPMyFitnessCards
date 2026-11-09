"""Adding the integration, and adding, changing and erasing people."""

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness.const import DOMAIN, SUBENTRY_PERSON

from .conftest import mock_entry, person

FORM = {k: v for k, v in person().items() if k != "key"}


async def test_adds_the_integration_once_on_sqlite_by_default(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"engine": "sqlite"}

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def _add(hass: HomeAssistant, entry: MockConfigEntry, **fields: Any) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**FORM, **fields}
    )


def _people(entry: MockConfigEntry) -> dict[str, dict]:
    return {s.title: dict(s.data) for s in entry.subentries.values()}


async def test_adds_a_person_with_a_new_key(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add(hass, entry, name="  Nora ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    nora = _people(entry)["Nora"]
    assert nora["name"] == "Nora"
    assert len(nora["key"]) == 32
    assert nora["key"] not in {"debora", "matteo"}


async def test_rejects_bad_details(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add(
        hass,
        entry,
        name="DEBORA",
        birth_date="2026-11-09",
        start_date="2026-11-10",
        protein_pct=30,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "name": "name_taken",
        "birth_date": "birth_date_future",
        "start_date": "start_date_future",
        "base": "macros_not_100",
    }
    result = await _add(hass, entry, name="   ")
    assert result["errors"] == {"name": "name_empty"}


async def test_re_adding_a_removed_person_brings_their_data_back(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    debora = next(s for s in entry.subentries.values() if s.title == "Debora")
    assert hass.config_entries.async_remove_subentry(entry, debora.subentry_id)
    await hass.async_block_till_done()
    result = await _add(hass, entry, name="debora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _people(entry)["debora"]["key"] == "debora"


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, name: str) -> dict:
    subentry = next(s for s in entry.subentries.values() if s.title == name)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    return result


async def test_changes_a_person_keeping_their_key(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
    assert result["step_id"] == "edit"
    # Keeping her own name is fine; another person's is not.
    taken = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**FORM, "name": "Matteo"}
    )
    assert taken["errors"] == {"name": "name_taken"}
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**FORM, "name": "Deb", "height_cm": 166}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert _people(entry)["Deb"] | {"key": "debora"} == _people(entry)["Deb"]
    assert _people(entry)["Deb"]["height_cm"] == 166


async def test_erases_a_person_s_data_after_confirming(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await ws("weight/set", person="debora", day="2026-11-09", kg=69.5)
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "erase"}
    )
    unconfirmed = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert unconfirmed["errors"] == {"confirm": "not_confirmed"}
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert done["reason"] == "erased"
    await hass.async_block_till_done()
    assert (await ws("weights", person="debora"))["result"] == []
    # The person stays.
    assert "Debora" in _people(entry)


async def _postgres_flow(hass: HomeAssistant, url: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"engine": "postgresql"}
    )
    assert result["step_id"] == "postgresql"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"db_url": url})


async def test_adds_the_integration_on_postgres(
    hass: HomeAssistant, postgres_database: str
) -> None:
    result = await _postgres_flow(hass, f" {postgres_database} ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"engine": "postgresql", "db_url": postgres_database}
    await hass.async_block_till_done()
    assert result["result"].runtime_data.data.db.url == postgres_database


async def test_rejects_postgres_urls_that_do_not_work(
    hass: HomeAssistant, postgres_server: str
) -> None:
    result = await _postgres_flow(hass, "mysql://user@host/db")
    assert result["errors"] == {"db_url": "invalid_url"}
    result = await _postgres_flow(hass, "postgresql://postgres@/nothing?host=/nonexistent")
    assert result["errors"] == {"db_url": "cannot_connect"}
    result = await _postgres_flow(hass, postgres_server.format(database="no_such_database"))
    assert result["errors"] == {"db_url": "cannot_connect"}


async def test_says_when_the_postgres_driver_is_missing(hass: HomeAssistant) -> None:
    with patch("custom_components.zp_my_fitness.config_flow.make_engine", side_effect=ImportError):
        result = await _postgres_flow(hass, "postgresql://user@host/db")
    assert result["errors"] == {"db_url": "no_driver"}


async def test_rejects_a_postgres_url_naming_an_unknown_driver(hass: HomeAssistant) -> None:
    result = await _postgres_flow(hass, "postgresql+nosuchdriver://user@host/db")
    assert result["errors"] == {"db_url": "invalid_url"}


async def test_a_person_added_while_unloaded_gets_a_new_key(hass: HomeAssistant) -> None:
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await _add(hass, entry, name="Nora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(_people(entry)["Nora"]["key"]) == 32


@pytest.mark.parametrize("step", ["import_history", "erase"])
async def test_steps_that_need_the_database_wait_for_it_to_load(
    hass: HomeAssistant, step: str
) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_importing_history_needs_the_recorder(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "import_history"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_recorder"
