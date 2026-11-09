"""Setting up the integration: the cards' file and the websocket commands."""

from homeassistant.config_entries import SOURCE_USER, ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.zp_my_fitness import CARDS_FILE
from custom_components.zp_my_fitness.const import CARDS_URL, DOMAIN, SUBENTRY_PERSON


async def test_serves_the_cards(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    response = await client.get(CARDS_URL)
    assert response.status == 200
    assert await response.text() == CARDS_FILE.read_text()


async def test_lists_people(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ZPMyFitnessCards",
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_PERSON,
                title="Matteo",
                data={"name": "Matteo"},
                unique_id=None,
                subentry_id="p1",
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_PERSON,
                title="Debora",
                data={"name": "Debora"},
                unique_id=None,
                subentry_id="p2",
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": f"{DOMAIN}/people"})
    response = await ws.receive_json()
    assert response["success"]
    assert response["result"] == [{"id": "p1", "name": "Matteo"}, {"id": "p2", "name": "Debora"}]


async def test_lists_a_person_added_after_setup(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    await hass.config_entries.subentries.async_configure(result["flow_id"], {"name": "Nora"})
    await hass.async_block_till_done()

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": f"{DOMAIN}/people"})
    response = await ws.receive_json()
    assert [p["name"] for p in response["result"]] == ["Nora"]
