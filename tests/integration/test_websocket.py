"""The websocket commands the cards call."""

from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.metron.goals import Goals

from .conftest import mock_entry
from .test_activity import GARMIN, KCAL, anna
from .test_services import added_on

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


async def test_copies_a_meal_to_another_day_and_meal_as_it_was(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    oats = await ok(ws, "food/add", **OATS)
    day = {"person": "debora", "day": "2026-11-08"}
    await ok(ws, "entry/add", **day, meal="breakfast", food_id=oats["id"], grams=60)
    await ok(ws, "entry/add", **day, meal="breakfast", name="Coffee", kcal=2, protein=0.3)
    await ok(ws, "entry/add", **day, meal="lunch", name="Soup", kcal=300)
    db = entry.runtime_data.data.db
    imported = {"day": "2026-11-08", "meal": "breakfast", "name": "Banana", "kcal": 105}
    await hass.async_add_executor_job(
        db.replace_entries, "debora", "myfitnesspal", "2026-11-08", "2026-11-08", [imported]
    )
    copies = await ok(
        ws,
        "meal/copy",
        person="debora",
        from_day="2026-11-08",
        from_meal="breakfast",
        to_day="2026-11-09",
        to_meal="dinner",
    )
    kept = ("food_id", "name", "grams", "kcal", "protein", "carbs", "fat")
    originals = [e for e in db.day_entries("debora", "2026-11-08") if e["meal"] == "breakfast"]
    assert [{k: c[k] for k in kept} for c in copies] == [{k: e[k] for k in kept} for e in originals]
    assert {(c["day"], c["meal"]) for c in copies} == {("2026-11-09", "dinner")}
    # A copy is the person's own, which importing from MyFitnessPal again leaves.
    assert [e["source"] for e in db.day_entries("debora", "2026-11-09")] == [None, None, None]


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


async def test_days_carry_goals_set_before_their_range(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    db = entry.runtime_data.data.db
    for day, kcal in (("2026-11-01", 1800), ("2026-11-05", 1700), ("2026-11-08", 1600)):
        goals = Goals(kcal=kcal, protein=100, carbs=200, fat=60)
        await hass.async_add_executor_job(db.set_day, "debora", day, None, goals)
    await ok(ws, "weight/set", person="debora", day="2026-11-07", kg=69)
    days = (await ok(ws, "days", person="debora", start="2026-11-06", end="2026-11-08"))["days"]
    assert [d["goals"]["kcal"] for d in days] == [1700, 1700, 1600]
    assert [d["weight_kg"] for d in days] == [None, 69, None]
    # One day's goals and weigh-in, too.
    day = await ok(ws, "day", person="debora", day="2026-11-07")
    assert day["goals"] == {"kcal": 1700, "protein": 100, "carbs": 200, "fat": 60}
    assert day["weight_kg"] == 69
    assert (await ok(ws, "day", person="debora", day="2026-11-06"))["weight_kg"] is None


async def test_days_cover_from_one_day_to_400(ws) -> None:
    def days(start: str) -> Any:
        return ws("days", person="debora", start=start, end="2026-11-09")

    assert [d["day"] for d in (await days("2026-11-09"))["result"]["days"]] == ["2026-11-09"]
    assert len((await days("2025-10-06"))["result"]["days"]) == 400
    assert (await days("2025-10-05"))["error"]["code"] == "invalid_range"


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


async def test_subscribers_hear_that_the_people_may_have_changed(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    client = ws.client
    await client.send_json_auto_id({"type": "metron/subscribe"})
    subscribed = await client.receive_json()
    assert subscribed["success"]

    # Setting up, as after any change to a person, tells of each person, then
    # that the people themselves may have changed.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    events = [(await client.receive_json())["event"] for _ in range(3)]
    assert sorted(e["person"] for e in events[:2]) == ["debora", "matteo"]
    assert events[2] == {"person": None, "days": [], "people": True}

    # Unsubscribed, neither kind comes: the next message is a command's reply.
    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": subscribed["id"]})
    assert (await client.receive_json())["success"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (await ws("people"))["type"] == "result"


async def test_every_write_tells_subscribers_what_changed(ws) -> None:
    client = ws.client
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    # A known change, made once a command has answered, closes what it caused.
    closing = {"person": "matteo", "days": []}

    async def until(done: Any) -> tuple[list[dict], list[dict]]:
        replies, events = [], []
        while not done(replies, events):
            message = await client.receive_json()
            if message["type"] == "result":
                replies.append(message)
            else:
                events.append(message["event"])
        return replies, events

    async def announced(type_: str, **fields: Any) -> tuple[dict, list[dict]]:
        """The command's reply, and the changes it announced."""
        await client.send_json_auto_id({"type": f"metron/{type_}", **fields})
        [reply], events = await until(lambda replies, _events: replies)
        await client.send_json_auto_id(
            {"type": "metron/weight/set", "person": "matteo", "day": "2026-01-01", "kg": 80}
        )
        _replies, later = await until(lambda replies, events: replies and closing in events)
        later.remove(closing)
        return reply, events + later

    foods = [{"person": None, "days": []}]
    reply, events = await announced("food/add", **OATS, barcode="5000")
    oats = reply["result"]
    assert events == foods
    assert (await announced("food/update", food_id=oats["id"], kcal=380))[1] == foods
    meal = (
        await announced(
            "meal/add", name="Oats", owner=None, items=[{"food_id": oats["id"], "grams": 40}]
        )
    )[0]["result"]
    reply, events = await announced(
        "meal/update", meal_id=meal["id"], version=meal["version"], name="Morning oats"
    )
    assert events == foods
    changed = reply["result"]

    # A refused write changes nothing, and says so to no one.
    reply, events = await announced(
        "meal/update", meal_id=meal["id"], version=meal["version"], name="Old"
    )
    assert (reply["error"]["code"], events) == ("meal_changed", [])
    reply, events = await announced("food/add", **{**OATS, "name": "Other"}, barcode="5000")
    assert (reply["error"]["code"], events) == ("barcode_taken", [])

    # Entries name the days they changed: both, for one moved between days.
    _reply, events = await announced(
        "meal/log",
        person="debora",
        day="2026-11-08",
        meal="breakfast",
        meal_id=changed["id"],
        version=changed["version"],
        items=[changed["items"][0]["id"]],
    )
    assert events == [{"person": "debora", "days": ["2026-11-08"]}]
    lunch = {"person": "debora", "meal": "lunch", "name": "Soup", "kcal": 300}
    reply, events = await announced("entry/add", **lunch, day="2026-11-07")
    assert events == [{"person": "debora", "days": ["2026-11-07"]}]
    soup = reply["result"]
    _reply, events = await announced("entry/update", entry_id=soup["id"], day="2026-11-05")
    assert events == [{"person": "debora", "days": ["2026-11-05", "2026-11-07"]}]
    _reply, events = await announced("entry/delete", entry_id=soup["id"])
    assert events == [{"person": "debora", "days": ["2026-11-05"]}]
    _reply, events = await announced(
        "meal/copy",
        person="debora",
        from_day="2026-11-08",
        from_meal="breakfast",
        to_day="2026-11-09",
        to_meal="dinner",
    )
    assert events == [{"person": "debora", "days": ["2026-11-09"]}]

    # Weights name the person only.
    weights = [{"person": "debora", "days": []}]
    assert (await announced("weight/set", person="debora", day="2026-11-09", kg=69))[1] == weights
    assert (await announced("weight/delete", person="debora", day="2026-11-09"))[1] == weights

    # Deleting a food takes it out of its meals too: one change to foods and meals.
    assert (await announced("food/delete", food_id=oats["id"]))[1] == foods
    assert (await announced("meals"))[0]["result"] == []


@pytest.mark.parametrize(
    "fields",
    [
        {"day": "yesterday"},
        {"day": "2026-11-09", "kcal": -1},
        {"day": "2026-11-09", "grams": 0},
        {"day": "2026-11-09", "name": "   "},
        # Numbers, but not ones a value can be.
        {"day": "2026-11-09", "kcal": "nan"},
        {"day": "2026-11-09", "kcal": "inf"},
        {"day": "2026-11-09", "protein": "-inf"},
    ],
)
async def test_rejects_bad_values(ws, fields: dict) -> None:
    message = {"person": "debora", "meal": "lunch", "name": "Soup", "kcal": 100, **fields}
    assert await error(ws, "entry/add", **message) == "invalid_format"


@pytest.mark.parametrize("value", ["nan", "inf"])
async def test_refuses_foods_and_weights_that_are_not_numbers(ws, value: str) -> None:
    assert await error(ws, "food/add", **{**OATS, "kcal": value}) == "invalid_format"
    assert await error(ws, "food/add", **{**OATS, "barcode": "5000", "fat": value}) == (
        "invalid_format"
    )
    assert (
        await error(ws, "weight/set", person="debora", day="2026-11-09", kg=value)
        == "invalid_format"
    )


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


async def test_a_day_without_goals_of_its_own_has_the_last_day_s_base(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    # A marathon on the 7th, then Home Assistant off for all of the 8th.
    freezer.move_to("2026-11-07T12:00:00+00:00")
    hass.states.async_set(GARMIN, "2400", KCAL)
    entry = mock_entry(anna(), data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to("2026-11-09T12:00:00+00:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    async def ask(type_: str, **fields: Any) -> Any:
        await client.send_json_auto_id({"type": f"metron/{type_}", "person": "anna", **fields})
        return (await client.receive_json())["result"]

    marathon = {"kcal": 2624, "protein": 131.2, "carbs": 328.0, "fat": 87.5}
    # 2,624 less the 1,255.83 activity added: the base, its macros scaled to it.
    base = {"kcal": 1368, "protein": 68.4, "carbs": 171.0, "fat": 45.6}
    assert (await ask("day", day="2026-11-08"))["goals"] == base
    days = (await ask("days", start="2026-11-07", end="2026-11-09"))["days"]
    assert [d["goals"] for d in days] == [marathon, base, base]


async def test_a_day_has_activity_with_today_s_status_only(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = mock_entry(anna(active_calories_entity=None), data=entry_data)
    data = (await added_on(hass, freezer, "2026-11-08", entry)).runtime_data.data
    await data.async_log_activity(data.people["anna"], "2026-11-08", 906)
    client = await hass_ws_client(hass)

    async def activity(day: str) -> dict | None:
        await client.send_json_auto_id({"type": "metron/day", "person": "anna", "day": day})
        return (await client.receive_json())["result"]["activity"]

    today = await activity("2026-11-09")
    assert (today["source"], today["measured"], today["status"]) == ("action", None, "waiting")
    past = await activity("2026-11-08")
    assert (past["source"], past["measured"], past["status"]) == ("action", 906, None)
    assert await activity("2026-11-07") is None
