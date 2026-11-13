"""Upgrading the database from one schema version to the next, and failing to."""

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from sqlalchemy import insert, inspect, update
from sqlalchemy.exc import DBAPIError

from custom_components.metron import db as db_module
from custom_components.metron.const import DB_FILE
from custom_components.metron.db import (
    MIGRATIONS,
    Database,
    NewerSchemaError,
    _schema_v1,
    _schema_v2,
    _schema_v4,
    make_engine,
    sqlite_url,
)

from ..schemas import (
    LATEST,
    SAMPLE_DAY,
    SAMPLE_PEOPLE,
    add_version_1_sample,
    contents,
    database_at,
    failing_version_bumps,
    layout,
    set_version,
    version,
)
from .conftest import mock_entry, person

VERSION_1_COLUMNS = {name: list(table.c.keys()) for name, table in _schema_v1().tables.items()}


class Crash(Exception):
    """A failure in the middle of a migration."""


def version_1_database(url: str) -> dict[str, list[tuple]]:
    """Make the database at `url` one that version 1 left with the sample; return its rows."""
    database_at(url, 1)
    add_version_1_sample(url)
    return contents(url)


# The database alone


def test_a_transaction_undoes_its_schema_changes_with_its_writes(database_url: str) -> None:
    engine = make_engine(database_url)
    try:
        with pytest.raises(Crash), engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE scratch (n INTEGER)")
            conn.exec_driver_sql("INSERT INTO scratch VALUES (1)")
            conn.exec_driver_sql("ALTER TABLE scratch ADD COLUMN m INTEGER")
            raise Crash
        assert "scratch" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_upgrades_a_version_1_database_keeping_everything_in_it(database_url: str) -> None:
    before = version_1_database(database_url)
    db = Database(database_url)
    db.open()
    assert db.schema_version() == LATEST
    db.close()
    assert contents(database_url, VERSION_1_COLUMNS) == {
        t: rows for t, rows in before.items() if t in VERSION_1_COLUMNS
    }
    assert {row.source for row in contents(database_url, {"entries": ["source"]})["entries"]} == {
        None
    }


def test_upgrades_a_version_2_database_keeping_everything_in_it(database_url: str) -> None:
    # Version 2 is what installs that have imported from MyFitnessPal are at.
    database_at(database_url, 2)
    add_version_1_sample(database_url)
    engine = make_engine(database_url)
    entries = _schema_v2().tables["entries"]
    with engine.begin() as conn:
        conn.execute(
            update(entries).where(entries.c.name == "Old quick add").values(source="myfitnesspal")
        )
    engine.dispose()
    version_2_columns = {name: list(t.c.keys()) for name, t in _schema_v2().tables.items()}
    before = contents(database_url, version_2_columns)

    db = Database(database_url)
    db.open()
    try:
        assert db.schema_version() == LATEST
        assert contents(database_url, version_2_columns) == before
        # Foods saved then were saved by nobody known, and are found in any case.
        assert [f["saved_by"] for f in db.search_foods("OLD PORRIDGE", 10)] == [None]
        assert db.meals() == []
        # Importing again still replaces the entries MyFitnessPal brought, and only those.
        db.replace_entries("matteo", "myfitnesspal", SAMPLE_DAY, SAMPLE_DAY, [])
        assert [e["name"] for e in db.day_entries("matteo", SAMPLE_DAY)] == ["Old porridge oats"]
    finally:
        db.close()


def test_foods_saved_before_an_upgrade_are_found_in_any_case(database_url: str) -> None:
    database_at(database_url, 3)
    engine = make_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            insert(_schema_v1().tables["foods"]).values(
                name="Ölsardinen",
                kcal=210,
                protein=24,
                carbs=0,
                fat=13,
                portions="[]",
                updated_at="2026-11-01T08:00:00+00:00",
            )
        )
    engine.dispose()
    db = Database(database_url)
    db.open()
    try:
        assert [f["name"] for f in db.search_foods("öl", 10)] == ["Ölsardinen"]
        assert [f["name"] for f in db.foods_named("ÖLSARDINEN")] == ["Ölsardinen"]
    finally:
        db.close()


def test_upgrades_a_version_4_database_with_somewhere_to_keep_activity(
    database_url: str,
) -> None:
    database_at(database_url, 4)
    add_version_1_sample(database_url)
    version_4_columns = {name: list(t.c.keys()) for name, t in _schema_v4().tables.items()}
    before = contents(database_url, version_4_columns)
    assert "activity" not in layout(database_url)

    db = Database(database_url)
    db.open()
    try:
        assert db.schema_version() == LATEST == 5
        assert contents(database_url, version_4_columns) == before
        # Goals set before stored no allowance.
        assert "allowed" in layout(database_url)["goals"]
        assert {row.allowed for row in contents(database_url, {"goals": ["allowed"]})["goals"]} == {
            None
        }
        assert layout(database_url)["activity"] == sorted(
            [
                "person",
                "day",
                "source",
                "measured",
                "counted",
                "added",
                "allowed",
                "share",
                "cap",
                "last_reading",
            ]
        )
        assert db.activity("matteo", SAMPLE_DAY) is None
        row = {
            "source": "sensor.garmin_connect_active_calories",
            "measured": 906,
            "counted": 680,
            "added": 435.8,
            "allowed": 244.2,
            "share": 75,
            "cap": 1500,
            "last_reading": 906,
        }
        db.set_day("matteo", SAMPLE_DAY, row)
        assert db.activity("matteo", SAMPLE_DAY) == row
        # Deleting a person deletes theirs.
        db.delete_person("matteo")
        assert db.activity("matteo", SAMPLE_DAY) is None
    finally:
        db.close()


@pytest.mark.parametrize("number", range(1, LATEST + 1))
def test_a_migration_that_fails_midway_changes_nothing_and_the_next_open_finishes(
    database_url: str, number: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_at(database_url, number - 1)
    if number > 1:
        add_version_1_sample(database_url)
    before = layout(database_url), contents(database_url)
    real = MIGRATIONS[number - 1]

    def crashing(conn: Any) -> None:
        real(conn)
        raise Crash

    monkeypatch.setattr(
        db_module, "MIGRATIONS", [*MIGRATIONS[: number - 1], crashing, *MIGRATIONS[number:]]
    )
    db = Database(database_url)
    with pytest.raises(Crash):
        db.open()
    # Closed, so a Postgres server keeps no connection from a failed open.
    assert db._engine is None
    assert (layout(database_url), contents(database_url)) == before
    assert version(database_url) == (number - 1 or None)

    monkeypatch.undo()
    db.open()
    assert db.schema_version() == LATEST
    db.close()


def test_a_version_bump_the_database_refuses_undoes_its_migration(database_url: str) -> None:
    version_1_database(database_url)
    before = layout(database_url), contents(database_url)
    db = Database(database_url)
    with failing_version_bumps(database_url):
        with pytest.raises(DBAPIError, match="version bump fails on purpose"):
            db.open()
        assert db._engine is None
        assert (layout(database_url), contents(database_url)) == before
        assert "source" not in layout(database_url)["entries"]
    db.open()
    assert db.schema_version() == LATEST
    assert [e["name"] for e in db.day_entries("matteo", SAMPLE_DAY)] == [
        "Old porridge oats",
        "Old quick add",
    ]
    db.close()


def test_refuses_a_database_a_newer_release_upgraded_and_changes_nothing(
    database_url: str,
) -> None:
    database_at(database_url, LATEST)
    add_version_1_sample(database_url)
    set_version(database_url, LATEST + 1)
    before = layout(database_url), contents(database_url)
    db = Database(database_url)
    with pytest.raises(NewerSchemaError) as raised:
        db.open()
    assert raised.value.version == LATEST + 1
    assert str(raised.value) == f"schema version {LATEST + 1}; this release knows up to {LATEST}"
    assert db._engine is None
    assert (layout(database_url), contents(database_url)) == before


def test_opens_a_database_at_the_latest_version_without_touching_it(database_url: str) -> None:
    database_at(database_url, LATEST)
    add_version_1_sample(database_url)
    before = layout(database_url), contents(database_url)
    db = Database(database_url)
    db.open()
    db.close()
    assert (layout(database_url), contents(database_url)) == before


# Setting up the integration


def entry_url(hass: HomeAssistant, entry_data: dict[str, Any]) -> str:
    """The database the entry with `entry_data` opens."""
    return entry_data.get("db_url") or sqlite_url(hass.config.path(DB_FILE))


def sample_entry(entry_data: dict[str, Any]):
    """The integration's entry with the sample's people, as they were added."""
    return mock_entry(
        *(person(name, key=key) for key, name in SAMPLE_PEOPLE.items()), data=entry_data
    )


async def test_setup_upgrades_a_version_1_database(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    url = entry_url(hass, entry_data)
    version_1_database(url)
    entry = sample_entry(entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert version(url) == LATEST
    db = entry.runtime_data.data.db
    for key in SAMPLE_PEOPLE:
        assert [(e["name"], e["kcal"], e["source"]) for e in db.day_entries(key, SAMPLE_DAY)] == [
            ("Old porridge oats", 155.6, None),
            ("Old quick add", 640, None),
        ]
    assert float(hass.states.get("sensor.matteo_weight").state) == 80.1


async def test_setup_fails_when_an_upgrade_fails_and_a_reload_finishes_it(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    url = entry_url(hass, entry_data)
    version_1_database(url)
    before = layout(url), contents(url)
    entry = sample_entry(entry_data)
    entry.add_to_hass(hass)
    with failing_version_bumps(url):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert (layout(url), contents(url)) == before
        assert hass.states.get("sensor.matteo_weight") is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert version(url) == LATEST
    assert float(hass.states.get("sensor.matteo_weight").state) == 80.1


async def test_setup_refuses_a_database_a_newer_release_upgraded(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> None:
    url = entry_url(hass, entry_data)
    database_at(url, LATEST)
    add_version_1_sample(url)
    set_version(url, LATEST + 1)
    before = layout(url), contents(url)
    entry = sample_entry(entry_data)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "newer_database"
    assert entry.error_reason_translation_placeholders == {
        "version": str(LATEST + 1),
        "latest": str(LATEST),
    }
    # Home Assistant drops the message's last full stop.
    assert entry.reason == (
        f"A newer release of Metron upgraded this database to version {LATEST + 1}."
        f" This release knows up to version {LATEST}, so it left the database as it is."
        " Update Metron to use it again"
    )
    assert (layout(url), contents(url)) == before
    assert hass.states.get("sensor.matteo_weight") is None

    # Back at a version it knows, as after updating, it loads.
    set_version(url, LATEST)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
