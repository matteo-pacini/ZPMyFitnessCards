"""Exporting a person's data through their menu, and downloading it."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.metron.export import build_zip

from .conftest import mock_entry, person
from .test_activity import GARMIN, KCAL, anna

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
    bowl = [{"name": "Bowl", "grams": 40}]
    oats = (await ws("food/add", **OATS, barcode="5000", portions=bowl, person="debora"))["result"]
    await ws("food/add", name="Apple", kcal=52, protein=0.3, carbs=14, fat=0.2, salt=0)
    coffee = {"name": "Coffee", "grams": 250, "kcal": 20, "protein": 1, "carbs": 1.5, "fat": 1}
    porridge = [{"food_id": oats["id"], "grams": 60}, coffee]
    await ws("meal/add", name="Porridge bowl", owner=None, items=porridge)
    await ws("meal/add", name="Her snack", owner="debora", items=[{"name": "Bar", "kcal": 200}])
    await ws("meal/add", name="His snack", owner="matteo", items=[{"name": "Bar", "kcal": 1}])
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
    assert url.startswith("/api/metron/export/debora?authSig=")

    # The link alone is enough: no other sign-in.
    response = await (await hass_client_no_auth()).get(url)
    assert response.status == 200
    assert response.content_type == "application/zip"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="metron-debora-2026-11-09.zip"'
    )
    archive = zipfile.ZipFile(io.BytesIO(await response.read()))
    assert archive.namelist() == [
        "entries.csv",
        "weights.csv",
        "foods.csv",
        "meals.csv",
        "activity.csv",
    ]
    # Debora has never had active calories allowed.
    assert read_csv(archive, "activity.csv") == []

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
        "saved_by": "Debora",
    }
    assert (apple["barcode"], apple["salt_g_per_100g"], apple["portions"]) == ("", "0", "")
    assert apple["saved_by"] == ""

    # Everyone's meals and hers, not his. A saved food's item follows the
    # food, so it gives no values of its own.
    snack, linked, fixed = read_csv(archive, "meals.csv")
    assert snack == {
        "owner": "Debora",
        "meal": "Her snack",
        "item": "Bar",
        "food_id": "",
        "grams": "",
        "kcal": "200",
        "protein_g": "",
        "carbs_g": "",
        "fat_g": "",
        "fibre_g": "",
        "sugar_g": "",
        "saturated_fat_g": "",
        "salt_g": "",
    }
    assert {k: v for k, v in linked.items() if v} == {
        "owner": "Everyone",
        "meal": "Porridge bowl",
        "item": "Porridge oats",
        "food_id": str(oats["id"]),
        "grams": "60",
    }
    assert {k: v for k, v in fixed.items() if v} == {
        "owner": "Everyone",
        "meal": "Porridge bowl",
        "item": "Coffee",
        "grams": "250",
        "kcal": "20",
        "protein_g": "1",
        "carbs_g": "1.5",
        "fat_g": "1",
    }


async def test_exports_a_person_s_active_calories(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    hass.states.async_set(GARMIN, "120", KCAL)
    entry = mock_entry(anna(), person(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    await data.async_log_activity(data.people["anna"], "2026-11-08", 906)
    archive = zipfile.ZipFile(
        io.BytesIO(await hass.async_add_executor_job(build_zip, data.db, "anna"))
    )
    assert read_csv(archive, "activity.csv") == [
        {
            "day": "2026-11-08",
            "source": "action",
            "measured_kcal": "906",
            "counted_kcal": "680",
            "added_kcal": "435.831",
            "allowed_kcal": "244.169",
            "share_pct": "75",
            "cap_kcal": "1500",
        },
        {
            "day": "2026-11-09",
            "source": GARMIN,
            "measured_kcal": "120",
            "counted_kcal": "90",
            "added_kcal": "0",
            "allowed_kcal": "244.169",
            "share_pct": "75",
            "cap_kcal": "1500",
        },
    ]


async def test_the_link_is_short_lived_and_for_admins_only(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
    hass_read_only_access_token: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = await hass_client_no_auth()
    assert (await client.get("/api/metron/export/debora")).status == 401
    viewer = hass.auth.async_validate_access_token(hass_read_only_access_token)
    theirs = async_sign_path(
        hass, "/api/metron/export/debora", timedelta(minutes=5), refresh_token_id=viewer.id
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
    assert (await client.get("/api/metron/export/nobody")).status == 404
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await client.get("/api/metron/export/debora")).status == 404
