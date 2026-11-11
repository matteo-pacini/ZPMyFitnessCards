"""Fixtures for the integration tests."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.zp_my_fitness.const import DOMAIN, SUBENTRY_PERSON

# Monday 9 November 2026, midday in London.
NOW = "2026-11-09T12:00:00+00:00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components/."""


@pytest.fixture(autouse=True)
async def london(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path) -> None:
    """Run every test in London at NOW, with its own empty database."""
    hass.config.config_dir = str(tmp_path)
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(NOW)


@pytest.fixture
def us_customary(hass: HomeAssistant) -> None:
    """Home Assistant in US customary units, which weigh in lb.

    Ask for it before `entry`, so the sensors start in lb.
    """
    hass.config.units = US_CUSTOMARY_SYSTEM


def person(name: str = "Debora", key: str | None = None, **changes: Any) -> dict[str, Any]:
    """A person's sub-entry data, as the form stores it."""
    return {
        "key": key or name.lower(),
        "name": name,
        "sex": "female",
        "birth_date": "1996-03-15",
        "height_cm": 165.0,
        "start_weight_kg": 70.0,
        "start_date": "2026-11-01",
        "goal_weight_kg": 62.0,
        "activity": "moderate",
        "pace": "lose_0_5",
        "protein_pct": 20.0,
        "carbs_pct": 50.0,
        "fat_pct": 30.0,
        **changes,
    }


def mock_entry(*people: dict[str, Any], data: dict[str, Any] | None = None) -> MockConfigEntry:
    """The integration's entry with these people as sub-entries, on SQLite unless `data` says."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="ZPMyFitnessCards",
        data=data or {"engine": "sqlite"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_PERSON,
                title=p["name"],
                data=p,
                unique_id=None,
                subentry_id=f"sub_{p['key']}",
            )
            for p in people
        ],
    )


@pytest.fixture
def entry_data(database_url: str) -> dict[str, Any]:
    """The entry's data: SQLite in the config folder, then a Postgres database."""
    if database_url.startswith("sqlite"):
        return {"engine": "sqlite"}
    return {"engine": "postgresql", "db_url": database_url}


@pytest.fixture
async def entry(hass: HomeAssistant, entry_data: dict[str, Any]) -> MockConfigEntry:
    """The integration set up with Debora (key "debora") and Matteo (key "matteo").

    Each test using it runs twice: on SQLite, then on Postgres.
    """
    entry = mock_entry(
        person(),
        person(
            "Matteo",
            sex="male",
            birth_date="1990-06-01",
            height_cm=180.0,
            start_weight_kg=89.0,
            goal_weight_kg=80.0,
            activity="light",
        ),
        data=entry_data,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def ws(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator):
    """Send one command over the websocket API and return the reply."""
    client = await hass_ws_client(hass)

    async def call(type_: str, **fields: Any) -> dict[str, Any]:
        await client.send_json_auto_id({"type": f"{DOMAIN}/{type_}", **fields})
        reply = await client.receive_json()
        await hass.async_block_till_done()
        return reply

    call.client = client
    return call


MYFITNESSPAL = Path(__file__).parents[1] / "fixtures" / "myfitnesspal"
EXPORT = "File-Export-2025-10-01-to-2025-10-04"


def myfitnesspal_zip(folder: Path) -> Path:
    """MyFitnessPal's export ZIP, made in `folder` from the fixture's CSVs."""
    path = folder / f"{EXPORT}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for csv in sorted((MYFITNESSPAL / EXPORT).iterdir()):
            archive.write(csv, csv.name)
    return path
