"""The websocket commands the cards call."""

from typing import Any

import pytest
from homeassistant.core import HomeAssistant

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}


async def ok(ws, type_: str, **fields: Any) -> Any:
    reply = await ws(type_, **fields)
    assert reply["success"], reply
    return reply["result"]


async def error(ws, type_: str, **fields: Any) -> str:
    reply = await ws(type_, **fields)
    assert not reply["success"], reply
    return reply["error"]["code"]


async def test_lists_people_with_their_bands(ws) -> None:
    people = {p["name"]: p for p in await ok(ws, "people")}
    assert people["Matteo"]["id"] == "matteo"
    assert people["Matteo"]["obese_from_kg"] == 97.2
    assert people["Debora"]["start_date"] == "2026-11-01"


async def test_logging_a_saved_food_copies_it_scaled(ws) -> None:
    food = await ok(ws, "food/add", **OATS)
    entry = await ok(
        ws,
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="breakfast",
        food_id=food["id"],
        grams=60,
    )
    assert entry["name"] == "Porridge oats"
    assert entry["kcal"] == pytest.approx(233.4)
    assert entry["protein"] == pytest.approx(10.14)
    assert entry["fibre"] is None
    # Changing the food leaves the entry alone.
    await ok(ws, "food/update", food_id=food["id"], kcal=1)
    day = await ok(ws, "day", person="debora", day="2026-11-09")
    assert day["entries"][0]["kcal"] == pytest.approx(233.4)


async def test_quick_add_needs_a_name_and_kcal(ws) -> None:
    entry = await ok(
        ws,
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="dinner",
        name="Restaurant pizza",
        kcal=900,
    )
    assert entry["grams"] is None
    assert (
        await error(
            ws, "entry/add", person="debora", day="2026-11-09", meal="dinner", name="No kcal"
        )
        == "invalid_format"
    )
    assert (
        await error(ws, "entry/add", person="debora", day="2026-11-09", meal="dinner", food_id=1)
        == "invalid_format"
    )


async def test_rejects_future_days_and_unknown_people(ws) -> None:
    assert (
        await error(
            ws, "entry/add", person="debora", day="2026-11-10", meal="dinner", name="x", kcal=1
        )
        == "invalid_format"
    )
    assert await error(ws, "day", person="nobody", day="2026-11-09") == "not_found"
    assert (
        await error(
            ws, "entry/add", person="debora", day="2026-11-09", meal="brunch", name="x", kcal=1
        )
        == "invalid_format"
    )


async def test_new_grams_scale_an_entry(ws) -> None:
    food = await ok(ws, "food/add", **OATS)
    entry = await ok(
        ws,
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="breakfast",
        food_id=food["id"],
        grams=60,
    )
    changed = await ok(ws, "entry/update", entry_id=entry["id"], grams=90, meal="snacks")
    assert changed["kcal"] == pytest.approx(entry["kcal"] * 1.5)
    assert changed["meal"] == "snacks"
    await ok(ws, "entry/delete", entry_id=entry["id"])
    assert await error(ws, "entry/delete", entry_id=entry["id"]) == "not_found"


async def test_copies_a_meal_to_another_day(ws) -> None:
    for name in ("Eggs", "Toast"):
        await ok(
            ws,
            "entry/add",
            person="debora",
            day="2026-11-08",
            meal="breakfast",
            name=name,
            kcal=100,
        )
    await ok(ws, "entry/add", person="debora", day="2026-11-08", meal="lunch", name="X", kcal=1)
    copies = await ok(
        ws,
        "meal/copy",
        person="debora",
        from_day="2026-11-08",
        from_meal="breakfast",
        to_day="2026-11-09",
        to_meal="breakfast",
    )
    assert [c["name"] for c in copies] == ["Eggs", "Toast"]
    assert {c["day"] for c in copies} == {"2026-11-09"}


async def test_days_carry_goals_forward(ws) -> None:
    await ok(ws, "entry/add", person="debora", day="2026-11-08", meal="lunch", name="X", kcal=10)
    await ok(ws, "weight/set", person="debora", day="2026-11-08", kg=69)
    days = (await ok(ws, "days", person="debora", start="2026-11-07", end="2026-11-09"))["days"]
    assert [d["day"] for d in days] == ["2026-11-07", "2026-11-08", "2026-11-09"]
    assert days[1]["meals"]["lunch"]["kcal"] == 10
    assert days[1]["weight_kg"] == 69
    # Goals were first recorded when the integration set up, today.
    assert days[0]["goals"] is None
    assert days[2]["goals"]["kcal"] > 0
    assert (
        await error(ws, "days", person="debora", start="2026-11-09", end="2026-11-08")
        == "invalid_range"
    )


async def test_foods_search_recent_and_barcodes(ws) -> None:
    oats = await ok(
        ws, "food/add", **OATS, barcode="5000", portions=[{"name": "Bowl", "grams": 40}]
    )
    assert await error(ws, "food/add", **OATS, barcode="5000") == "barcode_taken"
    assert await error(ws, "food/add", name="No macros", kcal=1) == "invalid_format"
    assert [f["id"] for f in await ok(ws, "food/search", query="oat")] == [oats["id"]]
    assert (await ok(ws, "food/barcode", barcode="5000"))["portions"] == [
        {"name": "Bowl", "grams": 40}
    ]
    assert await ok(ws, "food/barcode", barcode="nope") is None
    await ok(
        ws,
        "entry/add",
        person="debora",
        day="2026-11-09",
        meal="lunch",
        food_id=oats["id"],
        grams=10,
    )
    assert [f["id"] for f in await ok(ws, "food/recent", person="debora")] == [oats["id"]]
    assert await ok(ws, "food/recent", person="matteo") == []
    await ok(ws, "food/delete", food_id=oats["id"])
    assert await error(ws, "food/delete", food_id=oats["id"]) == "not_found"


async def test_weights(ws) -> None:
    await ok(ws, "weight/set", person="matteo", day="2017-05-31", kg=95.2)
    await ok(ws, "weight/set", person="matteo", day="2026-11-09", kg=89.4)
    await ok(ws, "weight/set", person="matteo", day="2026-11-09", kg=89.1)
    assert await ok(ws, "weights", person="matteo") == [
        {"day": "2017-05-31", "kg": 95.2},
        {"day": "2026-11-09", "kg": 89.1},
    ]
    await ok(ws, "weight/delete", person="matteo", day="2026-11-09")
    assert len(await ok(ws, "weights", person="matteo", start="2026-01-01")) == 0
    assert await error(ws, "weight/set", person="matteo", day="2026-11-09", kg=5) == (
        "invalid_format"
    )


async def test_subscribers_hear_about_changes(hass: HomeAssistant, ws) -> None:
    client = ws.client
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id(
        {
            "type": "metron/entry/add",
            "person": "debora",
            "day": "2026-11-08",
            "meal": "lunch",
            "name": "X",
            "kcal": 1,
        }
    )
    messages = [await client.receive_json(), await client.receive_json()]
    event = next(m for m in messages if m["type"] == "event")
    assert event["event"] == {"person": "debora", "days": ["2026-11-08"]}


@pytest.mark.parametrize(
    "fields",
    [
        {"day": "yesterday"},
        {"day": "2026-11-09", "kcal": -1},
        {"day": "2026-11-09", "grams": 0},
        {"day": "2026-11-09", "name": "   "},
    ],
)
async def test_rejects_bad_values(ws, fields: dict) -> None:
    message = {"person": "debora", "meal": "lunch", "name": "Soup", "kcal": 100, **fields}
    assert await error(ws, "entry/add", **message) == "invalid_format"


async def test_says_when_food_or_entries_are_missing(ws) -> None:
    assert (
        await error(
            ws, "entry/add", person="debora", day="2026-11-09", meal="lunch", food_id=999, grams=10
        )
        == "not_found"
    )
    assert await error(ws, "entry/update", entry_id=999, grams=10) == "not_found"
    assert await error(ws, "food/update", food_id=999, kcal=1) == "not_found"


async def test_refuses_to_empty_required_values(ws) -> None:
    entry = await ok(
        ws, "entry/add", person="debora", day="2026-11-09", meal="lunch", name="Soup", kcal=100
    )
    assert await error(ws, "entry/update", entry_id=entry["id"], kcal=None) == "invalid_format"
    food = await ok(ws, "food/add", **OATS)
    assert await error(ws, "food/update", food_id=food["id"], protein=None) == "invalid_format"


async def test_refuses_a_barcode_another_food_has(ws) -> None:
    await ok(ws, "food/add", **OATS, barcode="5000")
    other = await ok(ws, "food/add", **{**OATS, "name": "Other"})
    assert await error(ws, "food/update", food_id=other["id"], barcode="5000") == "barcode_taken"


async def test_answers_not_loaded_while_the_integration_is_unloaded(
    hass: HomeAssistant, ws
) -> None:
    entry = hass.config_entries.async_entries("metron")[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await error(ws, "people") == "not_loaded"
