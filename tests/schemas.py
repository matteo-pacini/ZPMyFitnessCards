"""Databases as older and newer releases leave them, for the migration tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import MetaData, delete, insert, inspect, select

from custom_components.zp_my_fitness.db import MIGRATIONS, VERSION, _schema_v1, make_engine

LATEST = len(MIGRATIONS)

# What a version 1 database holds for SAMPLE_PEOPLE: one food, a day's
# entries, two weigh-ins, and a day's goals.
SAMPLE_PEOPLE = {"matteo": "Matteo", "debora": "Debora"}
SAMPLE_DAY = "2026-11-02"


def database_at(url: str, version: int) -> None:
    """Turn the empty database at `url` into one at schema `version`, as that release left it."""
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            VERSION.create(conn)
            for migrate in MIGRATIONS[:version]:
                migrate(conn)
            if version:
                conn.execute(insert(VERSION).values(version=version))
    finally:
        engine.dispose()


def set_version(url: str, version: int) -> None:
    """Record `version` as the database's schema version, as a newer release would."""
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(delete(VERSION))
            conn.execute(insert(VERSION).values(version=version))
    finally:
        engine.dispose()


def empty_database(url: str) -> None:
    """Drop every table in the database at `url`."""
    engine = make_engine(url)
    try:
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as conn:
            metadata.drop_all(conn)
    finally:
        engine.dispose()


def add_version_1_sample(url: str, day: str = SAMPLE_DAY) -> None:
    """Fill a version 1 database with SAMPLE_PEOPLE's data on `day` and the day before."""
    tables = _schema_v1().tables
    stamp = f"{day}T08:00:00+00:00"
    day_before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            for key, name in SAMPLE_PEOPLE.items():
                conn.execute(insert(tables["people"]).values(key=key, name=name))
            oats = conn.execute(
                insert(tables["foods"]).values(
                    name="Old porridge oats",
                    barcode="5000000000001",
                    kcal=389,
                    protein=16.9,
                    carbs=66,
                    fat=6.9,
                    portions='[{"name": "Bowl", "grams": 40}]',
                    updated_at=stamp,
                )
            ).inserted_primary_key[0]
            for key in SAMPLE_PEOPLE:
                conn.execute(
                    insert(tables["entries"]).values(
                        person=key,
                        day=day,
                        meal="breakfast",
                        food_id=oats,
                        name="Old porridge oats",
                        grams=40,
                        kcal=155.6,
                        protein=6.76,
                        carbs=26.4,
                        fat=2.76,
                        created_at=stamp,
                    )
                )
                conn.execute(
                    insert(tables["entries"]).values(
                        person=key,
                        day=day,
                        meal="dinner",
                        name="Old quick add",
                        kcal=640,
                        created_at=stamp,
                    )
                )
                conn.execute(
                    insert(tables["weights"]),
                    [
                        {"person": key, "day": day_before, "kg": 80.5, "updated_at": stamp},
                        {"person": key, "day": day, "kg": 80.1, "updated_at": stamp},
                    ],
                )
                conn.execute(
                    insert(tables["goals"]).values(
                        person=key, day=day, kcal=2000, protein=125, carbs=225, fat=67
                    )
                )
    finally:
        engine.dispose()


def layout(url: str) -> dict[str, list[str]]:
    """Each table's column names: what a migration changes."""
    engine = make_engine(url)
    try:
        found = inspect(engine)
        return {
            table: sorted(c["name"] for c in found.get_columns(table))
            for table in sorted(found.get_table_names())
        }
    finally:
        engine.dispose()


def contents(url: str, columns: dict[str, list[str]] | None = None) -> dict[str, list[tuple]]:
    """Every row of every table, in a stable order; or only `columns`, by table."""
    engine = make_engine(url)
    try:
        metadata = MetaData()
        metadata.reflect(engine)
        if columns is None:
            columns = {name: list(table.c.keys()) for name, table in metadata.tables.items()}
        with engine.connect() as conn:
            return {
                name: sorted(
                    conn.execute(select(*(metadata.tables[name].c[c] for c in names))).all(),
                    key=repr,
                )
                for name, names in sorted(columns.items())
            }
    finally:
        engine.dispose()


def version(url: str) -> int | None:
    """The schema version recorded in the database."""
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(select(VERSION.c.version)).scalar()
    finally:
        engine.dispose()


@contextmanager
def failing_version_bumps(url: str) -> Iterator[None]:
    """Make every write of a schema version fail inside the database, until the block ends.

    A migration runs before its version bump in the same transaction, so this
    fails each migration after its own changes are made.
    """
    engine = make_engine(url)
    postgres = engine.dialect.name == "postgresql"
    try:
        with engine.begin() as conn:
            if postgres:
                conn.exec_driver_sql(
                    "CREATE FUNCTION fail_version_bump() RETURNS trigger LANGUAGE plpgsql AS"
                    " $$ BEGIN RAISE EXCEPTION 'version bump fails on purpose'; END $$"
                )
                conn.exec_driver_sql(
                    "CREATE TRIGGER fail_version_bump BEFORE INSERT ON schema_version"
                    " FOR EACH ROW EXECUTE FUNCTION fail_version_bump()"
                )
            else:
                conn.exec_driver_sql(
                    "CREATE TRIGGER fail_version_bump BEFORE INSERT ON schema_version"
                    " BEGIN SELECT RAISE(ABORT, 'version bump fails on purpose'); END"
                )
        yield
    finally:
        with engine.begin() as conn:
            if postgres:
                conn.exec_driver_sql("DROP TRIGGER fail_version_bump ON schema_version")
                conn.exec_driver_sql("DROP FUNCTION fail_version_bump()")
            else:
                conn.exec_driver_sql("DROP TRIGGER fail_version_bump")
        engine.dispose()
