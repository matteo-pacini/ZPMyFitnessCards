"""Keep the database file complete while Home Assistant backs it up."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _loaded(hass: HomeAssistant) -> list:
    return [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Hold writes and fold the write-ahead log into the file."""
    for entry in _loaded(hass):
        await entry.runtime_data.data.async_pause_for_backup()


async def async_post_backup(hass: HomeAssistant) -> None:
    """Let writes continue."""
    for entry in _loaded(hass):
        entry.runtime_data.data.resume_after_backup()
