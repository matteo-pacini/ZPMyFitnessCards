"""Fixtures for the integration tests."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components/."""


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """The integration's entry, set up, with no people yet."""
    entry = MockConfigEntry(domain=DOMAIN, title="ZPMyFitnessCards")
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry
