"""The database: foods, entries, weights, daily goals and activity, in SQLite or Postgres.

Queries use SQLAlchemy Core, which Home Assistant already ships for its
recorder, so the same code runs on both. Every method blocks, so Home
Assistant code calls them in the executor.
"""

from __future__ import annotations

import itertools
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


def _schema_v3() -> MetaData:
    """Version 2, with who saved each food, and saved meals.

    A meal's owner is a person's key, or "" for a meal everyone shares. Its
    items are saved foods with grams, or fixed values with a name, for
    entries that came from no saved food.
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
        Column("saved_by", String(64)),
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
    meals = Table(
        "meals",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("owner", String(64), nullable=False),
        Column("name", Text, nullable=False),
        # The name casefolded, so that names differing only in case clash.
        Column("folded", Text, nullable=False),
        # Raised by every change, so that a change made to the meal as it
        # was at an older version can be refused.
        Column("version", Integer, nullable=False),
    )
    Index("meals_by_name", meals.c.owner, meals.c.folded, unique=True)
    Table(
        "meal_items",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("meal_id", Integer, ForeignKey("meals.id", ondelete="CASCADE"), nullable=False),
        Column("position", Integer, nullable=False),
        Column("food_id", Integer, ForeignKey("foods.id", ondelete="CASCADE")),
        Column("name", Text),
        Column("grams", Float),
        *[Column(n, Float) for n in NUTRIENTS],
    )
    return metadata


def _schema_v4() -> MetaData:
    """Version 3, with each food's name casefolded, to find it in any case.

    The databases' own lower() leaves letters outside ASCII as they are on
    SQLite, and on a Postgres whose locale is C.
    """
    metadata = _schema_v3()
    metadata.tables["foods"].append_column(
        Column("folded", Text, nullable=False, server_default="")
    )
    return metadata


def _schema_v5() -> MetaData:
    """Version 4, with each person's active calories, one row a day.

    `source` is the sensor's entity ID, or "action". `measured` is the day's
    figure in kcal, and the rest is what it came to under the person's
    settings that day, kept so that a past day explains its own goal.
    `last_reading` is the sensor's last reading that counted for the day,
    in kcal, or NULL if none did; it differs from `measured` once the
    action set the figure.
    """
    metadata = _schema_v4()
    Table(
        "activity",
        metadata,
        Column("person", String(64), primary_key=True),
        Column("day", String(10), primary_key=True),
        Column("source", Text, nullable=False),
        *[
            Column(n, Float, nullable=False)
            for n in ("measured", "counted", "added", "allowed", "share", "cap")
        ],
        Column("last_reading", Float),
    )
    return metadata


def _migrate_to_v1(conn: Connection) -> None:
    _schema_v1().create_all(conn)


def _migrate_to_v2(conn: Connection) -> None:
    source = _schema_v2().tables["entries"].c.source
    conn.execute(
        DDL(f"ALTER TABLE entries ADD COLUMN {CreateColumn(source).compile(dialect=conn.dialect)}")
    )


def _migrate_to_v3(conn: Connection) -> None:
    schema = _schema_v3()
    saved_by = schema.tables["foods"].c.saved_by
    conn.execute(
        DDL(f"ALTER TABLE foods ADD COLUMN {CreateColumn(saved_by).compile(dialect=conn.dialect)}")
    )
    schema.tables["meals"].create(conn)
    schema.tables["meal_items"].create(conn)


def _migrate_to_v4(conn: Connection) -> None:
    foods = _schema_v4().tables["foods"]
    folded = foods.c.folded
    conn.execute(
        DDL(f"ALTER TABLE foods ADD COLUMN {CreateColumn(folded).compile(dialect=conn.dialect)}")
    )
    for food_id, name in conn.execute(select(foods.c.id, foods.c.name)).all():
        conn.execute(update(foods).where(foods.c.id == food_id).values(folded=name.casefold()))


def _migrate_to_v5(conn: Connection) -> None:
    _schema_v5().tables["activity"].create(conn)


# Each entry upgrades the schema by one version; schema_version holds the
# version a database is at. Never edit a released entry, append a new one.
MIGRATIONS: list[Callable[[Connection], None]] = [
    _migrate_to_v1,
    _migrate_to_v2,
    _migrate_to_v3,
    _migrate_to_v4,
    _migrate_to_v5,
]

# The tables the queries below use: those of the latest version.
SCHEMA = _schema_v5()
PEOPLE, FOODS, ENTRIES, WEIGHTS, GOALS, SAVED_MEALS, MEAL_ITEMS, ACTIVITY = (
    SCHEMA.tables[name]
    for name in (
        "people",
        "foods",
        "entries",
        "weights",
        "goals",
        "meals",
        "meal_items",
        "activity",
    )
)

# An activity row's columns besides its person and day.
ACTIVITY_FIELDS = (
    "source",
    "measured",
    "counted",
    "added",
    "allowed",
    "share",
    "cap",
    "last_reading",
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
    del food["folded"]
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


# The owner of a saved meal that everyone shares.
EVERYONE = ""


class MealExistsError(Exception):
    """A meal that some of the same people see already has the name.

    `owner` is that meal's owner: a person's key, or EVERYONE.
    """

    def __init__(self, owner: str) -> None:
        super().__init__(f"a meal with this name exists for {owner or 'everyone'}")
        self.owner = owner


class MealChangedError(Exception):
    """The meal was changed or deleted since it was read."""


class FoodGoneError(Exception):
    """A meal item's saved food no longer exists."""


def _scaled(values: dict[str, Any], grams: float) -> dict[str, float | None]:
    """Nutrients per 100 g scaled to `grams`."""
    return {n: None if values[n] is None else values[n] * grams / 100 for n in NUTRIENTS}


def _clash(conn: Connection, owner: str, name: str, exclude: int | None = None) -> str | None:
    """The owner of a meal called `name` that someone who sees `owner`'s meals sees, or None.

    A person sees everyone's meals and their own, so a person's meal clashes
    with those, and an everyone meal clashes with every meal. Everyone's
    clash is the one returned when there are several.
    """
    query = select(SAVED_MEALS.c.owner).where(SAVED_MEALS.c.folded == name.casefold())
    if owner != EVERYONE:
        query = query.where(SAVED_MEALS.c.owner.in_([EVERYONE, owner]))
    if exclude is not None:
        query = query.where(SAVED_MEALS.c.id != exclude)
    row = conn.execute(query.order_by(SAVED_MEALS.c.owner).limit(1)).first()
    return None if row is None else row.owner


def _meals(conn: Connection, *where: Any) -> list[dict[str, Any]]:
    """The meals matching `where`, A to Z, each with its items in order.

    An item of a saved food takes the food's name and its values now, scaled
    to the item's grams. Owner is None for everyone's meals.
    """
    meals = conn.execute(
        select(SAVED_MEALS).where(*where).order_by(SAVED_MEALS.c.folded, SAVED_MEALS.c.id)
    ).all()
    if not meals:
        return []
    food_values = [FOODS.c[n].label(f"food_{n}") for n in NUTRIENTS]
    rows = conn.execute(
        select(MEAL_ITEMS, FOODS.c.name.label("food_name"), *food_values)
        .outerjoin(FOODS, FOODS.c.id == MEAL_ITEMS.c.food_id)
        .where(MEAL_ITEMS.c.meal_id.in_([m.id for m in meals]))
        .order_by(MEAL_ITEMS.c.meal_id, MEAL_ITEMS.c.position)
    )
    items: dict[int, list[dict[str, Any]]] = {m.id: [] for m in meals}
    for row in rows:
        r = row._mapping
        item = {"id": r["id"], "food_id": r["food_id"], "grams": r["grams"]}
        if r["food_id"] is None:
            item |= {"name": r["name"], **{n: r[n] for n in NUTRIENTS}}
        else:
            per_100g = {n: r[f"food_{n}"] for n in NUTRIENTS}
            item |= {"name": r["food_name"], **_scaled(per_100g, r["grams"])}
        items[r["meal_id"]].append(item)
    return [
        {
            "id": m.id,
            "owner": m.owner or None,
            "name": m.name,
            "version": m.version,
            "items": items[m.id],
        }
        for m in meals
    ]


def _write_items(conn: Connection, meal_id: int, items: Iterable[dict[str, Any]]) -> None:
    """Add `items` to a meal, in order: {food_id, grams}, or a name, grams and nutrients.

    Raises FoodGoneError if an item's food no longer exists.
    """
    for position, item in enumerate(items):
        if item.get("food_id") is not None:
            found = conn.execute(select(FOODS.c.id).where(FOODS.c.id == item["food_id"])).first()
            if found is None:
                raise FoodGoneError
            values = {"food_id": item["food_id"], "grams": item["grams"]}
        else:
            values = {"name": item["name"], "grams": item.get("grams")}
            values |= {n: item.get(n) for n in NUTRIENTS}
        conn.execute(insert(MEAL_ITEMS).values(meal_id=meal_id, position=position, **values))


def _insert_entries(conn: Connection, person: str, entries: Iterable[dict[str, Any]]) -> list[int]:
    return [
        conn.execute(
            insert(ENTRIES)
            .values(person=person, **{k: e.get(k) for k in ENTRY_FIELDS}, created_at=_now())
            .returning(ENTRIES.c.id)
        ).scalar_one()
        for e in entries
    ]


def _read_entries(conn: Connection, ids: list[int]) -> list[dict[str, Any]]:
    rows = conn.execute(select(ENTRIES).where(ENTRIES.c.id.in_(ids)).order_by(ENTRIES.c.id))
    return [dict(r._mapping) for r in rows]


def _check_meal(conn: Connection, meal_id: int, version: int | None) -> Any:
    """The meal's row, unless it is gone or, given `version`, changed since.

    Raises MealChangedError otherwise.
    """
    row = conn.execute(select(SAVED_MEALS).where(SAVED_MEALS.c.id == meal_id)).first()
    if row is None or (version is not None and row.version != version):
        raise MealChangedError
    return row


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
        """Delete everything stored for a person.

        That is their entries, weights, goals, activity and own saved meals,
        and the foods they saved that no entry of anyone's and no meal uses
        any more. The foods they saved that are still used stay, saved by
        nobody.
        """
        with self._db.begin() as conn:
            for table in (ENTRIES, WEIGHTS, GOALS, ACTIVITY):
                conn.execute(delete(table).where(table.c.person == person))
            own = select(SAVED_MEALS.c.id).where(SAVED_MEALS.c.owner == person)
            conn.execute(delete(MEAL_ITEMS).where(MEAL_ITEMS.c.meal_id.in_(own)))
            conn.execute(delete(SAVED_MEALS).where(SAVED_MEALS.c.owner == person))
            logged = select(ENTRIES.c.id).where(ENTRIES.c.food_id == FOODS.c.id).exists()
            in_meal = select(MEAL_ITEMS.c.id).where(MEAL_ITEMS.c.food_id == FOODS.c.id).exists()
            conn.execute(delete(FOODS).where(FOODS.c.saved_by == person, ~logged, ~in_meal))
            conn.execute(update(FOODS).where(FOODS.c.saved_by == person).values(saved_by=None))
            conn.execute(delete(PEOPLE).where(PEOPLE.c.key == person))

    def adopt_removed(self, people: Iterable[str]) -> None:
        """Give everyone the meals of people no longer in `people`, and forget who saved foods.

        A removed person's meal that would clash with another is renamed
        "Name (Person)", or "Name (Person 2)" and on. The meals stay
        everyone's if the person comes back.
        """
        keys = list(people)
        with self._db.begin() as conn:
            names = {row.key: row.name for row in conn.execute(select(PEOPLE))}
            orphans = conn.execute(
                select(SAVED_MEALS)
                .where(SAVED_MEALS.c.owner != EVERYONE, SAVED_MEALS.c.owner.not_in(keys))
                .order_by(SAVED_MEALS.c.id)
            ).all()
            for meal in orphans:
                who = names.get(meal.owner, meal.owner)
                suffixes = itertools.chain(
                    ["", f" ({who})"], (f" ({who} {n})" for n in itertools.count(2))
                )
                name = next(
                    f"{meal.name}{s}"
                    for s in suffixes
                    if _clash(conn, EVERYONE, f"{meal.name}{s}", exclude=meal.id) is None
                )
                conn.execute(
                    update(SAVED_MEALS)
                    .where(SAVED_MEALS.c.id == meal.id)
                    .values(
                        owner=EVERYONE,
                        name=name,
                        folded=name.casefold(),
                        version=SAVED_MEALS.c.version + 1,
                    )
                )
            conn.execute(
                update(FOODS)
                .where(FOODS.c.saved_by.is_not(None), FOODS.c.saved_by.not_in(keys))
                .values(saved_by=None)
            )

    # Foods

    def add_food(self, food: dict[str, Any]) -> dict[str, Any]:
        """Save a new food and return it. `saved_by` is a person's key, or None.

        Raises sqlalchemy.exc.IntegrityError if another food has its barcode.
        """
        values = {k: food.get(k) for k in FOOD_FIELDS}
        values["portions"] = json.dumps(food.get("portions") or [])
        values["saved_by"] = food.get("saved_by")
        values["folded"] = values["name"].casefold()
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
        if "name" in values:
            values["folded"] = values["name"].casefold()
        if values:
            with self._db.begin() as conn:
                conn.execute(
                    update(FOODS).where(FOODS.c.id == food_id).values(**values, updated_at=_now())
                )
        return self.food(food_id)

    def delete_food(self, food_id: int) -> bool:
        """Delete a food, and return whether there was one.

        Entries logged from it keep their copied numbers. It leaves the saved
        meals it was in, and a meal it leaves empty is deleted too.
        """
        with self._db.begin() as conn:
            meal_ids = (
                conn.execute(
                    select(MEAL_ITEMS.c.meal_id).where(MEAL_ITEMS.c.food_id == food_id).distinct()
                )
                .scalars()
                .all()
            )
            conn.execute(delete(MEAL_ITEMS).where(MEAL_ITEMS.c.food_id == food_id))
            if not conn.execute(delete(FOODS).where(FOODS.c.id == food_id)).rowcount:
                return False
            if meal_ids:
                has_items = select(MEAL_ITEMS.c.id).where(MEAL_ITEMS.c.meal_id == SAVED_MEALS.c.id)
                changed = SAVED_MEALS.c.id.in_(meal_ids)
                conn.execute(delete(SAVED_MEALS).where(changed, ~has_items.exists()))
                conn.execute(
                    update(SAVED_MEALS).where(changed).values(version=SAVED_MEALS.c.version + 1)
                )
            return True

    def meals_with_food(self, food_id: int) -> list[dict[str, Any]]:
        """The saved meals a food is in, A to Z, as {id, name, owner, emptied}.

        `emptied` says the meal holds nothing else, so deleting the food
        would delete it. Owner is None for everyone's meals.
        """
        other = select(MEAL_ITEMS.c.id).where(
            MEAL_ITEMS.c.meal_id == SAVED_MEALS.c.id,
            or_(MEAL_ITEMS.c.food_id.is_(None), MEAL_ITEMS.c.food_id != food_id),
        )
        using = select(MEAL_ITEMS.c.meal_id).where(MEAL_ITEMS.c.food_id == food_id)
        rows = self._all(
            select(
                SAVED_MEALS.c.id,
                SAVED_MEALS.c.name,
                SAVED_MEALS.c.owner,
                (~other.exists()).label("emptied"),
            )
            .where(SAVED_MEALS.c.id.in_(using))
            .order_by(SAVED_MEALS.c.folded, SAVED_MEALS.c.id)
        )
        return [r | {"owner": r["owner"] or None, "emptied": bool(r["emptied"])} for r in rows]

    def food(self, food_id: int) -> dict[str, Any] | None:
        """One food, or None."""
        with self._db.connect() as conn:
            return _food(conn.execute(select(FOODS).where(FOODS.c.id == food_id)).first())

    def food_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        """The food with this barcode, or None."""
        with self._db.connect() as conn:
            return _food(conn.execute(select(FOODS).where(FOODS.c.barcode == barcode)).first())

    def foods_named(self, name: str) -> list[dict[str, Any]]:
        """Foods called `name`, ignoring case, oldest first."""
        query = select(FOODS).where(FOODS.c.folded == name.casefold())
        with self._db.connect() as conn:
            return [_food(r) for r in conn.execute(query.order_by(FOODS.c.id))]

    def search_foods(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Foods whose name contains `query`, ignoring case, or whose barcode is `query`."""
        escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        found = (
            select(FOODS)
            .where(
                or_(
                    FOODS.c.folded.like(f"%{escaped}%", escape="\\"),
                    FOODS.c.barcode == query,
                )
            )
            .order_by(FOODS.c.folded)
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

    # Saved meals

    def meals(self, person: str | None = None) -> list[dict[str, Any]]:
        """Saved meals, A to Z, with their items: everyone's and `person`'s own, or all."""
        with self._db.connect() as conn:
            if person is None:
                return _meals(conn)
            return _meals(conn, SAVED_MEALS.c.owner.in_([EVERYONE, person]))

    def meal(self, meal_id: int) -> dict[str, Any] | None:
        """One saved meal with its items, or None."""
        with self._db.connect() as conn:
            found = _meals(conn, SAVED_MEALS.c.id == meal_id)
        return found[0] if found else None

    def meals_named(self, name: str) -> list[dict[str, Any]]:
        """The saved meals called `name`, ignoring case, everyone's first."""
        with self._db.connect() as conn:
            found = _meals(conn, SAVED_MEALS.c.folded == name.casefold())
        return sorted(found, key=lambda m: m["owner"] is not None)

    def add_meal(self, owner: str, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Save a meal for `owner`, a person's key or EVERYONE, and return it.

        Items are {food_id, grams}, or {name, grams, nutrients...} for fixed
        values. Raises MealExistsError if the name clashes, and FoodGoneError
        if a food is gone.
        """
        with self._db.begin() as conn:
            clash = _clash(conn, owner, name)
            if clash is not None:
                raise MealExistsError(clash)
            meal_id = conn.execute(
                insert(SAVED_MEALS)
                .values(owner=owner, name=name, folded=name.casefold(), version=1)
                .returning(SAVED_MEALS.c.id)
            ).scalar_one()
            _write_items(conn, meal_id, items)
        return self.meal(meal_id)

    def update_meal(self, meal_id: int, version: int, changes: dict[str, Any]) -> dict[str, Any]:
        """Change a meal's name, owner or items (all of them, replaced), and return it.

        Raises MealChangedError if it changed or went since `version`,
        MealExistsError if the new name or owner clashes, and FoodGoneError
        if a food is gone.
        """
        with self._db.begin() as conn:
            row = _check_meal(conn, meal_id, version)
            name, owner = changes.get("name", row.name), changes.get("owner", row.owner)
            clash = _clash(conn, owner, name, exclude=meal_id)
            if clash is not None:
                raise MealExistsError(clash)
            conn.execute(
                update(SAVED_MEALS)
                .where(SAVED_MEALS.c.id == meal_id)
                .values(
                    owner=owner,
                    name=name,
                    folded=name.casefold(),
                    version=SAVED_MEALS.c.version + 1,
                )
            )
            if "items" in changes:
                conn.execute(delete(MEAL_ITEMS).where(MEAL_ITEMS.c.meal_id == meal_id))
                _write_items(conn, meal_id, changes["items"])
        return self.meal(meal_id)

    def delete_meal(self, meal_id: int, version: int) -> None:
        """Delete a meal. Entries logged from it stay.

        Raises MealChangedError if it changed or went since `version`.
        """
        with self._db.begin() as conn:
            _check_meal(conn, meal_id, version)
            conn.execute(delete(MEAL_ITEMS).where(MEAL_ITEMS.c.meal_id == meal_id))
            conn.execute(delete(SAVED_MEALS).where(SAVED_MEALS.c.id == meal_id))

    def log_meal(
        self,
        person: str,
        day: str,
        meal: str,
        meal_id: int,
        version: int | None = None,
        item_ids: Iterable[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Log a saved meal's items as entries in one go, and return them.

        Every item, or those in `item_ids`. Each becomes a plain entry, with
        its food's values now. Raises MealChangedError, logging nothing, if
        the meal is gone, is another person's own, changed since
        `version`, or lacks one of `item_ids`.
        """
        with self._db.begin() as conn:
            row = _check_meal(conn, meal_id, version)
            if row.owner not in (EVERYONE, person):
                raise MealChangedError
            items = _meals(conn, SAVED_MEALS.c.id == meal_id)[0]["items"]
            if item_ids is not None:
                wanted = set(item_ids)
                items = [i for i in items if i["id"] in wanted]
                if len(items) != len(wanted):
                    raise MealChangedError
            values = ("food_id", "name", "grams", *NUTRIENTS)
            entries = [{"day": day, "meal": meal, **{k: i[k] for k in values}} for i in items]
            return _read_entries(conn, _insert_entries(conn, person, entries))

    # Entries

    def add_entries(self, person: str, entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Log several entries, all or none, and return them in order."""
        with self._db.begin() as conn:
            return _read_entries(conn, _insert_entries(conn, person, entries))

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

    def export(self, person: str) -> dict[str, Any]:
        """A person's entries, weights and activity, oldest first, every saved food, and meals.

        Foods are everyone's, so they are all there; the meals are everyone's
        and the person's own. `people` maps every key ever known to its name.
        Read in one transaction, so they all agree.
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
            activity = conn.execute(
                select(ACTIVITY).where(ACTIVITY.c.person == person).order_by(ACTIVITY.c.day)
            )
            return {
                "entries": [dict(r._mapping) for r in entries],
                "weights": [dict(r._mapping) for r in weights],
                "activity": [dict(r._mapping) for r in activity],
                "foods": [_food(r) for r in conn.execute(select(FOODS).order_by(FOODS.c.id))],
                "meals": _meals(conn, SAVED_MEALS.c.owner.in_([EVERYONE, person])),
                "people": {row.key: row.name for row in conn.execute(select(PEOPLE))},
            }

    # Goals

    def goal_in_force(self, person: str, day: str) -> tuple[str, Goals] | None:
        """The day the goals in force on `day` were set, and those goals; or None."""
        row = self._one(
            select(GOALS.c.day, GOALS.c.kcal, GOALS.c.protein, GOALS.c.carbs, GOALS.c.fat)
            .where(GOALS.c.person == person, GOALS.c.day <= day)
            .order_by(GOALS.c.day.desc())
            .limit(1)
        )
        return (row.pop("day"), Goals(**row)) if row else None

    def first_goal_day(self, person: str) -> str | None:
        """The first day a person's goals were set, or None if they never were."""
        with self._db.connect() as conn:
            query = select(func.min(GOALS.c.day)).where(GOALS.c.person == person)
            return conn.execute(query).scalar()

    def activity_added(self, person: str, start: str, end: str) -> dict[str, float]:
        """What activity added to a person's goal, by day, from `start` to `end`.

        Only days with activity are there.
        """
        rows = self._all(
            select(ACTIVITY.c.day, ACTIVITY.c.added).where(
                ACTIVITY.c.person == person, ACTIVITY.c.day.between(start, end)
            )
        )
        return {row["day"]: row["added"] for row in rows}

    def goal_changes(self, person: str, end: str) -> list[tuple[str, Goals]]:
        """Each day up to `end` on which a person's goals were set, oldest first."""
        rows = self._all(
            select(GOALS.c.day, GOALS.c.kcal, GOALS.c.protein, GOALS.c.carbs, GOALS.c.fat)
            .where(GOALS.c.person == person, GOALS.c.day <= end)
            .order_by(GOALS.c.day)
        )
        return [(row.pop("day"), Goals(**row)) for row in rows]

    def _set_goal(self, conn: Connection, person: str, day: str, goals: Goals) -> None:
        values = {
            "kcal": goals.kcal,
            "protein": goals.protein,
            "carbs": goals.carbs,
            "fat": goals.fat,
        }
        upsert = self._insert(GOALS).values(person=person, day=day, **values)
        conn.execute(upsert.on_conflict_do_update(index_elements=["person", "day"], set_=values))

    # Activity

    def activity(self, person: str, day: str) -> dict[str, Any] | None:
        """A person's activity on `day`, as ACTIVITY_FIELDS, or None."""
        return self._one(
            select(*(ACTIVITY.c[f] for f in ACTIVITY_FIELDS)).where(
                ACTIVITY.c.person == person, ACTIVITY.c.day == day
            )
        )

    def set_day(
        self,
        person: str,
        day: str,
        activity: dict[str, Any] | None,
        goals: Goals | None = None,
        pin: tuple[str, Goals] | None = None,
    ) -> None:
        """Set a person's activity on `day`, or delete it if None, and the day's goals if given.

        All or nothing. `pin`, a later day and its goals, first gives that
        day a goals row of its own with them, unless it has one, so that
        `goals` stop before it.
        """
        with self._db.begin() as conn:
            if pin is not None:
                pin_day, kept = pin
                insert_new = self._insert(GOALS).values(
                    person=person,
                    day=pin_day,
                    kcal=kept.kcal,
                    protein=kept.protein,
                    carbs=kept.carbs,
                    fat=kept.fat,
                )
                conn.execute(insert_new.on_conflict_do_nothing(index_elements=["person", "day"]))
            if activity is None:
                conn.execute(
                    delete(ACTIVITY).where(ACTIVITY.c.person == person, ACTIVITY.c.day == day)
                )
            else:
                upsert = self._insert(ACTIVITY).values(person=person, day=day, **activity)
                conn.execute(
                    upsert.on_conflict_do_update(index_elements=["person", "day"], set_=activity)
                )
            if goals is not None:
                self._set_goal(conn, person, day, goals)
