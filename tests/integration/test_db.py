"""The SQLite database, without Home Assistant."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, OperationalError

from custom_components.fork_and_scale.db import (
    MIGRATIONS,
    VERSION,
    Database,
    _schema_v1,
    key_for_name,
    make_engine,
    sqlite_url,
)
from custom_components.fork_and_scale.goals import Goals

OATS = {"name": "Porridge oats", "kcal": 389, "protein": 16.9, "carbs": 66, "fat": 6.9}


@pytest.fixture
def db(database_url: str) -> Database:
    """An open database, once on SQLite and once on Postgres."""
    database = Database(database_url)
    database.open()
    yield database
    database.close()


def entry(day: str, meal: str = "breakfast", kcal: float = 100, **more) -> dict:
    return {"day": day, "meal": meal, "name": "Food", "kcal": kcal, **more}


def test_creates_the_latest_schema_and_reopens_without_migrating(database_url: str) -> None:
    first = Database(database_url)
    first.open()
    assert first.schema_version() == len(MIGRATIONS)
    first.add_food(OATS)
    first.close()
    again = Database(database_url)
    again.open()
    assert again.schema_version() == len(MIGRATIONS)
    assert again.search_foods("oats", 10)[0]["name"] == "Porridge oats"
    again.close()


def test_sqlite_keeps_foreign_keys_and_the_write_ahead_log(tmp_path: Path) -> None:
    db = Database(sqlite_url(str(tmp_path / "test.db")))
    db.open()
    with db._db.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    db.close()


def test_sqlite_checkpoint_moves_the_write_ahead_log_into_the_file(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    db = Database(sqlite_url(str(path)))
    db.open()
    # The last connection to close empties the log anyway, so keep one open.
    other = sqlite3.connect(path)
    try:
        other.execute("SELECT 1").fetchone()
        db.add_food(OATS)
        wal = tmp_path / "test.db-wal"
        assert wal.stat().st_size > 0
        db.checkpoint()
        assert wal.stat().st_size == 0
        assert other.execute("SELECT name FROM foods").fetchall() == [("Porridge oats",)]
    finally:
        other.close()
        db.close()


def test_foods_search_by_name_or_barcode(db: Database) -> None:
    db.add_food({**OATS, "barcode": "123", "portions": [{"name": "Bowl", "grams": 40}]})
    db.add_food({"name": "100% rye", "kcal": 250, "protein": 8, "carbs": 48, "fat": 1.7})
    assert [f["name"] for f in db.search_foods("OAT", 10)] == ["Porridge oats"]
    assert [f["name"] for f in db.search_foods("123", 10)] == ["Porridge oats"]
    # % and _ match themselves, not any text.
    assert [f["name"] for f in db.search_foods("0%", 10)] == ["100% rye"]
    assert db.food_by_barcode("123")["portions"] == [{"name": "Bowl", "grams": 40}]


def test_a_barcode_belongs_to_one_food(db: Database) -> None:
    db.add_food({**OATS, "barcode": "123"})
    with pytest.raises(IntegrityError):
        db.add_food({**OATS, "name": "Other", "barcode": "123"})


def test_updates_and_deletes_foods(db: Database) -> None:
    food = db.add_food(OATS)
    assert db.update_food(food["id"], {"kcal": 380})["kcal"] == 380
    assert db.update_food(999, {"kcal": 1}) is None
    assert db.delete_food(food["id"])
    assert not db.delete_food(food["id"])


def test_deleting_a_food_keeps_its_entries(db: Database) -> None:
    food = db.add_food(OATS)
    logged = db.add_entry("p", entry("2026-11-09", food_id=food["id"], kcal=233))
    db.delete_food(food["id"])
    kept = db.entry(logged["id"])
    assert kept["food_id"] is None
    assert kept["kcal"] == 233


def test_recent_foods_are_the_person_s_newest_first(db: Database) -> None:
    oats = db.add_food(OATS)
    rye = db.add_food({**OATS, "name": "Rye"})
    db.add_entry("p", entry("2026-11-08", food_id=oats["id"]))
    db.add_entry("p", entry("2026-11-09", food_id=rye["id"]))
    db.add_entry("other", entry("2026-11-09", food_id=oats["id"]))
    assert [f["name"] for f in db.recent_foods("p", 10)] == ["Rye", "Porridge oats"]


def test_meal_totals_by_day_and_meal(db: Database) -> None:
    db.add_entry("p", entry("2026-11-08", kcal=100, protein=10))
    db.add_entry("p", entry("2026-11-09", kcal=200, protein=None))
    db.add_entry("p", entry("2026-11-09", kcal=50, protein=5))
    db.add_entry("p", entry("2026-11-09", "dinner", kcal=700))
    db.add_entry("other", entry("2026-11-09", kcal=999))
    totals = db.meal_totals("p", "2026-11-09", "2026-11-09")
    assert totals["2026-11-09"]["breakfast"]["kcal"] == 250
    # Missing values count as 0.
    assert totals["2026-11-09"]["breakfast"]["protein"] == 5
    assert totals["2026-11-09"]["dinner"]["kcal"] == 700
    assert "2026-11-08" not in totals


def test_one_weight_a_day_the_last_wins(db: Database) -> None:
    db.set_weight("p", "2026-11-08", 70.4)
    db.set_weight("p", "2026-11-09", 70.2)
    db.set_weight("p", "2026-11-09", 69.9)
    assert db.weights("p", "2026-11-01", "2026-11-30") == [
        {"day": "2026-11-08", "kg": 70.4},
        {"day": "2026-11-09", "kg": 69.9},
    ]
    assert db.latest_weight("p", "2026-11-08") == {"day": "2026-11-08", "kg": 70.4}
    db.delete_weight("p", "2026-11-09")
    assert db.latest_weight("p", "2026-11-09")["kg"] == 70.4


def test_goals_hold_until_the_next_change(db: Database) -> None:
    first, second = Goals(1800, 90, 225, 60), Goals(1700, 85, 212.5, 56.7)
    db.set_goal("p", "2026-11-01", first)
    db.set_goal("p", "2026-11-05", second)
    assert db.goal_on("p", "2026-10-31") is None
    assert db.goal_on("p", "2026-11-04") == first
    assert db.goal_on("p", "2026-11-09") == second
    assert db.goal_changes("p", "2026-11-04") == [("2026-11-01", first)]


def test_remembers_removed_people_by_name(db: Database) -> None:
    db.sync_people([("k1", "Debora"), ("k2", "Matteo")])
    assert key_for_name(db.url, "debora", exclude=[]) == "k1"
    assert key_for_name(db.url, "Debora", exclude=["k1"]) is None
    db.sync_people([("k1", "Deb")])
    assert key_for_name(db.url, "Debora", exclude=[]) is None


def test_finds_people_while_another_connection_writes(db: Database) -> None:
    db.sync_people([("k1", "Debora")])
    with db._db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO people (key, name) VALUES ('k2', 'Nora')")
        # Neither blocked nor shown what is not committed yet.
        assert key_for_name(db.url, "Debora", exclude=[]) == "k1"
        assert key_for_name(db.url, "Nora", exclude=[]) is None
    assert key_for_name(db.url, "Nora", exclude=[]) == "k2"


def test_finds_nobody_in_a_database_with_no_tables(database_url: str) -> None:
    assert key_for_name(database_url, "Debora", exclude=[]) is None


def test_a_database_it_cannot_open_raises(tmp_path: Path) -> None:
    with pytest.raises(OperationalError):
        key_for_name(sqlite_url(str(tmp_path / "missing" / "test.db")), "Debora", exclude=[])


def test_deletes_everything_for_one_person(db: Database) -> None:
    db.sync_people([("p", "P"), ("q", "Q")])
    for who in ("p", "q"):
        db.add_entry(who, entry("2026-11-09"))
        db.set_weight(who, "2026-11-09", 70)
        db.set_goal(who, "2026-11-09", Goals(1, 1, 1, 1))
    db.delete_person("p")
    assert db.day_entries("p", "2026-11-09") == []
    assert db.latest_weight("p", "2026-11-09") is None
    assert db.goal_on("p", "2026-11-09") is None
    assert key_for_name(db.url, "P", exclude=[]) is None
    assert len(db.day_entries("q", "2026-11-09")) == 1


def test_a_new_database_starts_at_the_latest_version_and_closes_twice(database_url: str) -> None:
    db = Database(database_url)
    db.open()
    assert db.schema_version() == len(MIGRATIONS)
    db.close()
    db.close()


def test_updates_with_nothing_to_change_return_the_row(db: Database) -> None:
    food = db.add_food({**OATS, "portions": [{"name": "Bowl", "grams": 40}]})
    assert db.update_food(food["id"], {"unknown": 1}) == food
    assert db.update_food(food["id"], {"portions": None})["portions"] == []
    logged = db.add_entry("p", entry("2026-11-09"))
    assert db.update_entry(logged["id"], {}) == logged
    assert db.update_entry(999, {"kcal": 1}) is None


def test_upgrades_a_version_1_database_keeping_its_entries(database_url: str) -> None:
    engine = make_engine(database_url)
    with engine.begin() as conn:
        MIGRATIONS[0](conn)
        VERSION.create(conn)
        conn.execute(insert(VERSION).values(version=1))
        conn.execute(
            insert(_schema_v1().tables["entries"]).values(
                person="p",
                day="2026-11-09",
                meal="lunch",
                name="Soup",
                kcal=100,
                created_at="2026-11-09T12:00:00+00:00",
            )
        )
    engine.dispose()
    db = Database(database_url)
    db.open()
    assert db.schema_version() == len(MIGRATIONS) == 2
    [soup] = db.day_entries("p", "2026-11-09")
    assert (soup["name"], soup["source"]) == ("Soup", None)
    db.close()


def test_replaces_one_source_s_entries_on_the_days_given(db: Database) -> None:
    mine = db.add_entry("p", entry("2026-11-01", name="Mine"))
    db.replace_entries(
        "p", "mfp", "2026-11-01", "2026-11-02", [entry("2026-11-01", kcal=1), entry("2026-11-02")]
    )
    db.replace_entries("q", "mfp", "2026-11-01", "2026-11-01", [entry("2026-11-01", kcal=9)])
    # Again, over days that overlap: the 2nd's entry goes, the 1st's stays.
    db.replace_entries("p", "mfp", "2026-11-02", "2026-11-03", [entry("2026-11-03", kcal=3)])

    def day(d: str) -> list:
        return [(e["name"], e["kcal"], e["source"]) for e in db.day_entries("p", d)]

    assert day("2026-11-01") == [("Mine", 100, None), ("Food", 1, "mfp")]
    assert day("2026-11-02") == []
    assert day("2026-11-03") == [("Food", 3, "mfp")]
    assert db.entry(mine["id"])["source"] is None
    assert len(db.day_entries("q", "2026-11-01")) == 1


def test_exports_a_person_s_entries_and_weights_and_every_food(db: Database) -> None:
    oats = db.add_food({**OATS, "portions": [{"name": "Bowl", "grams": 40}]})
    db.add_entry("p", entry("2026-11-09", name="Late"))
    db.add_entry("p", entry("2026-11-08", food_id=oats["id"], grams=40))
    db.add_entry("q", entry("2026-11-08", name="Not theirs"))
    db.set_weight("p", "2026-11-09", 70.2)
    db.set_weight("p", "2026-11-01", 71)
    db.set_weight("q", "2026-11-01", 90)
    data = db.export("p")
    assert [(e["day"], e["name"]) for e in data["entries"]] == [
        ("2026-11-08", "Food"),
        ("2026-11-09", "Late"),
    ]
    assert [(w["day"], w["kg"]) for w in data["weights"]] == [
        ("2026-11-01", 71),
        ("2026-11-09", 70.2),
    ]
    assert data["foods"] == [db.food(oats["id"])]
