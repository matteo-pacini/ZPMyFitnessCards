"""Reading a diary from MyFitnessPal's files, with no Home Assistant code.

Two kinds of file are read: the Premium export, a ZIP of CSVs or any one of
those CSVs, and the printable diary page saved from a browser as a complete
web page. Both become a Diary of foods and weights.

A saved page also carries the account's email, location and sign-in tokens in
its scripts. Only the diary's rows are read, and errors name a line or a row,
never the file's text.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from .const import IMPORTED_MEAL, MAX_KG, MIN_KG

# The name of each entry a CSV's meal totals become.
TOTAL_NAME = "MyFitnessPal"

KJ_PER_KCAL = 4.184
KG_PER_LB = 0.45359237
# Salt is 2.5 times the sodium in it.
SALT_PER_SODIUM = 2.5

# Decimal places kept of each imported value, in kcal or g.
DIGITS = {"kcal": 1, "salt": 3}

GRAM_WORDS = {"g", "gr", "gram", "grams", "grama"}

# A date as Excel writes it on re-saving a CSV, D/M/YYYY or M/D/YYYY by region.
SLASH_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}

# The Nutrition-Summary columns read, by the nutrient they hold; sodium
# becomes salt. Everything else in it is left out.
CSV_NUTRIENTS = {
    "protein": "Protein (g)",
    "carbs": "Carbohydrates (g)",
    "fat": "Fat (g)",
    "fibre": "Fiber",
    "sugar": "Sugar",
    "saturated_fat": "Saturated Fat",
    "sodium": "Sodium (mg)",
}

# The printable diary's columns read, by their header text in lower case.
PAGE_COLUMNS = {
    "calories": "kcal",
    "carbs": "carbs",
    "fat": "fat",
    "protein": "protein",
    "fiber": "fibre",
    "sugar": "sugar",
    "sat fat": "saturated_fat",
    "saturated fat": "saturated_fat",
    "sodium": "sodium",
}

PAGE_DATE = "qa-regression-report-date"
PAGE_FOODS = "qa-regression-foods-table"
PAGE_TOTALS = "qa-regression-foods-total-data"


class Unreadable(Exception):
    """The file cannot be imported.

    `key` is the reason, one of the import form's error keys, and
    `placeholders` fill in its message.
    """

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


@dataclass(frozen=True)
class Food:
    """One entry to log: a food from the printable diary, or a meal's total from a CSV."""

    day: date
    # The meal's title in MyFitnessPal.
    meal: str
    name: str
    grams: float | None
    # In kcal and g, by the entry fields in NUTRIENTS; None where the file has no value.
    nutrients: dict[str, float | None]


@dataclass(frozen=True)
class Weight:
    """A weight in the file, in the unit it was written in, which the file does not say."""

    day: date
    value: float
    file: str
    line: int


@dataclass(frozen=True)
class Diary:
    """What a file holds to import."""

    foods: list[Food]
    weights: list[Weight]
    # "kg" or "lb", when an Exercise-Summary in the same ZIP gives it.
    weight_unit: str | None = None


def read(path: Path, last_day: date) -> Diary:
    """Read a file, choosing how by its extension, leaving out days after `last_day`.

    Raises Unreadable.
    """
    suffix = path.suffix.lower()
    if suffix == ".zip":
        diary = _read_zip(path)
    elif suffix == ".csv":
        diary = _read_csvs([(path.name, path.read_bytes())])
    elif suffix == ".html":
        diary = _read_page(path.read_bytes().decode("utf-8", errors="replace"))
    else:
        raise Unreadable("not_myfitnesspal")
    return Diary(
        [f for f in diary.foods if f.day <= last_day],
        [w for w in diary.weights if w.day <= last_day],
        diary.weight_unit,
    )


# Meals


def known_meal(title: str) -> str | None:
    """The meal a MyFitnessPal meal title stands for, or None for a meal of their own."""
    text = " ".join(title.split()).casefold()
    if text in ("breakfast", "lunch"):
        return text
    if text in ("dinner", "supper"):
        return "dinner"
    if re.fullmatch(r"snacks?( \(\d+\))?", text):
        return "snacks"
    return None


def other_meals(diary: Diary) -> list[str]:
    """The diary's meal titles that known_meal does not know, in the order they come."""
    return list(dict.fromkeys(f.meal for f in diary.foods if known_meal(f.meal) is None))


def entries(diary: Diary, meals: dict[str, str]) -> list[dict]:
    """The diary's foods as entries, oldest first.

    `meals` maps each title from other_meals to one of MEALS; any missing
    goes under snacks.
    """
    return [
        {
            "day": f.day.isoformat(),
            "meal": known_meal(f.meal) or meals.get(f.meal, IMPORTED_MEAL),
            "name": f.name,
            "grams": f.grams,
            **f.nutrients,
        }
        for f in sorted(diary.foods, key=lambda f: f.day)
    ]


def weights_kg(diary: Diary, unit: str) -> list[tuple[str, float]]:
    """The diary's weights as (day, kg), reading them in `unit`, "kg" or "lb".

    Raises Unreadable for a weight that is not from MIN_KG to MAX_KG.
    """
    factor = KG_PER_LB if unit == "lb" else 1
    weights = []
    for weight in diary.weights:
        kg = round(weight.value * factor, 2)
        if not MIN_KG <= kg <= MAX_KG:
            raise Unreadable("weight_out_of_range", file=weight.file, line=str(weight.line))
        weights.append((weight.day.isoformat(), kg))
    return weights


def _rounded(nutrients: dict[str, float | None]) -> dict[str, float | None]:
    """In kcal and g, with sodium in mg turned into salt."""
    sodium = nutrients.pop("sodium", None)
    nutrients["salt"] = None if sodium is None else sodium * SALT_PER_SODIUM / 1000
    return {
        n: None if value is None else round(value, DIGITS.get(n, 2))
        for n, value in nutrients.items()
    }


# The Premium export's CSVs


def _read_zip(path: Path) -> Diary:
    try:
        with zipfile.ZipFile(path) as archive:
            files = [
                (Path(info.filename).name, archive.read(info))
                for info in archive.infolist()
                if info.filename.lower().endswith(".csv")
            ]
    except zipfile.BadZipFile as err:
        raise Unreadable("not_myfitnesspal") from err
    return _read_csvs(files)


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel saves CSV in the Windows code page unless told otherwise.
        return raw.decode("cp1252", errors="replace")


def _read_csvs(files: list[tuple[str, bytes]]) -> Diary:
    """Read the CSVs, telling them apart by their columns; others are left out."""
    totals: dict[tuple[date, str], dict[str, float | None]] = {}
    weights: dict[date, Weight] = {}
    unit = None
    known = False
    for name, raw in files:
        lines = _rows(name, _text(raw))
        header = next(lines, (0, []))[1]
        columns = {title.strip(): i for i, title in enumerate(header)}
        if "Date" not in columns:
            continue
        if "Meal" in columns and ("Calories" in columns or "Kilojoules" in columns):
            known = True
            _add_totals(totals, name, columns, lines)
        elif "Exercise" in columns:
            known = True
            unit = "kg" if "Kilograms" in columns else "lb" if "Pounds" in columns else unit
        elif "Weight" in columns:
            known = True
            for day, line, row in _dated(name, lines):
                value = _number(name, line, _cell(name, line, row, columns["Weight"]))
                if value is not None:
                    weights[day] = Weight(day, value, name, line)
    if not known:
        raise Unreadable("not_myfitnesspal")
    foods = [
        Food(day, meal, TOTAL_NAME, None, _rounded(nutrients))
        for (day, meal), nutrients in totals.items()
    ]
    return Diary(foods, list(weights.values()), unit)


def _rows(name: str, text: str):
    """Each row with the line it starts on."""
    reader = csv.reader(io.StringIO(text, newline=""))
    start = 1
    try:
        for row in reader:
            yield start, row
            start = reader.line_num + 1
    except csv.Error as err:
        raise Unreadable("bad_line", file=name, line=str(start)) from err


def _dated(name: str, lines):
    """Each row that starts with a date, as (day, line, row).

    MyFitnessPal writes notes with line breaks unquoted, so their later lines
    come as rows of their own, which this leaves out.
    """
    rows = list(lines)
    day_first = _day_first(name, rows)
    for line, row in rows:
        if row and (day := _csv_day(name, line, row[0].strip(), day_first)):
            yield day, line, row


def _day_first(name: str, rows: list[tuple[int, list[str]]]) -> bool:
    """Whether the file's slash dates, which Excel writes, are D/M/YYYY rather than M/D/YYYY.

    Excel writes them in its region's order, which the file does not say. A
    first part over 12 can only be a day, as can a second part over 12. A
    file with neither is read as M/D/YYYY. Raises Unreadable for a file with
    both, naming the line that contradicts the lines before it.
    """
    day_first = month_first = 0
    for line, row in rows:
        if row and (match := SLASH_DATE.fullmatch(row[0].strip())):
            first, second = int(match[1]), int(match[2])
            # Both over 12 is no date at all, which _csv_day refuses.
            if first > 12 >= second:
                day_first = day_first or line
            elif second > 12 >= first:
                month_first = month_first or line
    if day_first and month_first:
        raise Unreadable("mixed_date_orders", file=name, line=str(max(day_first, month_first)))
    return bool(day_first)


def _csv_day(name: str, line: int, text: str, day_first: bool) -> date | None:
    if iso := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        year, month, day = iso.groups()
    elif slash := SLASH_DATE.fullmatch(text):
        first, second, year = slash.groups()
        day, month = (first, second) if day_first else (second, first)
    else:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError as err:
        raise Unreadable("bad_line", file=name, line=str(line)) from err


def _cell(name: str, line: int, row: list[str], index: int) -> str:
    if index >= len(row):
        raise Unreadable("bad_line", file=name, line=str(line))
    return row[index].strip()


def _number(name: str, line: int, text: str) -> float | None:
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as err:
        raise Unreadable("bad_line", file=name, line=str(line)) from err
    # float() reads "nan" and "inf" too.
    if not math.isfinite(number):
        raise Unreadable("bad_line", file=name, line=str(line))
    return number


def _add_totals(totals: dict, name: str, columns: dict[str, int], lines) -> None:
    """Add each row's values to its day and meal's totals; rows at other times add up."""
    for day, line, row in _dated(name, lines):
        meal = " ".join(_cell(name, line, row, columns["Meal"]).split())
        values = {
            n: None
            if title not in columns
            else _number(name, line, _cell(name, line, row, columns[title]))
            for n, title in (("kcal", "Calories"), ("kj", "Kilojoules"), *CSV_NUTRIENTS.items())
        }
        if (kj := values.pop("kj")) is not None:
            values["kcal"] = kj / KJ_PER_KCAL
        meal_totals = totals.setdefault((day, meal), dict.fromkeys(values))
        for n, v in values.items():
            if v is not None:
                meal_totals[n] = (meal_totals[n] or 0.0) + v


# The printable diary page


class _Page(HTMLParser):
    """Collects the diary's dates and food tables' rows, in order, as (kind, text).

    The kinds: "date"; "columns", a table's header; "meal", a meal's title;
    and "food", a food's row. Totals rows and everything else are left out.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[str, str | list[str]]] = []
        self._date: list[str] | None = None
        self._foods_next = False
        self._in_table = False
        self._section: str | None = None
        self._row: list[tuple[str, str]] | None = None
        self._cell: list[str] | None = None
        self._cell_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        test_id = dict(attrs).get("data-testid")
        if test_id == PAGE_DATE:
            self._date = []
        elif test_id == PAGE_FOODS:
            self._foods_next = True
        if tag == "table":
            self._in_table, self._foods_next = self._foods_next, False
        elif not self._in_table:
            return
        elif tag == "thead":
            self._section = "head"
        elif tag == "tbody":
            self._section = "totals" if test_id == PAGE_TOTALS else "body"
        elif tag == "tr":
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell, self._cell_tag = [], tag

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._date is not None:
            self.records.append(("date", _words(self._date)))
            self._date = None
        elif tag == "table":
            self._in_table = False
        elif not self._in_table:
            return
        elif tag in ("th", "td") and self._row is not None and self._cell is not None:
            self._row.append((self._cell_tag, _words(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._end_row(self._row)
            self._row = None
        elif tag in ("thead", "tbody"):
            self._section = None

    def handle_data(self, data: str) -> None:
        if self._date is not None:
            self._date.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _end_row(self, row: list[tuple[str, str]]) -> None:
        if not row:
            return
        if self._section == "head":
            self.records.append(("columns", [text for _tag, text in row]))
        elif self._section == "body":
            # A meal's title row uses td cells; its foods' rows use th.
            if row[0][0] == "td":
                self.records.append(("meal", row[0][1]))
            else:
                self.records.append(("food", [text for _tag, text in row]))


def _words(pieces: list[str]) -> str:
    """The text with each run of whitespace, &nbsp; included, made one space."""
    return " ".join("".join(pieces).split())


def _read_page(html: str) -> Diary:
    page = _Page()
    page.feed(html)
    page.close()
    foods: list[Food] = []
    day = None
    columns: dict[int, str] = {}
    meal = ""
    row = 0
    for kind, value in page.records:
        if kind == "date":
            day, row = _english_day(value), 0
        elif kind == "columns":
            columns = {
                i: PAGE_COLUMNS[title.lower()]
                for i, title in enumerate(value)
                if title.lower() in PAGE_COLUMNS
            }
        elif kind == "meal":
            meal = value
        elif day is not None:
            row += 1
            foods.append(_page_food(day, meal, columns, value, row))
    if not foods:
        raise Unreadable("save_complete")
    return Diary(foods, [])


def _english_day(text: str) -> date:
    """A date such as "Oct 26, 2026". Raises Unreadable for any other."""
    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}), (\d{4})", text)
    month = MONTHS.get(match[1].lower()) if match else None
    if match is None or month is None:
        raise Unreadable("date_not_english")
    try:
        return date(int(match[3]), month, int(match[2]))
    except ValueError as err:
        raise Unreadable("date_not_english") from err


def _page_food(day: date, meal: str, columns: dict[int, str], cells: list[str], row: int) -> Food:
    if "kcal" not in columns.values():
        raise Unreadable("no_calories")
    if len(cells) <= max(columns):
        raise Unreadable("bad_row", day=day.isoformat(), row=str(row))
    nutrients: dict[str, float | None] = {
        n: None for n in ("kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat")
    }
    for index, nutrient in columns.items():
        nutrients[nutrient] = _page_value(cells[index], nutrient, day, row)
    name, grams = _name_and_grams(cells[0])
    return Food(day, meal, name, grams, _rounded(nutrients))


def _page_value(text: str, nutrient: str, day: date, row: int) -> float | None:
    """A cell such as 194, 19g or 29mg: in kcal, in g, or for sodium in mg. -- is no value."""
    if text == "--":
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?) ?(g|mg)?", text)
    if match is None:
        raise Unreadable("bad_row", day=day.isoformat(), row=str(row))
    value = float(match[1])
    unit = match[2] or ("mg" if nutrient == "sodium" else "g")
    if nutrient == "kcal":
        return value
    grams = value / 1000 if unit == "mg" else value
    return grams * 1000 if nutrient == "sodium" else grams


def _name_and_grams(text: str) -> tuple[str, float | None]:
    """Split "<name>, <amount> <unit>" when the unit is grams; else keep the whole text.

    The split is at the last ", " followed by a number.
    """
    match = re.fullmatch(r"(.*), (\d+(?:\.\d+)?) ?(.*)", text)
    if match:
        words = match[3].split()
        if words and words[0].lower() in GRAM_WORDS:
            return match[1], float(match[2])
    return text, None
