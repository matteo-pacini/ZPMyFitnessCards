"""The database: foods, entries, weights and daily goals, in SQLite or Postgres.

Queries use SQLAlchemy Core, which Home Assistant already ships for its
recorder, so the same code runs on both. Every method blocks, so Home
Assistant code calls them in the executor.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Connection,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    inspect,
    or_,
    select,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import DDL, CreateColumn

from .const import NUTRIENTS
from .goals import Goals


def _schema_v1() -> MetaData:
    """The tables as schema version 1 created them. Never edit this.

    A later version gets its own function, changed from a copy of this one,
    and a migration that turns version 1 into it.
    """
    metadata = MetaData()
    nutrients = [Column(n, Float) for n in NUTRIENTS]
    Table(
        "people",
        metadata,
        Column("key", String(64), primary_key=True),
        Column("name", Text, nullable=False),
    )
    Table(
        "foods",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", Text, nullable=False),
        Column("barcode", String(64), unique=True),
        *[
            Column(n, Float, nullable=n in ("fibre", "sugar", "saturated_fat", "salt"))
            for n in NUTRIENTS
        ],
        Column("portions", Text, nullable=False, default="[]"),
        Column("updated_at", String(32), nullable=False),
    )
    entries = Table(
        "entries",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("person", String(64), nullable=False),
        Column("day", String(10), nullable=False),
        Column("meal", String(16), nullable=False),
        Column("food_id", Integer, ForeignKey("foods.id", ondelete="SET NULL")),
        Column("name", Text, nullable=False),
        Column("grams", Float),
        *nutrients,
        Column("created_at", String(32), nullable=False),
        CheckConstraint("meal IN ('breakfast', 'lunch', 'dinner', 'snacks')"),
    )
    Index("entries_by_day", entries.c.person, entries.c.day)
    Table(
        "weights",
        metadata,
        Column("person", String(64), primary_key=True),
        Column("day", String(10), primary_key=True),
        Column("kg", Float, nullable=False),
        Column("updated_at", String(32), nullable=False),
    )
    Table(
        "goals",
        metadata,
        Column("person", String(64), primary_key=True),
        Column("day", String(10), primary_key=True),
        *[Column(n, Float, nullable=False) for n in ("kcal", "protein", "carbs", "fat")],
    )
    return metadata


def _schema_v2() -> MetaData:
    """Version 1, with each entry's source: NULL when logged in Home Assistant."""
    metadata = MetaData()
    nutrients = [Column(n, Float) for n in NUTRIENTS]
    Table(
        "people",
        metadata,
        Column("key", String(64), primary_key=True),
        Column("name", Text, nullable=False),
    )
    Table(
        "foods",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", Text, nullable=False),
        Column("barcode", String(64), unique=True),
        *[
            Column(n, Float, nullable=n in ("fibre", "sugar", "saturated_fat", "salt"))
            for n in NUTRIENTS
        ],
        Column("portions", Text, nullable=False, default="[]"),
        Column("updated_at", String(32), nullable=False),
    )
    entries = Table(
        "entries",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("person", String(64), nullable=False),
        Column("day", String(10), nullable=False),
        Column("meal", String(16), nullable=False),
        Column("food_id", Integer, ForeignKey("foods.id", ondelete="SET NULL")),
        Column("name", Text, nullable=False),
        Column("grams", Float),
        *nutrients,
        Column("created_at", String(32), nullable=False),
        Column("source", String(16)),
        CheckConstraint("meal IN ('breakfast', 'lunch', 'dinner', 'snacks')"),
    )
    Index("entries_by_day", entries.c.person, entries.c.day)
    Table(
        "weights",
        metadata,
        Column("person", String(64), primary_key=True),
        Column("day", String(10), primary_key=True),
        Column("kg", Float, nullable=False),
        Column("updated_at", String(32), nullable=False),
    )
    Table(
        "goals",
        metadata,
        Column("person", String(64), primary_key=True),
        Column("day", String(10), primary_key=True),
        *[Column(n, Float, nullable=False) for n in ("kcal", "protein", "carbs", "fat")],
    )
    return metadata


def _migrate_to_v1(conn: Connection) -> None:
    _schema_v1().create_all(conn)


def _migrate_to_v2(conn: Connection) -> None:
    source = _schema_v2().tables["entries"].c.source
    conn.execute(
        DDL(f"ALTER TABLE entries ADD COLUMN {CreateColumn(source).compile(dialect=conn.dialect)}")
    )


# Each entry upgrades the schema by one version; schema_version holds the
# version a database is at. Never edit a released entry, append a new one.
MIGRATIONS: list[Callable[[Connection], None]] = [_migrate_to_v1, _migrate_to_v2]

# The tables the queries below use: those of the latest version.
SCHEMA = _schema_v2()
PEOPLE, FOODS, ENTRIES, WEIGHTS, GOALS = (
    SCHEMA.tables[name] for name in ("people", "foods", "entries", "weights", "goals")
)

VERSION = Table("schema_version", MetaData(), Column("version", Integer, nullable=False))

FOOD_FIELDS = ("name", "barcode", *NUTRIENTS, "portions")
ENTRY_FIELDS = ("day", "meal", "food_id", "name", "grams", *NUTRIENTS)


def sqlite_url(path: str) -> str:
    """The database URL of an SQLite file."""
    return f"sqlite:///{path}"


def make_engine(url: str) -> Engine:
    """An engine for `url`, set up for this integration's use of it."""
    if url.startswith("sqlite"):
        # A connection per use: opening a local file is cheap, and nothing is
        # left open for a reload or shutdown to miss.
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=NullPool)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()
            # Python's sqlite3 begins a transaction only before INSERT, UPDATE
            # and DELETE, so a migration's ALTER TABLE would commit on its own
            # even if the rest of the migration failed. Stop it beginning any,
            # and begin every transaction below instead:
            # https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#sqlite-enabling-transactions
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn: Connection) -> None:
            conn.exec_driver_sql("BEGIN")

        return engine
    return create_engine(url, pool_pre_ping=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _food(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    food = dict(row._mapping)
    food["portions"] = json.loads(food["portions"])
    return food


def key_for_name(url: str, name: str, exclude: Iterable[str]) -> str | None:
    """The key of a person once called `name` in the database at `url`, unless in `exclude`.

    Names match ignoring case. It reads on a connection of its own, so it
    works whether or not the integration has the database open, and finds
    nobody in a database with no tables yet.
    """
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            if not inspect(conn).has_table(PEOPLE.name):
                return None
            excluded = set(exclude)
            for row in conn.execute(select(PEOPLE.c.key, PEOPLE.c.name)):
                if row.name.casefold() == name.casefold() and row.key not in excluded:
                    return row.key
            return None
    finally:
        engine.dispose()


class NewerSchemaError(Exception):
    """The database is at a schema version that only a newer release knows."""

    def __init__(self, version: int) -> None:
        super().__init__(f"schema version {version}; this release knows up to {len(MIGRATIONS)}")
        self.version = version


class Database:
    """The integration's data, in one SQLite file or one Postgres database."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._engine: Engine | None = None

    # Connection

    @property
    def is_sqlite(self) -> bool:
        """Whether the data is in an SQLite file, which Home Assistant backs up."""
        return self.url.startswith("sqlite")

    @property
    def _db(self) -> Engine:
        assert self._engine is not None, "database is not open"
        return self._engine

    def open(self) -> None:
        """Connect, creating the tables if needed, and upgrade the schema.

        Raises NewerSchemaError, and changes nothing, if a newer release of the
        integration has upgraded the database past what this one knows. On any
        failure the database is left at the last version that completed, and
        closed.
        """
        self._engine = make_engine(self.url)
        try:
            with self._db.begin() as conn:
                VERSION.create(conn, checkfirst=True)
            version = self.schema_version()
            if version > len(MIGRATIONS):
                raise NewerSchemaError(version)
            for number, migrate in enumerate(MIGRATIONS[version:], start=version + 1):
                # The migration and its version bump commit together, or not at all.
                with self._db.begin() as conn:
                    migrate(conn)
                    conn.execute(delete(VERSION))
                    conn.execute(insert(VERSION).values(version=number))
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Close every connection."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def checkpoint(self) -> None:
        """Make an SQLite file complete on its own by moving its write-ahead log into it."""
        if self.is_sqlite:
            with self._db.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    def schema_version(self) -> int:
        """The schema version the database is at; open() creates its table first."""
        with self._db.connect() as conn:
            return conn.execute(select(VERSION.c.version)).scalar() or 0

    def _insert(self, table: Table) -> Any:
        """An INSERT for this database's dialect, which supports ON CONFLICT."""
        dialect = postgresql if self._db.dialect.name == "postgresql" else sqlite
        return dialect.insert(table)

    def _all(self, query: Any) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(query)]

    def _one(self, query: Any) -> dict[str, Any] | None:
        rows = self._all(query)
        return rows[0] if rows else None

    # People

    def sync_people(self, people: Iterable[tuple[str, str]]) -> None:
        """Record each (key, name), so a removed person's name is remembered."""
        with self._db.begin() as conn:
            for key, name in people:
                upsert = self._insert(PEOPLE).values(key=key, name=name)
                conn.execute(
                    upsert.on_conflict_do_update(index_elements=["key"], set_={"name": name})
                )

    def delete_person(self, person: str) -> None:
        """Delete everything stored for a person."""
        with self._db.begin() as conn:
            for table in (ENTRIES, WEIGHTS, GOALS):
                conn.execute(delete(table).where(table.c.person == person))
            conn.execute(delete(PEOPLE).where(PEOPLE.c.key == person))

    # Foods

    def add_food(self, food: dict[str, Any]) -> dict[str, Any]:
        """Save a new food and return it.

        Raises sqlalchemy.exc.IntegrityError if another food has its barcode.
        """
        values = {k: food.get(k) for k in FOOD_FIELDS}
        values["portions"] = json.dumps(food.get("portions") or [])
        with self._db.begin() as conn:
            food_id = conn.execute(
                insert(FOODS).values(**values, updated_at=_now()).returning(FOODS.c.id)
            ).scalar_one()
        return self.food(food_id)

    def update_food(self, food_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Change some of a food's fields and return it, or None if there is no such food."""
        values = {k: changes[k] for k in FOOD_FIELDS if k in changes}
        if "portions" in values:
            values["portions"] = json.dumps(values["portions"] or [])
        if values:
            with self._db.begin() as conn:
                conn.execute(
                    update(FOODS).where(FOODS.c.id == food_id).values(**values, updated_at=_now())
                )
        return self.food(food_id)

    def delete_food(self, food_id: int) -> bool:
        """Delete a food. Entries logged from it keep their copied numbers."""
        with self._db.begin() as conn:
            return conn.execute(delete(FOODS).where(FOODS.c.id == food_id)).rowcount > 0

    def food(self, food_id: int) -> dict[str, Any] | None:
        """One food, or None."""
        with self._db.connect() as conn:
            return _food(conn.execute(select(FOODS).where(FOODS.c.id == food_id)).first())

    def food_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        """The food with this barcode, or None."""
        with self._db.connect() as conn:
            return _food(conn.execute(select(FOODS).where(FOODS.c.barcode == barcode)).first())

    def foods_named(self, name: str) -> list[dict[str, Any]]:
        """Foods called `name`, ignoring case, oldest first.

        On SQLite, only the case of ASCII letters is ignored.
        """
        # The database's lower() on both sides, not Python's on `name`, so that
        # both go through the same rules.
        query = select(FOODS).where(func.lower(FOODS.c.name) == func.lower(name))
        with self._db.connect() as conn:
            return [_food(r) for r in conn.execute(query.order_by(FOODS.c.id))]

    def search_foods(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Foods whose name contains `query`, ignoring case, or whose barcode is `query`."""
        escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        found = (
            select(FOODS)
            .where(
                or_(
                    func.lower(FOODS.c.name).like(f"%{escaped}%", escape="\\"),
                    FOODS.c.barcode == query,
                )
            )
            .order_by(func.lower(FOODS.c.name))
            .limit(limit)
        )
        with self._db.connect() as conn:
            return [_food(r) for r in conn.execute(found)]

    def recent_foods(self, person: str, limit: int) -> list[dict[str, Any]]:
        """The foods a person logged most recently, newest first."""
        recent = (
            select(ENTRIES.c.food_id, func.max(ENTRIES.c.id).label("last"))
            .where(ENTRIES.c.person == person, ENTRIES.c.food_id.is_not(None))
            .group_by(ENTRIES.c.food_id)
            .subquery()
        )
        query = (
            select(FOODS)
            .join(recent, recent.c.food_id == FOODS.c.id)
            .order_by(recent.c.last.desc())
            .limit(limit)
        )
        with self._db.connect() as conn:
            return [_food(r) for r in conn.execute(query)]

    # Entries

    def add_entry(self, person: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Log an entry and return it."""
        values = {k: entry.get(k) for k in ENTRY_FIELDS}
        with self._db.begin() as conn:
            entry_id = conn.execute(
                insert(ENTRIES)
                .values(person=person, **values, created_at=_now())
                .returning(ENTRIES.c.id)
            ).scalar_one()
        return self.entry(entry_id)

    def update_entry(self, entry_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Change some of an entry's fields and return it, or None if there is no such entry."""
        values = {k: changes[k] for k in ENTRY_FIELDS if k in changes}
        if values:
            with self._db.begin() as conn:
                conn.execute(update(ENTRIES).where(ENTRIES.c.id == entry_id).values(**values))
        return self.entry(entry_id)

    def delete_entry(self, entry_id: int) -> None:
        """Delete an entry."""
        with self._db.begin() as conn:
            conn.execute(delete(ENTRIES).where(ENTRIES.c.id == entry_id))

    def replace_entries(
        self, person: str, source: str, start: str, end: str, entries: Iterable[dict[str, Any]]
    ) -> None:
        """Replace a person's entries from `source` on days from `start` to `end`.

        Entries from elsewhere, such as those logged in Home Assistant, stay.
        """
        with self._db.begin() as conn:
            conn.execute(
                delete(ENTRIES).where(
                    ENTRIES.c.person == person,
                    ENTRIES.c.source == source,
                    ENTRIES.c.day.between(start, end),
                )
            )
            for entry in entries:
                values = {k: entry.get(k) for k in ENTRY_FIELDS}
                conn.execute(
                    insert(ENTRIES).values(
                        person=person, **values, source=source, created_at=_now()
                    )
                )

    def days_with_entry_named(self, person: str, name: str) -> set[str]:
        """The days on which a person has an entry called `name`."""
        rows = self._all(
            select(ENTRIES.c.day)
            .where(ENTRIES.c.person == person, ENTRIES.c.name == name)
            .distinct()
        )
        return {row["day"] for row in rows}

    def entry(self, entry_id: int) -> dict[str, Any] | None:
        """One entry, or None."""
        return self._one(select(ENTRIES).where(ENTRIES.c.id == entry_id))

    def day_entries(self, person: str, day: str) -> list[dict[str, Any]]:
        """A person's entries on `day`, in the order they were logged."""
        return self._all(
            select(ENTRIES)
            .where(ENTRIES.c.person == person, ENTRIES.c.day == day)
            .order_by(ENTRIES.c.id)
        )

    def meal_totals(self, person: str, start: str, end: str) -> dict[str, dict[str, dict]]:
        """Sums of each nutrient by day and meal, for days from `start` to `end`.

        Returns {day: {meal: {nutrient: sum}}}, with only days and meals that
        have entries. Missing values count as 0.
        """
        sums = [func.coalesce(func.sum(ENTRIES.c[n]), 0.0).label(n) for n in NUTRIENTS]
        rows = self._all(
            select(ENTRIES.c.day, ENTRIES.c.meal, *sums)
            .where(ENTRIES.c.person == person, ENTRIES.c.day.between(start, end))
            .group_by(ENTRIES.c.day, ENTRIES.c.meal)
        )
        result: dict[str, dict[str, dict]] = {}
        for row in rows:
            result.setdefault(row["day"], {})[row["meal"]] = {n: float(row[n]) for n in NUTRIENTS}
        return result

    # Weights

    def set_weight(self, person: str, day: str, kg: float) -> None:
        """Record a person's weight for `day`, replacing any earlier one that day."""
        upsert = self._insert(WEIGHTS).values(person=person, day=day, kg=kg, updated_at=_now())
        with self._db.begin() as conn:
            conn.execute(
                upsert.on_conflict_do_update(
                    index_elements=["person", "day"],
                    set_={"kg": upsert.excluded.kg, "updated_at": upsert.excluded.updated_at},
                )
            )

    def add_weights(self, person: str, weights: Iterable[tuple[str, float]]) -> int:
        """Record (day, kg) pairs for days that have no weight yet; return how many."""
        added = 0
        with self._db.begin() as conn:
            for day, kg in weights:
                insert_new = self._insert(WEIGHTS).values(
                    person=person, day=day, kg=kg, updated_at=_now()
                )
                result = conn.execute(
                    insert_new.on_conflict_do_nothing(index_elements=["person", "day"])
                )
                added += result.rowcount
        return added

    def delete_weight(self, person: str, day: str) -> None:
        """Delete a person's weight for `day`."""
        with self._db.begin() as conn:
            conn.execute(delete(WEIGHTS).where(WEIGHTS.c.person == person, WEIGHTS.c.day == day))

    def weights(self, person: str, start: str, end: str) -> list[dict[str, Any]]:
        """A person's weights from `start` to `end`, oldest first, as {day, kg}."""
        return self._all(
            select(WEIGHTS.c.day, WEIGHTS.c.kg)
            .where(WEIGHTS.c.person == person, WEIGHTS.c.day.between(start, end))
            .order_by(WEIGHTS.c.day)
        )

    def latest_weight(self, person: str, day: str) -> dict[str, Any] | None:
        """A person's last weight on or before `day`, as {day, kg}, or None."""
        return self._one(
            select(WEIGHTS.c.day, WEIGHTS.c.kg)
            .where(WEIGHTS.c.person == person, WEIGHTS.c.day <= day)
            .order_by(WEIGHTS.c.day.desc())
            .limit(1)
        )

    # Export

    def export(self, person: str) -> dict[str, list[dict[str, Any]]]:
        """A person's entries and weights, oldest first, and every saved food.

        Foods are everyone's, so they are all there. Read in one transaction,
        so the three agree.
        """
        with self._db.begin() as conn:
            entries = conn.execute(
                select(ENTRIES)
                .where(ENTRIES.c.person == person)
                .order_by(ENTRIES.c.day, ENTRIES.c.id)
            )
            weights = conn.execute(
                select(WEIGHTS).where(WEIGHTS.c.person == person).order_by(WEIGHTS.c.day)
            )
            return {
                "entries": [dict(r._mapping) for r in entries],
                "weights": [dict(r._mapping) for r in weights],
                "foods": [_food(r) for r in conn.execute(select(FOODS).order_by(FOODS.c.id))],
            }

    # Goals

    def goal_on(self, person: str, day: str) -> Goals | None:
        """The goals in force on `day`: the last ones set on or before it."""
        row = self._one(
            select(GOALS.c.kcal, GOALS.c.protein, GOALS.c.carbs, GOALS.c.fat)
            .where(GOALS.c.person == person, GOALS.c.day <= day)
            .order_by(GOALS.c.day.desc())
            .limit(1)
        )
        return Goals(**row) if row else None

    def goal_changes(self, person: str, end: str) -> list[tuple[str, Goals]]:
        """Each day up to `end` on which a person's goals were set, oldest first."""
        rows = self._all(
            select(GOALS.c.day, GOALS.c.kcal, GOALS.c.protein, GOALS.c.carbs, GOALS.c.fat)
            .where(GOALS.c.person == person, GOALS.c.day <= end)
            .order_by(GOALS.c.day)
        )
        return [(row.pop("day"), Goals(**row)) for row in rows]

    def set_goal(self, person: str, day: str, goals: Goals) -> None:
        """Set the goals from `day` on, until the next day that has its own."""
        values = {
            "kcal": goals.kcal,
            "protein": goals.protein,
            "carbs": goals.carbs,
            "fat": goals.fat,
        }
        upsert = self._insert(GOALS).values(person=person, day=day, **values)
        with self._db.begin() as conn:
            conn.execute(
                upsert.on_conflict_do_update(index_elements=["person", "day"], set_=values)
            )
