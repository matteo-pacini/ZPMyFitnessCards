"""Importing from MyFitnessPal and exporting, through a person's menu in the integration's page.

The tests share one Home Assistant, so each imports into days of its own, in
October 2025, and deletes the weights it adds.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from .conftest import REPO, Home
from .test_cards import TIMEOUT, person_id, save_food

FIXTURES = REPO / "tests" / "fixtures" / "myfitnesspal"
EXPORT = "File-Export-2025-10-01-to-2025-10-04"


def menu(home: Home, page: Page, person: str) -> Locator:
    """Open a person's menu, the one "Change person" shows; return its dialog."""
    page.goto(home.url + "/config/integrations/integration/metron")
    row = page.locator("ha-config-sub-entry-row", has_text=person)
    row.get_by_role("button", name="Change person").click()
    dialog = page.locator("dialog-data-entry-flow")
    expect(dialog.get_by_text("Change details")).to_be_visible(timeout=TIMEOUT)
    return dialog


def upload(home: Home, page: Page, person: str, path: Path) -> Locator:
    """Send a file to the person's "Import from MyFitnessPal"; return the dialog."""
    dialog = menu(home, page, person)
    dialog.get_by_text("Import from MyFitnessPal").click()
    dialog.locator("input[type=file]").set_input_files(path)
    expect(dialog.get_by_text(path.name)).to_be_visible(timeout=TIMEOUT)
    submit(dialog)
    return dialog


def submit(dialog: Locator) -> None:
    dialog.get_by_role("button", name="Submit").click()


def summary(dialog: Locator, days: int, entries: int, added: int, skipped: int) -> None:
    for line in (
        f"Days: {days}",
        f"Entries: {entries}",
        f"Weights added: {added}",
        f"Weights skipped, on days that already had one: {skipped}",
    ):
        expect(dialog.get_by_text(line, exact=True)).to_be_visible(timeout=TIMEOUT)


def day(home: Home, person: str, day: str) -> list[tuple[str, str, float]]:
    reply = home.ws({"type": "metron/day", "person": person_id(home, person), "day": day})
    return [(e["meal"], e["name"], e["kcal"]) for e in reply["entries"]]


def weights(home: Home, person: str, start: str, end: str) -> dict[str, float]:
    reply = home.ws(
        {
            "type": "metron/weights",
            "person": person_id(home, person),
            "start": start,
            "end": end,
        }
    )
    return {w["day"]: w["kg"] for w in reply}


@pytest.fixture
def forget_weights(home: Home):
    """Delete the weights a test leaves on the (person, day) pairs it adds to the list."""
    added: list[tuple[str, str]] = []
    yield added
    for person, day_ in added:
        home.ws({"type": "metron/weight/delete", "person": person_id(home, person), "day": day_})


def test_imports_the_export_zip_asking_for_meals_and_the_unit(
    home: Home, page: Page, tmp_path: Path, forget_weights: list
) -> None:
    archive = tmp_path / f"{EXPORT}.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in sorted((FIXTURES / EXPORT).iterdir()):
            z.write(path, path.name)
    debora = person_id(home, "Debora")
    forget_weights += [("Debora", "2025-10-01"), ("Debora", "2025-10-04")]
    home.ws({"type": "metron/weight/set", "person": debora, "day": "2025-10-04", "kg": 79})

    dialog = upload(home, page, "Debora", archive)
    # The meal of the file's own, which goes under snacks unless changed.
    expect(dialog.get_by_text("Choose where each goes")).to_be_visible(timeout=TIMEOUT)
    meal = dialog.locator("ha-select")
    expect(meal).to_have_count(1)
    assert meal.evaluate("select => select.label") == "Preworkout"
    meal.click()
    page.locator("ha-dropdown-item", has_text="Breakfast").click()
    submit(dialog)
    # The Exercise-Summary's Kilograms column chose the unit.
    expect(dialog.get_by_role("radio", name="Kilograms (kg)")).to_be_checked(timeout=TIMEOUT)
    submit(dialog)

    summary(dialog, days=3, entries=6, added=1, skipped=1)
    assert day(home, "Debora", "2025-10-02") == [
        ("snacks", "MyFitnessPal", 150),
        ("breakfast", "MyFitnessPal", 120),
    ]
    assert weights(home, "Debora", "2025-10-01", "2025-10-04") == {
        "2025-10-01": 80.5,
        "2025-10-04": 79,
    }


def test_imports_weights_in_the_unit_chosen_after_refusing_them_in_another(
    home: Home, page: Page, tmp_path: Path, forget_weights: list
) -> None:
    measurements = tmp_path / "Measurement-Summary-e2e.csv"
    measurements.write_text("Date,Weight\n2025-10-12,176.4\n2025-10-13,450\n")
    forget_weights += [("Matteo", "2025-10-12"), ("Matteo", "2025-10-13")]

    dialog = upload(home, page, "Matteo", measurements)
    # The file does not say, so Home Assistant's own units choose: metric here.
    expect(dialog.get_by_role("radio", name="Kilograms (kg)")).to_be_checked(timeout=TIMEOUT)
    submit(dialog)
    expect(
        dialog.get_by_text("Line 3 of Measurement-Summary-e2e.csv has a weight outside")
    ).to_be_visible(timeout=TIMEOUT)
    dialog.get_by_role("radio", name="Pounds (lb)").check()
    submit(dialog)

    summary(dialog, days=0, entries=0, added=2, skipped=0)
    assert weights(home, "Matteo", "2025-10-12", "2025-10-13") == {
        "2025-10-12": 80.01,
        "2025-10-13": 204.12,
    }


def test_imports_the_printable_diary(home: Home, page: Page) -> None:
    dialog = upload(home, page, "Debora", FIXTURES / "printable-diary.html")
    meal = dialog.locator("ha-select")
    expect(meal).to_have_count(1, timeout=TIMEOUT)
    assert meal.evaluate("select => select.label") == "Pre-workout"
    submit(dialog)

    summary(dialog, days=2, entries=8, added=0, skipped=0)
    rows = day(home, "Debora", "2025-10-20")
    assert rows[0] == ("breakfast", "Porridge oats", 150)
    assert rows[-1] == ("snacks", 'Banana, 1 medium (7" to 7-7/8" long)', 105)
    assert len(rows) == 6


@pytest.mark.parametrize(
    ("name", "message"),
    [
        # Saved before the diary loaded.
        ("printable-diary-html-only.html", "The page has no diary rows."),
        (
            "Nutrition-Summary-mixed-dates.csv",
            "Line 4 of Nutrition-Summary-mixed-dates.csv has the day and month the other way round",
        ),
    ],
)
def test_refuses_files_it_cannot_import(home: Home, page: Page, name: str, message: str) -> None:
    dialog = upload(home, page, "Debora", FIXTURES / name)
    expect(dialog.get_by_text(message)).to_be_visible(timeout=TIMEOUT)
    expect(dialog.get_by_text("Import from MyFitnessPal")).to_be_visible()


def test_exports_a_person_s_data_from_a_link(home: Home, page: Page, forget_weights: list) -> None:
    oats = save_food(home, "Export oats e2e", barcode="5099999000017")
    debora = person_id(home, "Debora")
    forget_weights.append(("Debora", "2025-10-25"))
    home.ws({"type": "metron/weight/set", "person": debora, "day": "2025-10-25", "kg": 68.4})
    home.ws(
        {
            "type": "metron/entry/add",
            "person": debora,
            "day": "2025-10-25",
            "meal": "lunch",
            "food_id": oats["id"],
            "grams": 50,
        }
    )

    dialog = menu(home, page, "Debora")
    dialog.get_by_text("Export data").click()
    link = dialog.get_by_role("link", name="Download Debora's data")
    # In a new tab, which the download closes: the frontend opens links to
    # its own pages in place, where the file would never arrive.
    expect(link).to_have_attribute("target", "_blank", timeout=TIMEOUT)
    with page.expect_download(timeout=TIMEOUT) as info:
        link.click()
    download = info.value
    assert download.suggested_filename.startswith("metron-debora-")

    archive = zipfile.ZipFile(download.path())

    def rows(name: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))

    lunch = next(e for e in rows("entries.csv") if e["name"] == "Export oats e2e")
    assert (lunch["day"], lunch["grams"], lunch["kcal"], lunch["food_id"]) == (
        "2025-10-25",
        "50",
        "194.5",
        str(oats["id"]),
    )
    food = next(f for f in rows("foods.csv") if f["id"] == str(oats["id"]))
    assert (food["barcode"], food["kcal_per_100g"]) == ("5099999000017", "389")
    assert {"day": "2025-10-25", "weight_kg": "68.4"} in rows("weights.csv")
