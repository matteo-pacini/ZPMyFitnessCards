"""Reading MyFitnessPal's files, without Home Assistant."""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from custom_components.metron.myfitnesspal import (
    Diary,
    Unreadable,
    entries,
    known_meal,
    other_meals,
    read,
    weights_kg,
)

from .conftest import EXPORT, MYFITNESSPAL, myfitnesspal_zip

TODAY = date(2026, 11, 9)
PAGE = (MYFITNESSPAL / "printable-diary.html").read_text()

NUTRITION = (MYFITNESSPAL / EXPORT / f"Nutrition-Summary-{EXPORT[12:]}.csv").read_text(
    encoding="utf-8-sig"
)


def write(folder: Path, name: str, text: str | bytes) -> Path:
    path = folder / name
    if isinstance(text, str):
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(text)
    return path


def refusal(path: Path) -> tuple[str, dict[str, str]]:
    with pytest.raises(Unreadable) as caught:
        read(path, TODAY)
    return caught.value.key, caught.value.placeholders


def totals(diary: Diary) -> list[tuple[str, str, float | None]]:
    return [(e["day"], e["meal"], e["kcal"]) for e in entries(diary, {})]


def test_reads_the_export_zip(tmp_path: Path) -> None:
    diary = read(myfitnesspal_zip(tmp_path), TODAY)

    # The Exercise-Summary's Kilograms column gives the weights' unit.
    assert diary.weight_unit == "kg"
    assert other_meals(diary) == ["Preworkout"]
    breakfast, lunch, supper, snack, preworkout, dinner = entries(
        diary, {"Preworkout": "breakfast"}
    )
    # Two breakfast rows at different times add up into one quick add.
    assert breakfast == {
        "day": "2025-10-01",
        "meal": "breakfast",
        "name": "MyFitnessPal",
        "grams": None,
        "kcal": 520.5,
        "protein": 20.0,
        "carbs": 75.0,
        "fat": 13.5,
        "fibre": 7.0,
        "sugar": 20.0,
        "saturated_fat": 4.5,
        # 500 mg of sodium.
        "salt": 1.25,
    }
    # The quoted note's line break, and the unquoted note's extra lines, are skipped.
    assert (lunch["meal"], lunch["kcal"], supper["meal"], supper["kcal"]) == (
        "lunch",
        650,
        "dinner",
        700,
    )
    assert (snack["meal"], preworkout["meal"], preworkout["day"]) == (
        "snacks",
        "breakfast",
        "2025-10-02",
    )
    # Empty cells are no value.
    assert (dinner["kcal"], dinner["fibre"], dinner["salt"]) == (800, None, None)
    # A day with a waist but no weight has none.
    assert weights_kg(diary, "kg") == [("2025-10-01", 80.5), ("2025-10-04", 80.1)]


def test_reads_kilojoules_and_dates_excel_wrote(tmp_path: Path) -> None:
    diary = read(MYFITNESSPAL / "Nutrition-Summary-kilojoules.csv", TODAY)
    # 10/10/2025 and 10/11/2025: with no part over 12, slash dates are month first.
    assert totals(diary) == [
        ("2025-10-10", "breakfast", 500),
        ("2025-10-10", "lunch", 1000),
        ("2025-10-11", "snacks", 200),
    ]
    assert diary.weight_unit is None


@pytest.mark.parametrize(
    "name", ["Nutrition-Summary-day-first.csv", "Nutrition-Summary-month-first.csv"]
)
def test_reads_slash_dates_in_the_order_the_file_shows(name: str) -> None:
    # 25/10/2025 can only be day first, and 10/25/2025 month first: the
    # ambiguous 9/10/2025 and 10/9/2025 follow them.
    assert totals(read(MYFITNESSPAL / name, TODAY)) == [
        ("2025-10-09", "breakfast", 300),
        ("2025-10-09", "lunch", 500),
        ("2025-10-25", "dinner", 650),
    ]


def test_reads_weights_with_the_day_first(tmp_path: Path) -> None:
    diary = read(write(tmp_path, "w.csv", "Date,Weight\n1/10/2025,81\n13/10/2025,80\n"), TODAY)
    assert weights_kg(diary, "kg") == [("2025-10-01", 81), ("2025-10-13", 80)]


def test_refuses_a_file_with_slash_dates_in_both_orders() -> None:
    name = "Nutrition-Summary-mixed-dates.csv"
    # 25/10/2025 on line 3 is day first; 10/26/2025 on line 4 is month first.
    assert refusal(MYFITNESSPAL / name) == ("mixed_date_orders", {"file": name, "line": "4"})


def test_reads_weights_in_pounds(tmp_path: Path) -> None:
    diary = read(MYFITNESSPAL / "Measurement-Summary-pounds.csv", TODAY)
    assert diary.foods == []
    assert weights_kg(diary, "lb") == [("2025-10-12", 80.01), ("2025-10-13", 79.38)]


def test_an_exercise_summary_in_pounds_gives_the_unit(tmp_path: Path) -> None:
    exercise = "Date,Exercise,Type,Exercise Calories,Exercise Minutes,Sets,Reps Per Set,Pounds\n"
    weights = "Date,Weight\n2025-10-01,180\n"
    for name, unit in (("Pounds", "lb"), ("Steps", None)):
        archive = tmp_path / f"{name}.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Exercise-Summary.csv", exercise.replace("Pounds", name))
            z.writestr("Measurement-Summary.csv", weights)
            z.writestr("__MACOSX/._Measurement-Summary.csv", b"\x00\x05\x16\x07binary")
            z.writestr("readme.txt", "not a CSV")
        assert read(archive, TODAY).weight_unit == unit


def test_reads_a_csv_excel_saved_in_the_windows_code_page(tmp_path: Path) -> None:
    text = NUTRITION.replace("Preworkout", "Goûter")
    diary = read(write(tmp_path, "n.csv", text.encode("cp1252", errors="replace")), TODAY)
    assert other_meals(diary) == ["Goûter"]


def test_leaves_out_days_after_today(tmp_path: Path) -> None:
    csv = "Date,Meal,Calories\n2026-11-09,Lunch,500\n2026-11-10,Lunch,600\n"
    weights = "Date,Weight\n2026-11-09,70\n2026-11-10,69\n"
    assert totals(read(write(tmp_path, "n.csv", csv), TODAY)) == [("2026-11-09", "lunch", 500)]
    assert len(read(write(tmp_path, "w.csv", weights), TODAY).weights) == 1


def test_meals_map_by_name_ignoring_case() -> None:
    assert [
        known_meal(t)
        for t in ("BREAKFAST", "lunch", "Dinner", "supper", "Snack", "snacks", "Snack (3)", "Tea")
    ] == ["breakfast", "lunch", "dinner", "dinner", "snacks", "snacks", "snacks", None]


def test_refuses_weights_outside_the_range_in_the_unit_chosen(tmp_path: Path) -> None:
    diary = read(write(tmp_path, "w.csv", "Date,Weight\n2025-10-01,80\n2025-10-02,401\n"), TODAY)
    with pytest.raises(Unreadable) as caught:
        weights_kg(diary, "kg")
    assert (caught.value.key, caught.value.placeholders) == (
        "weight_out_of_range",
        {"file": "w.csv", "line": "3"},
    )
    # 401 lb is 181.89 kg, but 80 lb is 36.29 kg: both fine.
    assert weights_kg(diary, "lb") == [("2025-10-01", 36.29), ("2025-10-02", 181.89)]


@pytest.mark.parametrize(
    ("text", "line"),
    [
        # Line numbers count the lines a quoted note spans.
        ('Date,Meal,Calories,Note\n2025-10-01,Lunch,1,"a\nb"\n2025-10-02,Lunch,x,\n', "4"),
        ("Date,Meal,Calories\n2025-02-30,Lunch,1\n", "2"),
        ("Date,Meal,Calories\n1/10/2025,Lunch,1\n13/13/2025,Lunch,1\n", "3"),
        ("Date,Meal,Calories\n2025-10-01,Lunch\n", "2"),
        ('Date,Meal,Calories,Note\n2025-10-01,Lunch,1,"' + "x" * 200_000 + '"\n', "2"),
        ("Date,Meal,Calories\n2025-10-01,Lunch,nan\n", "2"),
        ("Date,Meal,Calories\n2025-10-01,Lunch,inf\n", "2"),
    ],
    ids=[
        "not a number",
        "no such date",
        "no such slash date",
        "too few cells",
        "a cell too long",
        "nan",
        "infinite",
    ],
)
def test_names_the_line_it_cannot_read(tmp_path: Path, text: str, line: str) -> None:
    assert refusal(write(tmp_path, "Nutrition.csv", text)) == (
        "bad_line",
        {"file": "Nutrition.csv", "line": line},
    )


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("notes.txt", "Date,Meal,Calories\n"),
        ("other.csv", "Date,Steps\n2025-10-01,1000\n"),
        ("undated.csv", "Day,Weight\n2025-10-01,80\n"),
        ("empty.csv", ""),
        ("broken.zip", "PK not really"),
        ("other.zip", b"PK\x05\x06" + b"\x00" * 18),
    ],
)
def test_refuses_files_that_are_not_myfitnesspal_s(
    tmp_path: Path, name: str, content: str | bytes
) -> None:
    assert refusal(write(tmp_path, name, content)) == ("not_myfitnesspal", {})


def test_reads_the_printable_diary_saved_as_a_complete_web_page() -> None:
    diary = read(MYFITNESSPAL / "printable-diary.html", TODAY)
    assert other_meals(diary) == ["Pre-workout"]
    rows = entries(diary, {"Pre-workout": "lunch"})
    assert [(e["day"], e["meal"], e["name"], e["grams"]) for e in rows] == [
        ("2025-10-20", "breakfast", "Porridge oats", 40),
        # &nbsp; is a space.
        ("2025-10-20", "breakfast", "Greek yogurt Natural", 150),
        # "62 g = 1 wrap (62g)" is 62 g.
        ("2025-10-20", "lunch", "Corner Deli - Chicken Wrap", 62),
        # Not in grams: MyFitnessPal's whole text, and no grams.
        ("2025-10-20", "lunch", "Corner Deli - Cheese & Onion Pasty, 1 Pasty", None),
        ("2025-10-20", "dinner", "Home - Lentil soup", 300),
        ("2025-10-20", "lunch", 'Banana, 1 medium (7" to 7-7/8" long)', None),
        ("2025-10-21", "breakfast", "Toast, 2 slice", None),
        ("2025-10-21", "snacks", "Dark chocolate 70%", 25),
    ]
    oats, yogurt, *_ = rows
    assert {k: oats[k] for k in ("kcal", "carbs", "fat", "protein", "sugar", "fibre", "salt")} == {
        "kcal": 150,
        "carbs": 27,
        "fat": 3,
        "protein": 5,
        "sugar": 1,
        "fibre": 4,
        # 2 mg of sodium.
        "salt": 0.005,
    }
    # -- is no value.
    assert (yogurt["fibre"], yogurt["salt"], yogurt["saturated_fat"]) == (None, None, None)
    # Values as shown, even when they look wrong.
    soup = rows[4]
    assert (soup["kcal"], soup["carbs"]) == (162, 162)


def test_keeps_none_of_the_page_but_its_rows() -> None:
    diary = read(MYFITNESSPAL / "printable-diary.html", TODAY)
    assert "example.com" not in repr(diary)
    assert "not-a-real-token" not in repr(diary)


def test_refuses_a_page_saved_before_the_diary_loaded() -> None:
    assert refusal(MYFITNESSPAL / "printable-diary-html-only.html") == ("save_complete", {})


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        (("Oct 20, 2025", "20 oct. 2025"), ("date_not_english", {})),
        (("Oct 20, 2025", "Okt 20, 2025"), ("date_not_english", {})),
        (("Oct 21, 2025", "Feb 30, 2025"), ("date_not_english", {})),
        (('">Calories</th>', '">Energy</th>'), ("no_calories", {})),
        (('">135</th>', '">1,35</th>'), ("bad_row", {"day": "2025-10-21", "row": "2"})),
        (
            ('<th scope="row" class="MuiTableCell-root MuiTableCell-body">2g</th></tr>', "</tr>"),
            ("bad_row", {"day": "2025-10-21", "row": "1"}),
        ),
    ],
    ids=["day first", "not English", "no such date", "no calories", "a value", "a short row"],
)
def test_refuses_a_page_it_cannot_read(
    tmp_path: Path, change: tuple[str, str], refused: tuple
) -> None:
    old, new = change
    assert old in PAGE
    # The last occurrence, so that the first day reads fine.
    head, _, tail = PAGE.rpartition(old)
    assert refusal(write(tmp_path, "page.html", head + new + tail)) == refused


def test_rows_outside_a_dated_day_and_empty_rows_are_skipped(tmp_path: Path) -> None:
    undated = PAGE.replace('data-testid="qa-regression-report-date"', "")
    assert refusal(write(tmp_path, "undated.html", undated)) == ("save_complete", {})
    with_empty_rows = PAGE.replace("<tbody", "<tbody><tr></tr>", 1).replace(
        "<thead", "<p>A paragraph</p><thead", 1
    )
    assert read(write(tmp_path, "empty.html", with_empty_rows), TODAY) == read(
        MYFITNESSPAL / "printable-diary.html", TODAY
    )


def test_values_and_amounts_in_other_units(tmp_path: Path) -> None:
    changes = [
        # Porridge oats: sodium in g, carbs in mg, an amount with no unit.
        ('">2mg</th>', '">1.2g</th>'),
        ('">27g</th>', '">2700mg</th>'),
        ("Porridge oats, 40 g", "Porridge oats, 40"),
        # Greek yogurt: sugar with no unit, which is g. The wrap: sodium with none, mg.
        (
            '">6g</th><th scope="row" class="MuiTableCell-root MuiTableCell-body">--',
            '">6</th><th scope="row" class="MuiTableCell-root MuiTableCell-body">--',
        ),
        ('">400mg</th>', '">400</th>'),
        # Lentil soup: no amount at all.
        ("Home - Lentil soup, 300 gram", "Home soup"),
    ]
    page = PAGE
    for old, new in changes:
        assert old in page
        page = page.replace(old, new, 1)
    oats, yogurt, wrap, _pasty, soup, *_ = entries(
        read(write(tmp_path, "units.html", page), TODAY), {}
    )
    assert (oats["salt"], oats["carbs"], oats["name"], oats["grams"]) == (
        3.0,
        2.7,
        "Porridge oats, 40",
        None,
    )
    assert (yogurt["sugar"], wrap["salt"], soup["name"], soup["grams"]) == (6, 1, "Home soup", None)
