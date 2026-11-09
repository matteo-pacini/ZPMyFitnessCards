"""Adding the integration and its people."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness.const import DOMAIN, SUBENTRY_PERSON


async def test_adds_the_integration_once(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ZPMyFitnessCards"

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def _add_person(hass: HomeAssistant, entry: MockConfigEntry, name: str) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], {"name": name})


async def test_adds_a_person(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add_person(hass, entry, "  Debora ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.subentry_type == SUBENTRY_PERSON
    assert subentry.title == "Debora"
    assert subentry.data == {"name": "Debora"}


async def test_rejects_a_name_another_person_has(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _add_person(hass, entry, "Debora")
    result = await _add_person(hass, entry, "DEBORA")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_taken"}
    assert len(entry.subentries) == 1


async def test_rejects_an_empty_name(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add_person(hass, entry, "   ")
    assert result["errors"] == {"name": "name_empty"}
    assert not entry.subentries
