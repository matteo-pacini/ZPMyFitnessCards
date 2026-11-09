"""ZPMyFitnessCards: a food diary and weight tracking for each person."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import websocket
from .const import CARDS_URL, DOMAIN

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARDS_FILE = Path(__file__).parent / "frontend" / "zp-my-fitness-cards.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the cards and register the websocket commands."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(CARDS_FILE), cache_headers=True)]
    )
    if "frontend" in hass.config.components:
        # Cached for good, so the version in the URL is what makes browsers
        # fetch the cards again after an update.
        add_extra_js_url(hass, f"{CARDS_URL}?v={integration.version}")
    websocket.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration's single entry."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry."""
    return True
