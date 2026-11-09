"""Adding the integration, and adding, changing and erasing people."""

from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness.const import DOMAIN, SUBENTRY_PERSON

from .conftest import person

FORM = {k: v for k, v in person().items() if k != "key"}


async def test_adds_the_integration_once(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

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
