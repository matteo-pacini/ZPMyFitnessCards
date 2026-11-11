"""Exporting a person's data through their menu, and downloading it."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}


@pytest.fixture(autouse=True)
async def config_api(hass: HomeAssistant) -> None:
    """The REST API the UI's dialogs use, set up before a client fixes the routes."""
    assert await async_setup_component(hass, "config", {})


async def export_link(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator, name: str
) -> dict:
    """Choose Export data in a person's menu, as the UI does; return the flow's end."""
    client = await hass_client()
    subentry = next(s for s in entry.subentries.values() if s.title == name)
    menu = await client.post(
        "/api/config/config_entries/subentries/flow",
        json={"handler": [entry.entry_id, "person"], "subentry_id": subentry.subentry_id},
    )
    flow_id = (await menu.json())["flow_id"]
    done = await client.post(
        f"/api/config/config_entries/subentries/flow/{flow_id}", json={"next_step_id": "export"}
    )
    return await done.json()


def link_url(placeholders: dict[str, str]) -> str:
    """The URL in the flow's link, which opens in a new tab so the frontend leaves it be."""
    match = re.fullmatch(r'<a href="([^"]+)" target="_blank">', placeholders["link"])
    assert match, placeholders["link"]
    assert placeholders["link_end"] == "</a>"
    return match[1]


def read_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    text = archive.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


async def test_exports_a_person_s_data_as_a_zip_of_csvs(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    ws,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    oats = (await ws("food/add", **OATS, barcode="5000", portions=[{"name": "Bowl", "grams": 40}]))[
        "result"
    ]
    await ws("food/add", name="Apple", kcal=52, protein=0.3, carbs=14, fat=0.2, salt=0)
    await ws(
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="breakfast",
        food_id=oats["id"],
        grams=60,
    )
    await ws("entry/add", person="debora", day="2026-11-08", meal="snacks", name="Pizza", kcal=900)
    await ws("entry/add", person="matteo", day="2026-11-08", meal="lunch", name="Not hers", kcal=1)
    await ws("weight/set", person="debora", day="2026-11-09", kg=69.5)
    await ws("weight/set", person="matteo", day="2026-11-09", kg=88)

    done = await export_link(hass, entry, hass_client, "Debora")
    assert done["type"] == "abort"
    assert done["reason"] == "exported"
    placeholders = done["description_placeholders"]
    assert (placeholders["name"], placeholders["minutes"]) == ("Debora", "5")
    url = link_url(placeholders)
    assert url.startswith("/api/zp_my_fitness/export/debora?authSig=")

    # The link alone is enough: no other sign-in.
    response = await (await hass_client_no_auth()).get(url)
    assert response.status == 200
    assert response.content_type == "application/zip"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="zp-my-fitness-debora-2026-11-09.zip"'
    )
    archive = zipfile.ZipFile(io.BytesIO(await response.read()))
    assert archive.namelist() == ["entries.csv", "weights.csv", "foods.csv"]

    pizza, porridge = read_csv(archive, "entries.csv")
    assert pizza == {
        "day": "2026-11-08",
        "meal": "snacks",
        "name": "Pizza",
        "grams": "",
        "kcal": "900",
        "protein_g": "",
        "carbs_g": "",
        "fat_g": "",
        "fibre_g": "",
        "sugar_g": "",
        "saturated_fat_g": "",
        "salt_g": "",
        "food_id": "",
        "source": "",
        "logged_at": "2026-11-09T12:00:00+00:00",
    }
    assert {k: porridge[k] for k in ("name", "grams", "kcal", "protein_g", "food_id")} == {
        "name": "Porridge oats",
        "grams": "60",
        # 389 * 60 / 100 is 233.39999999999998 in floating point.
        "kcal": "233.4",
        "protein_g": "10.14",
        "food_id": str(oats["id"]),
    }
    assert read_csv(archive, "weights.csv") == [{"day": "2026-11-09", "weight_kg": "69.5"}]
    oats_row, apple = read_csv(archive, "foods.csv")
    assert oats_row == {
        "id": str(oats["id"]),
        "name": "Porridge oats",
        "barcode": "5000",
        "kcal_per_100g": "389",
        "protein_g_per_100g": "16.9",
        "carbs_g_per_100g": "66",
        "fat_g_per_100g": "6.9",
        "fibre_g_per_100g": "",
        "sugar_g_per_100g": "",
        "saturated_fat_g_per_100g": "",
        "salt_g_per_100g": "",
        "portions": '[{"name": "Bowl", "grams": 40.0}]',
    }
    assert (apple["barcode"], apple["salt_g_per_100g"], apple["portions"]) == ("", "0", "")


async def test_the_link_is_short_lived_and_for_admins_only(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
    hass_read_only_access_token: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = await hass_client_no_auth()
    assert (await client.get("/api/zp_my_fitness/export/debora")).status == 401
    viewer = hass.auth.async_validate_access_token(hass_read_only_access_token)
    theirs = async_sign_path(
        hass, "/api/zp_my_fitness/export/debora", timedelta(minutes=5), refresh_token_id=viewer.id
    )
    assert (await client.get(theirs)).status == 401

    url = link_url(
        (await export_link(hass, entry, hass_client, "Debora"))["description_placeholders"]
    )
    freezer.tick(timedelta(minutes=6))
    assert (await client.get(url)).status == 401


async def test_answers_not_found_for_unknown_people_and_while_unloaded(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    assert (await client.get("/api/zp_my_fitness/export/nobody")).status == 404
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await client.get("/api/zp_my_fitness/export/debora")).status == 404
