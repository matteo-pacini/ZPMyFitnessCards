"""Importing from MyFitnessPal through a person's menu."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.fork_and_scale.const import SUBENTRY_PERSON

from .conftest import MYFITNESSPAL, myfitnesspal_zip


@pytest.fixture(autouse=True)
def uploads_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep file_upload's folder, which it puts in the system's, in the test's own."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


@pytest.fixture
def importer(hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator):
    """Upload a file and send it to Debora's import form; return the next step."""

    async def run(path: Path, name: str = "Debora") -> dict[str, Any]:
        client = await hass_client()
        with path.open("rb") as file:
            response = await client.post("/api/file_upload", data={"file": file})
        assert response.status == 200
        file_id = (await response.json())["file_id"]
        form = await start(name)
        return await hass.config_entries.subentries.async_configure(
            form["flow_id"], {"file": file_id}
        )

    async def start(name: str = "Debora") -> dict[str, Any]:
        subentry = next(s for s in entry.subentries.values() if s.title == name)
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_PERSON),
            context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
        )
        form = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"next_step_id": "import_mfp"}
        )
        assert form["step_id"] == "import_mfp"
        assert form["description_placeholders"] == {"name": name}
        return form

    run.start = start
    return run


async def configure(hass: HomeAssistant, result: dict, values: dict) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_configure(result["flow_id"], values)


def defaults(result: dict) -> dict[str, Any]:
    """Each field's default or suggested value."""
    return {
        str(key): key.default() if callable(key.default) else key.description["suggested_value"]
        for key in result["data_schema"].schema
    }


async def entries(ws, day: str) -> list[tuple[str, str, float, str | None]]:
    reply = await ws("day", person="debora", day=day)
    return [(e["meal"], e["name"], e["kcal"], e["source"]) for e in reply["result"]["entries"]]


async def test_imports_the_export_zip(hass: HomeAssistant, importer, ws, tmp_path: Path) -> None:
    await ws("entry/add", person="debora", day="2025-10-01", meal="lunch", name="Mine", kcal=10)
    await ws("weight/set", person="debora", day="2025-10-04", kg=79)

    meals = await importer(myfitnesspal_zip(tmp_path))
    assert meals["step_id"] == "import_mfp_meals"
    assert defaults(meals) == {"Preworkout": "snacks"}
    unit = await configure(hass, meals, {"Preworkout": "breakfast"})
    assert unit["step_id"] == "import_mfp_unit"
    # From the Exercise-Summary's Kilograms column.
    assert defaults(unit) == {"weight_unit": "kg"}
    done = await configure(hass, unit, {"weight_unit": "kg"})

    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "mfp_imported"
    assert done["description_placeholders"] == {
        "days": "3",
        "entries": "6",
        "weights": "1",
        "skipped": "1",
    }
    assert await entries(ws, "2025-10-01") == [
        ("lunch", "Mine", 10, None),
        ("breakfast", "MyFitnessPal", 520.5, "myfitnesspal"),
        ("lunch", "MyFitnessPal", 650, "myfitnesspal"),
        ("dinner", "MyFitnessPal", 700, "myfitnesspal"),
    ]
    assert [e[0] for e in await entries(ws, "2025-10-02")] == ["snacks", "breakfast"]
    weights = (await ws("weights", person="debora", start="2025-10-01", end="2025-10-31"))["result"]
    # Ours wins.
    assert weights == [{"day": "2025-10-01", "kg": 80.5}, {"day": "2025-10-04", "kg": 79}]


async def test_importing_again_replaces_only_myfitnesspal_entries(
    hass: HomeAssistant, importer, ws
) -> None:
    kilojoules = MYFITNESSPAL / "Nutrition-Summary-kilojoules.csv"
    first = await importer(kilojoules)
    assert first["description_placeholders"] == {
        "days": "2",
        "entries": "3",
        "weights": "0",
        "skipped": "0",
    }
    await ws("entry/add", person="debora", day="2025-10-10", meal="lunch", name="Mine", kcal=10)
    again = await importer(kilojoules)
    assert again["description_placeholders"] == first["description_placeholders"]
    assert await entries(ws, "2025-10-10") == [
        ("lunch", "Mine", 10, None),
        ("breakfast", "MyFitnessPal", 500, "myfitnesspal"),
        ("lunch", "MyFitnessPal", 1000, "myfitnesspal"),
    ]
    # Matteo's diary is his own.
    matteo = await ws("day", person="matteo", day="2025-10-10")
    assert matteo["result"]["entries"] == []


async def test_imports_the_printable_diary(hass: HomeAssistant, importer, ws) -> None:
    meals = await importer(MYFITNESSPAL / "printable-diary.html")
    assert defaults(meals) == {"Pre-workout": "snacks"}
    done = await configure(hass, meals, {"Pre-workout": "snacks"})
    assert done["description_placeholders"] == {
        "days": "2",
        "entries": "8",
        "weights": "0",
        "skipped": "0",
    }
    day = (await ws("day", person="debora", day="2025-10-20"))["result"]["entries"]
    oats = day[0]
    assert (oats["name"], oats["grams"], oats["kcal"], oats["salt"]) == (
        "Porridge oats",
        40,
        150,
        0.005,
    )
    assert day[-1]["name"] == 'Banana, 1 medium (7" to 7-7/8" long)'
    assert day[-1]["meal"] == "snacks"


@pytest.mark.parametrize(("units", "unit"), [(METRIC_SYSTEM, "kg"), (US_CUSTOMARY_SYSTEM, "lb")])
async def test_the_weight_unit_defaults_to_home_assistant_s(
    hass: HomeAssistant, importer, ws, units, unit: str
) -> None:
    hass.config.units = units
    form = await importer(MYFITNESSPAL / "Measurement-Summary-pounds.csv")
    assert form["step_id"] == "import_mfp_unit"
    assert defaults(form) == {"weight_unit": unit}
    done = await configure(hass, form, {"weight_unit": "lb"})
    assert done["description_placeholders"] == {
        "days": "0",
        "entries": "0",
        "weights": "2",
        "skipped": "0",
    }
    weights = await ws("weights", person="debora", start="2025-10-01", end="2025-10-31")
    assert [w["kg"] for w in weights["result"]] == [80.01, 79.38]


async def test_refuses_weights_outside_the_range(
    hass: HomeAssistant, importer, ws, tmp_path: Path
) -> None:
    heavy = tmp_path / "Measurement-Summary.csv"
    heavy.write_text("Date,Weight\n2025-10-01,80\n2025-10-02,450\n")
    form = await importer(heavy)
    refused = await configure(hass, form, {"weight_unit": "kg"})
    assert refused["step_id"] == "import_mfp_unit"
    assert refused["errors"] == {"base": "weight_out_of_range"}
    assert refused["description_placeholders"] == {"file": "Measurement-Summary.csv", "line": "3"}
    # The unit chosen stays chosen.
    assert defaults(refused) == {"weight_unit": "kg"}
    done = await configure(hass, refused, {"weight_unit": "lb"})
    assert done["description_placeholders"]["weights"] == "2"


@pytest.mark.parametrize(
    ("name", "content", "error"),
    [
        ("printable-diary-html-only.html", None, "save_complete"),
        ("Nutrition-Summary-mixed-dates.csv", None, "mixed_date_orders"),
        ("notes.csv", "Date,Steps\n2025-10-01,100\n", "not_myfitnesspal"),
        ("Nutrition.csv", "Date,Meal,Calories\n2025-10-01,Lunch,lots\n", "bad_line"),
        ("Exercise.csv", "Date,Exercise,Kilograms\n2025-10-01,Run,\n", "nothing_to_import"),
        ("Future.csv", "Date,Meal,Calories\n2026-11-10,Lunch,1\n", "nothing_to_import"),
    ],
)
async def test_refuses_files_it_cannot_import(
    hass: HomeAssistant, importer, ws, tmp_path: Path, name: str, content: str | None, error: str
) -> None:
    path = MYFITNESSPAL / name
    if content is not None:
        path = tmp_path / name
        path.write_text(content)
    refused = await importer(path)
    assert refused["step_id"] == "import_mfp"
    assert refused["errors"] == {"base": error}
    assert refused["description_placeholders"]["name"] == "Debora"


async def test_asks_for_the_file_again_once_its_upload_is_gone(
    hass: HomeAssistant, importer
) -> None:
    form = await importer.start()
    refused = await configure(hass, form, {"file": str(uuid.uuid4())})
    assert refused["errors"] == {"base": "upload_again"}


async def test_corrects_past_days_statistics_and_tells_the_cards(
    hass: HomeAssistant, importer, ws
) -> None:
    client = ws.client
    await client.send_json_auto_id({"type": "fork_and_scale/subscribe"})
    assert (await client.receive_json())["success"]
    recorder = MagicMock()
    hass.config.components.add("recorder")
    kilojoules = MYFITNESSPAL / "Nutrition-Summary-kilojoules.csv"
    with patch("homeassistant.components.recorder.get_instance", return_value=recorder):
        await importer(kilojoules)
        event = await client.receive_json()
        assert event["event"] == {"person": "debora", "days": ["2025-10-10", "2025-10-11"]}
        london = ZoneInfo("Europe/London")
        calls = {
            (c.args[0], c.args[1]): c.args[2]
            for c in recorder.async_adjust_statistics.call_args_list
            if c.args[0] == "sensor.debora_calories_today"
        }
        assert calls == {
            ("sensor.debora_calories_today", datetime(2025, 10, 10, 23, tzinfo=london)): 1500,
            ("sensor.debora_calories_today", datetime(2025, 10, 11, 23, tzinfo=london)): 200,
        }
        # The same file again changes no day's totals.
        recorder.reset_mock()
        await importer(kilojoules)
        assert recorder.async_adjust_statistics.call_count == 0
