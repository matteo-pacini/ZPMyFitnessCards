"""Websocket commands the cards call."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, SUBENTRY_PERSON
from .schema import vol


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every command."""
    websocket_api.async_register_command(hass, ws_people)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/people"})
@callback
def ws_people(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the people, each as {id, name}."""
    people = [
        {"id": subentry.subentry_id, "name": subentry.title}
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_PERSON
    ]
    connection.send_result(msg["id"], people)
