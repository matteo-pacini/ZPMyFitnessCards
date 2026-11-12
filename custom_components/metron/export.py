"""A person's data as a ZIP of CSVs, downloaded from the link their menu's "Export data" shows."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.decorators import require_admin
from homeassistant.util import slugify

from .const import DOMAIN, NUTRIENTS
from .data import loaded_data, today
from .db import Database

PATH = f"/api/{DOMAIN}/export/{{person}}"

# Each nutrient's column, with its unit.
UNITS = {n: n if n == "kcal" else f"{n}_g" for n in NUTRIENTS}

ENTRY_COLUMNS = [
    "day",
    "meal",
    "name",
    "grams",
    *UNITS.values(),
    "food_id",
    "source",
    "logged_at",
]
WEIGHT_COLUMNS = ["day", "weight_kg"]
FOOD_COLUMNS = [
    "id",
    "name",
    "barcode",
    *(f"{column}_per_100g" for column in UNITS.values()),
    "portions",
    "saved_by",
]
MEAL_COLUMNS = ["owner", "meal", "item", "food_id", "grams", *UNITS.values()]
ACTIVITY_COLUMNS = [
    "day",
    "source",
    "measured_kcal",
    "counted_kcal",
    "added_kcal",
    "allowed_kcal",
    "share_pct",
    "cap_kcal",
]

# The owner column of meals everyone shares.
EVERYONE = "Everyone"


def _number(value: float | None) -> str:
    return "" if value is None else str(round(value, 3)).removesuffix(".0")


def _csv(columns: list[str], rows: list[list[Any]]) -> bytes:
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(columns)
    writer.writerows(rows)
    # With a byte order mark, as MyFitnessPal's own export has, so that
    # Excel reads names in UTF-8.
    return text.getvalue().encode("utf-8-sig")


def build_zip(db: Database, person: str) -> bytes:
    """entries.csv, weights.csv, foods.csv, meals.csv and activity.csv for a person, zipped.

    meals.csv has everyone's meals and the person's own, an item a row. An
    item of a saved food gives the food and grams, as its values follow the
    food; a fixed item gives its values. activity.csv has a row for each day
    with active calories: its source, a sensor's entity ID or "action", and
    what was measured, what counted, what the activity level allowed for and
    what was added to the goal, with the share and cap that day. Blocks.
    """
    data = db.export(person)
    people = data["people"]
    entries = [
        [
            e["day"],
            e["meal"],
            e["name"],
            _number(e["grams"]),
            *(_number(e[n]) for n in NUTRIENTS),
            e["food_id"] or "",
            e["source"] or "",
            e["created_at"],
        ]
        for e in data["entries"]
    ]
    weights = [[w["day"], _number(w["kg"])] for w in data["weights"]]
    foods = [
        [
            f["id"],
            f["name"],
            f["barcode"] or "",
            *(_number(f[n]) for n in NUTRIENTS),
            json.dumps(f["portions"], ensure_ascii=False) if f["portions"] else "",
            people.get(f["saved_by"], f["saved_by"]) if f["saved_by"] else "",
        ]
        for f in data["foods"]
    ]
    meals = [
        [
            people.get(m["owner"], m["owner"]) if m["owner"] else EVERYONE,
            m["name"],
            i["name"],
            i["food_id"] or "",
            _number(i["grams"]),
            *(("",) * len(NUTRIENTS) if i["food_id"] else (_number(i[n]) for n in NUTRIENTS)),
        ]
        for m in data["meals"]
        for i in m["items"]
    ]
    activity = [
        [
            a["day"],
            a["source"],
            *(_number(a[n]) for n in ("measured", "counted", "added", "allowed", "share", "cap")),
        ]
        for a in data["activity"]
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("entries.csv", _csv(ENTRY_COLUMNS, entries))
        archive.writestr("weights.csv", _csv(WEIGHT_COLUMNS, weights))
        archive.writestr("foods.csv", _csv(FOOD_COLUMNS, foods))
        archive.writestr("meals.csv", _csv(MEAL_COLUMNS, meals))
        archive.writestr("activity.csv", _csv(ACTIVITY_COLUMNS, activity))
    return buffer.getvalue()


class ExportView(HomeAssistantView):
    """GET a person's ZIP, by their key. Admins only; the flow's link is signed."""

    url = PATH
    name = f"api:{DOMAIN}:export"

    @require_admin
    async def get(self, request: web.Request, person: str) -> web.Response:
        """The ZIP as an attachment, or 404 for an unknown person."""
        data = loaded_data(request.app[KEY_HASS])
        if data is None or person not in data.people:
            raise web.HTTPNotFound
        body = await data.async_read(build_zip, data.db, person)
        name = slugify(data.people[person].name, separator="-")
        filename = f"metron-{name}-{today().isoformat()}.zip"
        return web.Response(
            body=body,
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
