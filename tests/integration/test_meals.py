"""Saved meals, and who saved each food: the database, the websocket commands and the action."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from custom_components.metron.const import DOMAIN
from custom_components.metron.db import (
    EVERYONE,
    FOODS,
    MEAL_ITEMS,
    Database,
    FoodGoneError,
    MealChangedError,
    MealExistsError,
)

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}
MILK = {"name": "Semi-skimmed milk", "kcal": 49, "protein": 3.6, "carbs": 4.8, "fat": 1.7}
COFFEE = {"name": "Coffee", "grams": 250, "kcal": 20, "protein": 1, "carbs": 1.5, "fat": 1}


@pytest.fixture
def db(database_url: str) -> Database:
    """An open database, once on SQLite and once on Postgres."""
    database = Database(database_url)
    database.open()
    yield database
    database.close()


def names(meals: list[dict]) -> list[tuple[str, str | None]]:
    return [(m["name"], m["owner"]) for m in meals]


# The database


def test_a_meal_links_foods_and_keeps_fixed_values(db: Database) -> None:
    oats = db.add_food(OATS)
    meal = db.add_meal(EVERYONE, "Porridge bowl", [{"food_id": oats["id"], "grams": 60}, COFFEE])
    assert (meal["name"], meal["owner"]) == ("Porridge bowl", None)
    linked, fixed = meal["items"]
    assert (linked["food_id"], linked["name"], linked["grams"]) == (oats["id"], "Porridge oats", 60)
    assert linked["kcal"] == pytest.approx(233.4)
    assert linked["fibre"] is None
    assert {k: fixed[k] for k in ("food_id", "name", "grams", "kcal", "carbs")} == {
        "food_id": None,
        "name": "Coffee",
        "grams": 250,
        "kcal": 20,
        "carbs": 1.5,
    }
    # A linked item follows its food.
    db.update_food(oats["id"], {"name": "Oats", "kcal": 400})
    linked = db.meal(meal["id"])["items"][0]
    assert (linked["name"], linked["kcal"]) == ("Oats", 240)
    assert db.meal(meal["id"] + 1) is None


def test_lists_everyone_s_meals_and_a_person_s_own_a_to_z(db: Database) -> None:
    db.add_meal("debora", "usual breakfast", [COFFEE])
    db.add_meal(EVERYONE, "Pasta night", [COFFEE])
    db.add_meal("matteo", "Post-workout shake", [COFFEE])
    assert names(db.meals("debora")) == [("Pasta night", None), ("usual breakfast", "debora")]
    assert names(db.meals()) == [
        ("Pasta night", None),
        ("Post-workout shake", "matteo"),
        ("usual breakfast", "debora"),
    ]


def test_names_are_unique_within_what_one_person_sees(db: Database) -> None:
    db.add_meal(EVERYONE, "Pasta night", [COFFEE])
    db.add_meal("debora", "Usual breakfast", [COFFEE])
    # Someone else's own meal may share a name; case does not make a new one.
    db.add_meal("matteo", "usual BREAKFAST", [COFFEE])
    with pytest.raises(MealExistsError) as clash:
        db.add_meal("debora", "PASTA NIGHT", [COFFEE])
    assert clash.value.owner == EVERYONE
    with pytest.raises(MealExistsError) as clash:
        db.add_meal("debora", "usual breakfast", [COFFEE])
    assert clash.value.owner == "debora"
    # Everyone's meal clashes with anyone's.
    with pytest.raises(MealExistsError) as clash:
        db.add_meal(EVERYONE, "Usual Breakfast", [COFFEE])
    assert clash.value.owner in ("debora", "matteo")
    assert len(db.meals()) == 3


def test_changes_a_meal_as_it_was_read(db: Database) -> None:
    oats = db.add_food(OATS)
    meal = db.add_meal("debora", "Usual breakfast", [COFFEE])
    db.add_meal(EVERYONE, "Pasta night", [COFFEE])
    # Its own name in another case is fine.
    changed = db.update_meal(meal["id"], meal["version"], {"name": "Usual Breakfast"})
    assert changed["name"] == "Usual Breakfast"
    assert changed["version"] == meal["version"] + 1
    with pytest.raises(MealChangedError):
        db.update_meal(meal["id"], meal["version"], {"name": "Stale"})
    with pytest.raises(MealExistsError):
        db.update_meal(meal["id"], changed["version"], {"name": "pasta night"})
    items = [{"food_id": oats["id"], "grams": 50}]
    moved = db.update_meal(meal["id"], changed["version"], {"owner": EVERYONE, "items": items})
    assert moved["owner"] is None
    assert [i["name"] for i in moved["items"]] == ["Porridge oats"]
    with pytest.raises(FoodGoneError):
        db.update_meal(meal["id"], moved["version"], {"items": [{"food_id": 999, "grams": 1}]})
    # Nothing of a refused change is kept.
    assert db.meal(meal["id"]) == moved


def test_deletes_a_meal_as_it_was_read(db: Database) -> None:
    meal = db.add_meal(EVERYONE, "Pasta night", [COFFEE])
    with pytest.raises(MealChangedError):
        db.delete_meal(meal["id"], meal["version"] + 1)
    db.delete_meal(meal["id"], meal["version"])
    assert db.meals() == []
    with pytest.raises(MealChangedError):
        db.delete_meal(meal["id"], meal["version"])


def test_a_meal_with_a_food_that_is_gone_is_not_saved(db: Database) -> None:
    with pytest.raises(FoodGoneError):
        db.add_meal(EVERYONE, "Ghost", [COFFEE, {"food_id": 999, "grams": 1}])
    assert db.meals() == []


def test_logs_a_meal_s_items_all_or_none(db: Database) -> None:
    oats = db.add_food(OATS)
    meal = db.add_meal(EVERYONE, "Porridge bowl", [{"food_id": oats["id"], "grams": 60}, COFFEE])
    _linked, fixed = meal["items"]
    entries = db.log_meal("debora", "2026-11-09", "lunch", meal["id"], meal["version"])
    assert [(e["name"], e["meal"], e["food_id"]) for e in entries] == [
        ("Porridge oats", "lunch", oats["id"]),
        ("Coffee", "lunch", None),
    ]
    assert entries[0]["kcal"] == pytest.approx(233.4)
    assert entries[1]["grams"] == 250
    only = db.log_meal("debora", "2026-11-09", "snacks", meal["id"], None, [fixed["id"]])
    assert [e["name"] for e in only] == ["Coffee"]
    for item_ids, version in (([fixed["id"], 999], None), (None, meal["version"] + 1)):
        with pytest.raises(MealChangedError):
            db.log_meal("debora", "2026-11-09", "dinner", meal["id"], version, item_ids)
    with pytest.raises(MealChangedError):
        db.log_meal("debora", "2026-11-09", "dinner", 999)
    assert len(db.day_entries("debora", "2026-11-09")) == 3


def test_a_person_logs_only_everyone_s_meals_and_their_own(db: Database) -> None:
    his = db.add_meal("matteo", "Post-workout shake", [COFFEE])
    with pytest.raises(MealChangedError):
        db.log_meal("debora", "2026-11-09", "snacks", his["id"])
    assert len(db.log_meal("matteo", "2026-11-09", "snacks", his["id"])) == 1


def test_finds_meals_by_name_in_any_case_everyone_s_first(db: Database) -> None:
    db.add_meal("matteo", "Shake", [COFFEE])
    db.add_meal("debora", "SHAKE", [COFFEE])
    assert [m["owner"] for m in db.meals_named("shake")] == ["matteo", "debora"]
    db.delete_meal(*(lambda m: (m["id"], m["version"]))(db.meals_named("shake")[0]))
    db.add_meal(EVERYONE, "Toast", [COFFEE])
    db.add_meal("debora", "Toasts", [COFFEE])
    assert names(db.meals_named("TOAST")) == [("Toast", None)]
    assert db.meals_named("Nothing") == []


def test_deleting_a_food_takes_it_out_of_meals_and_deletes_emptied_ones(db: Database) -> None:
    banana = db.add_food({**OATS, "name": "Banana"})
    milk = db.add_food(MILK)
    item = {"food_id": banana["id"], "grams": 118}
    usual = db.add_meal("debora", "Usual breakfast", [item, {"food_id": milk["id"], "grams": 200}])
    snack = db.add_meal(EVERYONE, "Banana snack", [item, item])
    db.add_meal(EVERYONE, "Coffee", [COFFEE])
    assert db.meals_with_food(banana["id"]) == [
        {"id": snack["id"], "name": "Banana snack", "owner": None, "emptied": True},
        {"id": usual["id"], "name": "Usual breakfast", "owner": "debora", "emptied": False},
    ]
    assert db.meals_with_food(999) == []
    assert db.delete_food(banana["id"])
    assert names(db.meals()) == [("Coffee", None), ("Usual breakfast", "debora")]
    left = db.meal(usual["id"])
    assert [i["name"] for i in left["items"]] == ["Semi-skimmed milk"]
    # Someone holding the meal as it was can no longer change it.
    assert left["version"] == usual["version"] + 1
    assert not db.delete_food(banana["id"])


def test_adds_entries_all_or_none(db: Database) -> None:
    good = {"day": "2026-11-09", "meal": "lunch", "name": "Soup", "kcal": 100}
    with pytest.raises(IntegrityError):
        db.add_entries("debora", [good, {**good, "meal": "brunch"}])
    assert db.day_entries("debora", "2026-11-09") == []
    added = db.add_entries("debora", [good, {**good, "name": "Bread"}])
    assert [e["name"] for e in added] == ["Soup", "Bread"]


def test_records_who_saved_a_food(db: Database) -> None:
    assert db.add_food(OATS | {"saved_by": "debora"})["saved_by"] == "debora"
    assert db.add_food(MILK)["saved_by"] is None
    # Editing a food leaves who saved it.
    oats = db.foods_named("porridge oats")[0]
    assert db.update_food(oats["id"], {"kcal": 1, "saved_by": "matteo"})["saved_by"] == "debora"


def test_a_removed_person_s_meals_become_everyone_s(db: Database) -> None:
    db.sync_people([("ana", "Ana"), ("debora", "Debora")])
    for owner, name in (
        ("debora", "Usual breakfast"),
        (EVERYONE, "Usual breakfast (Ana)"),
        ("debora", "Smoothie"),
        ("ana", "Usual breakfast"),
        ("ana", "Smoothie"),
        ("ana", "Frozen berries bowl"),
        ("gone", "Gone's meal"),
    ):
        db.add_meal(owner, name, [COFFEE])
    db.add_food(OATS | {"saved_by": "ana"})
    db.add_food(MILK | {"saved_by": "debora"})
    db.adopt_removed(["debora"])
    # Sorted here: the databases' collations order "(Ana 2)" and "(Ana)" differently.
    assert sorted(names(db.meals())) == [
        ("Frozen berries bowl", None),
        # Not known by name: the key stands in.
        ("Gone's meal", None),
        ("Smoothie", "debora"),
        ("Smoothie (Ana)", None),
        ("Usual breakfast", "debora"),
        ("Usual breakfast (Ana 2)", None),
        ("Usual breakfast (Ana)", None),
    ]
    assert {f["name"]: f["saved_by"] for f in db.search_foods("", 10)} == {
        "Porridge oats": None,
        "Semi-skimmed milk": "debora",
    }
    # Run again, as every setup does, it changes nothing.
    before = db.meals()
    db.adopt_removed(["debora"])
    assert db.meals() == before


def test_deleting_a_person_s_data_keeps_what_others_use(db: Database) -> None:
    db.sync_people([("ana", "Ana"), ("debora", "Debora")])
    only_hers = db.add_food({**OATS, "name": "Only hers"} | {"saved_by": "ana"})
    logged = db.add_food({**OATS, "name": "Logged by Debora"} | {"saved_by": "ana"})
    in_meal = db.add_food({**OATS, "name": "In a meal"} | {"saved_by": "ana"})
    in_her_meal = db.add_food({**OATS, "name": "In her meal"} | {"saved_by": "ana"})
    theirs = db.add_food({**OATS, "name": "Debora's"} | {"saved_by": "debora"})

    def log(person: str, food: dict) -> None:
        entry = {"day": "2026-11-09", "meal": "lunch", "name": "x", "kcal": 1}
        db.add_entry(person, entry | {"food_id": food["id"]})

    for food in (only_hers, logged, theirs):
        log("ana", food)
    log("debora", logged)
    db.add_meal(EVERYONE, "Shared", [{"food_id": in_meal["id"], "grams": 1}])
    db.add_meal("ana", "Hers", [{"food_id": in_her_meal["id"], "grams": 1}])
    db.add_meal("debora", "Debora's", [COFFEE])
    db.delete_person("ana")
    assert {f["name"]: f["saved_by"] for f in db.search_foods("", 10)} == {
        "Debora's": "debora",
        "In a meal": None,
        "Logged by Debora": None,
    }
    assert names(db.meals()) == [("Debora's", "debora"), ("Shared", None)]
    assert db.day_entries("ana", "2026-11-09") == []
    assert len(db.day_entries("debora", "2026-11-09")) == 1


def test_meal_items_go_with_their_meal_and_food(db: Database) -> None:
    """The foreign keys clean up after a delete that skips the methods above."""
    oats = db.add_food(OATS)
    meal = db.add_meal(EVERYONE, "Porridge bowl", [{"food_id": oats["id"], "grams": 60}])
    with db._db.begin() as conn:
        conn.execute(FOODS.delete().where(FOODS.c.id == oats["id"]))
        assert conn.execute(select(MEAL_ITEMS)).all() == []
        conn.execute(insert(MEAL_ITEMS).values(meal_id=meal["id"], position=0, name="x", kcal=1))
    db.delete_meal(meal["id"], db.meal(meal["id"])["version"])
    with db._db.connect() as conn:
        assert conn.execute(select(MEAL_ITEMS)).all() == []


# The websocket commands


async def ok(ws, type_: str, **fields: Any) -> Any:
    reply = await ws(type_, **fields)
    assert reply["success"], reply
    return reply["result"]


async def error(ws, type_: str, **fields: Any) -> dict:
    reply = await ws(type_, **fields)
    assert not reply["success"], reply
    return reply["error"]


async def test_saves_lists_changes_and_deletes_meals(ws) -> None:
    oats = await ok(ws, "food/add", **OATS)
    items = [{"food_id": oats["id"], "grams": 60}, {"name": "Coffee", "kcal": 20}]
    shared = await ok(ws, "meal/add", name="Porridge bowl", owner=None, items=items)
    hers = await ok(ws, "meal/add", name="Usual breakfast", owner="debora", items=items[1:])
    await ok(ws, "meal/add", name="Shake", owner="matteo", items=items[1:])
    assert names(await ok(ws, "meals", person="debora")) == [
        ("Porridge bowl", None),
        ("Usual breakfast", "debora"),
    ]
    assert len(await ok(ws, "meals")) == 3
    changed = await ok(
        ws,
        "meal/update",
        meal_id=hers["id"],
        version=hers["version"],
        name="Her usual",
        owner=None,
    )
    assert (changed["name"], changed["owner"]) == ("Her usual", None)
    back = await ok(
        ws, "meal/update", meal_id=hers["id"], version=changed["version"], owner="debora"
    )
    assert back["owner"] == "debora"
    assert await ok(ws, "food/meals", food_id=oats["id"]) == [
        {"id": shared["id"], "name": "Porridge bowl", "owner": None, "emptied": False}
    ]
    await ok(ws, "meal/delete", meal_id=shared["id"], version=shared["version"])
    assert names(await ok(ws, "meals", person="debora")) == [("Her usual", "debora")]


async def test_says_whose_meal_has_the_name(ws) -> None:
    item = [{"name": "Coffee", "kcal": 20}]
    await ok(ws, "meal/add", name="Pasta night", owner=None, items=item)
    hers = await ok(ws, "meal/add", name="Usual breakfast", owner="debora", items=item)
    clash = await error(ws, "meal/add", name="pasta night", owner="debora", items=item)
    assert clash["code"] == "meal_exists"
    assert clash["translation_key"] == "meal_exists"
    assert clash["translation_domain"] == "metron"
    assert clash["translation_placeholders"] == {"owner": ""}
    clash = await error(ws, "meal/add", name="USUAL breakfast", owner=None, items=item)
    assert clash["translation_placeholders"] == {"owner": "debora"}
    clash = await error(
        ws,
        "meal/update",
        meal_id=hers["id"],
        version=hers["version"],
        name="Pasta Night",
    )
    assert (clash["code"], clash["translation_placeholders"]) == ("meal_exists", {"owner": ""})


async def test_refuses_meals_changed_meanwhile(ws) -> None:
    item = [{"name": "Coffee", "kcal": 20}]
    meal = await ok(ws, "meal/add", name="Toast", owner=None, items=item)
    await ok(ws, "meal/update", meal_id=meal["id"], version=meal["version"], name="Toasts")
    stale = {"meal_id": meal["id"], "version": meal["version"]}
    for command, fields in (
        ("meal/update", {"name": "Bread"}),
        ("meal/delete", {}),
        ("meal/log", {"person": "debora", "day": "2026-11-09", "meal": "lunch", "items": [1]}),
    ):
        refused = await error(ws, command, **stale, **fields)
        assert refused["code"] == "meal_changed", command
        assert "translation_key" not in refused
    day = await ok(ws, "day", person="debora", day="2026-11-09")
    assert day["entries"] == []


async def test_logs_the_ticked_items_of_a_meal(hass: HomeAssistant, ws) -> None:
    oats = await ok(ws, "food/add", **OATS)
    items = [{"food_id": oats["id"], "grams": 60}, {"name": "Coffee", "kcal": 20, "grams": 250}]
    meal = await ok(ws, "meal/add", name="Porridge bowl", owner=None, items=items)
    linked, _coffee = meal["items"]
    client = ws.client
    await client.send_json_auto_id({"type": "metron/subscribe"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id(
        {
            "type": "metron/meal/log",
            "person": "debora",
            "day": "2026-11-09",
            "meal": "breakfast",
            "meal_id": meal["id"],
            "version": meal["version"],
            "items": [linked["id"]],
        }
    )
    messages = [await client.receive_json(), await client.receive_json()]
    event = next(m for m in messages if m["type"] == "event")
    assert event["event"] == {"person": "debora", "days": ["2026-11-09"]}
    entries = next(m for m in messages if m["type"] == "result")["result"]
    assert [(e["name"], e["grams"], e["meal"]) for e in entries] == [
        ("Porridge oats", 60, "breakfast")
    ]


async def test_saves_fixed_values_left_empty(ws) -> None:
    """As Save as meal sends a quick add's entry: grams and macros may be empty."""
    nutrients = ("protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt")
    empty = dict.fromkeys(nutrients)
    rice = {"name": "Rice", "grams": None, "kcal": 200, **empty}
    meal = await ok(ws, "meal/add", name="Rice bowl", owner="debora", items=[rice])
    assert {k: meal["items"][0][k] for k in ("food_id", "grams", "kcal", "protein")} == {
        "food_id": None,
        "grams": None,
        "kcal": 200,
        "protein": None,
    }
    no_grams = [{"food_id": 1, "grams": None}]
    refused = await error(ws, "meal/add", name="x", owner=None, items=no_grams)
    assert refused["code"] == "invalid_format"


async def test_meal_commands_check_owners_foods_and_items(ws) -> None:
    item = [{"name": "Coffee", "kcal": 20}]
    assert (await error(ws, "meal/add", name="x", owner="nobody", items=item))["code"] == (
        "not_found"
    )
    gone = [{"food_id": 999, "grams": 1}]
    assert (await error(ws, "meal/add", name="x", owner=None, items=gone))["code"] == "not_found"
    meal = await ok(ws, "meal/add", name="x", owner=None, items=item)
    stamp = {"meal_id": meal["id"], "version": meal["version"]}
    assert (await error(ws, "meal/update", **stamp, owner="nobody"))["code"] == "not_found"
    assert (await error(ws, "meal/update", **stamp, items=gone))["code"] == "not_found"
    for fields in (
        {"name": "x", "owner": None, "items": []},
        {"name": " ", "owner": None, "items": item},
        {"name": "x", "owner": None, "items": [{"name": "No kcal"}]},
        {"name": "x", "owner": None, "items": [{"food_id": 1}]},
        {"name": "x", "owner": None, "items": [{"name": "Coffee", "kcal": -1}]},
    ):
        assert (await error(ws, "meal/add", **fields))["code"] == "invalid_format", fields
    refused = await error(
        ws, "meal/log", person="debora", day="2026-11-09", meal="lunch", **stamp, items=[]
    )
    assert refused["code"] == "invalid_format"
    assert (await error(ws, "meals", person="nobody"))["code"] == "not_found"


async def test_saving_a_food_names_who_saved_it(ws) -> None:
    oats = await ok(ws, "food/add", **OATS, person="debora")
    assert oats["saved_by"] == "debora"
    assert (await ok(ws, "food/add", **MILK))["saved_by"] is None
    assert (await error(ws, "food/add", **MILK, person="nobody"))["code"] == "not_found"


async def test_warns_about_a_food_saved_already(ws) -> None:
    oats = await ok(ws, "food/add", **OATS, barcode="5000", person="debora")
    taken = await error(ws, "food/add", **{**OATS, "name": "Other oats"}, barcode="5000")
    assert taken["code"] == "barcode_taken"
    assert taken["translation_placeholders"] == {
        "food_id": str(oats["id"]),
        "name": "Porridge oats",
        "saved_by": "debora",
    }
    # Without a barcode, a name a food has is a warning that can be overruled.
    named = await error(ws, "food/add", **{**OATS, "name": "PORRIDGE OATS"})
    assert named["code"] == "name_taken"
    assert named["translation_placeholders"] == taken["translation_placeholders"]
    again = await ok(ws, "food/add", **OATS, anyway=True)
    assert again["id"] != oats["id"]
    # With its own barcode, it's another product that happens to share a name.
    assert (await ok(ws, "food/add", **OATS, barcode="6000"))["barcode"] == "6000"
    milk = await ok(ws, "food/add", **MILK)
    named = await error(ws, "food/add", **MILK)
    assert named["translation_placeholders"]["saved_by"] == ""
    assert named["translation_placeholders"]["food_id"] == str(milk["id"])


async def test_a_barcode_taken_by_a_food_deleted_meanwhile(hass: HomeAssistant, ws) -> None:
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    data = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.data
    with patch.object(data.db, "add_food", side_effect=IntegrityError("x", {}, Exception())):
        taken = await error(ws, "food/add", **OATS, barcode="7000")
    assert taken["code"] == "barcode_taken"
    assert "translation_key" not in taken


async def test_deleting_a_food_announces_its_meals_too(ws) -> None:
    banana = await ok(ws, "food/add", **{**OATS, "name": "Banana"})
    item = [{"food_id": banana["id"], "grams": 118}]
    snack = await ok(ws, "meal/add", name="Banana snack", owner=None, items=item)
    assert (await ok(ws, "food/meals", food_id=banana["id"]))[0]["emptied"]
    await ok(ws, "food/delete", food_id=banana["id"])
    assert await ok(ws, "meals") == []
    gone = await error(ws, "meal/delete", meal_id=snack["id"], version=snack["version"])
    assert gone["code"] == "meal_changed"


# The log_meal action


async def device_of(hass: HomeAssistant, key: str) -> str:
    devices = dr.async_get(hass).devices
    return next(d.id for d in devices if (DOMAIN, key) in d.identifiers)


async def log_meal(hass: HomeAssistant, person: str, **fields: Any) -> None:
    await hass.services.async_call(
        DOMAIN,
        "log_meal",
        {"device_id": await device_of(hass, person), "meal": "lunch", **fields},
        blocking=True,
    )


async def test_logs_everyone_s_meals_and_the_person_s_own(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    item = [{"name": "Coffee", "kcal": 20}, {"name": "Toast", "kcal": 150}]
    await ok(ws, "meal/add", name="Breakfast for all", owner=None, items=item)
    await ok(ws, "meal/add", name="Post-workout shake", owner="matteo", items=item[:1])
    await log_meal(hass, "matteo", saved_meal="breakfast FOR ALL", day="2026-11-08")
    await log_meal(hass, "matteo", saved_meal="Post-workout shake")
    past = await ok(ws, "day", person="matteo", day="2026-11-08")
    assert [(e["name"], e["meal"]) for e in past["entries"]] == [
        ("Coffee", "lunch"),
        ("Toast", "lunch"),
    ]
    today = await ok(ws, "day", person="matteo", day="2026-11-09")
    assert [e["name"] for e in today["entries"]] == ["Coffee"]


async def test_log_meal_names_what_is_wrong(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    item = [{"name": "Coffee", "kcal": 20}]
    await ok(ws, "meal/add", name="Post-workout shake", owner="matteo", items=item)
    with pytest.raises(ServiceValidationError) as err:
        await log_meal(hass, "debora", saved_meal="Pancakes")
    assert err.value.translation_key == "unknown_meal"
    assert err.value.translation_placeholders == {"name": "Pancakes", "person": "Debora"}
    with pytest.raises(ServiceValidationError) as err:
        await log_meal(hass, "debora", saved_meal="post-workout shake")
    assert err.value.translation_key == "others_meal"
    assert err.value.translation_placeholders == {
        "name": "Post-workout shake",
        "person": "Debora",
        "owner": "Matteo",
    }


async def test_log_meal_when_the_meal_goes_meanwhile(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    from unittest.mock import patch

    await ok(ws, "meal/add", name="Toast", owner=None, items=[{"name": "Toast", "kcal": 150}])
    data = entry.runtime_data.data
    with (
        patch.object(data.db, "log_meal", side_effect=MealChangedError),
        pytest.raises(ServiceValidationError) as err,
    ):
        await log_meal(hass, "debora", saved_meal="Toast")
    assert err.value.translation_key == "unknown_meal"


async def test_log_meal_names_an_owner_not_loaded_by_key(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = entry.runtime_data.data
    await hass.async_add_executor_job(
        data.db.add_meal, "someone", "Theirs", [{"name": "x", "kcal": 1}]
    )
    with pytest.raises(ServiceValidationError) as err:
        await log_meal(hass, "debora", saved_meal="Theirs")
    assert err.value.translation_placeholders["owner"] == "someone"


# Removing people, and deleting a person's data


async def test_removing_a_person_gives_their_meals_to_everyone(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    item = [{"name": "Coffee", "kcal": 20}]
    await ok(ws, "meal/add", name="Usual breakfast", owner="matteo", items=item)
    await ok(ws, "meal/add", name="Usual breakfast", owner="debora", items=item)
    await ok(ws, "food/add", **OATS, person="matteo")
    assert hass.config_entries.async_remove_subentry(entry, "sub_matteo")
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    meals = await hass.async_add_executor_job(data.db.meals)
    assert names(meals) == [("Usual breakfast", "debora"), ("Usual breakfast (Matteo)", None)]
    [oats] = await hass.async_add_executor_job(data.db.foods_named, "Porridge oats")
    assert oats["saved_by"] is None
