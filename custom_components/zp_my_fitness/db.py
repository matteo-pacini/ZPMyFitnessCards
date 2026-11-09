"""The SQLite database: foods, entries, weights and daily goals.

Every method blocks, so Home Assistant code calls them in the executor. One
connection serves all threads, behind a lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .const import MEALS, NUTRIENTS
from .goals import Goals

# Each entry upgrades the schema by one version. PRAGMA user_version holds the
# version a database is at; never edit a released entry, append a new one.
MIGRATIONS: list[str] = [
    f"""
    CREATE TABLE people (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL
    );
    CREATE TABLE foods (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        barcode TEXT UNIQUE,
        kcal REAL NOT NULL,
        protein REAL NOT NULL,
        carbs REAL NOT NULL,
        fat REAL NOT NULL,
        fibre REAL,
        sugar REAL,
        saturated_fat REAL,
        salt REAL,
        portions TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    );
    CREATE TABLE entries (
        id INTEGER PRIMARY KEY,
        person TEXT NOT NULL,
        day TEXT NOT NULL,
        meal TEXT NOT NULL CHECK (meal IN ({", ".join(f"'{m}'" for m in MEALS)})),
        food_id INTEGER REFERENCES foods (id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        grams REAL,
        kcal REAL NOT NULL,
        protein REAL,
        carbs REAL,
        fat REAL,
        fibre REAL,
        sugar REAL,
        saturated_fat REAL,
        salt REAL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX entries_by_day ON entries (person, day);
    CREATE TABLE weights (
        person TEXT NOT NULL,
        day TEXT NOT NULL,
        kg REAL NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (person, day)
    );
    CREATE TABLE goals (
        person TEXT NOT NULL,
        day TEXT NOT NULL,
        kcal REAL NOT NULL,
        protein REAL NOT NULL,
        carbs REAL NOT NULL,
        fat REAL NOT NULL,
        PRIMARY KEY (person, day)
    );
    """,
]

FOOD_FIELDS = ("name", "barcode", *NUTRIENTS, "portions")
ENTRY_FIELDS = ("day", "meal", "food_id", "name", "grams", *NUTRIENTS)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _food(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    food = dict(row)
    food["portions"] = json.loads(food["portions"])
    return food


class Database:
    """The integration's data, in one SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # Connection

    def open(self) -> None:
        """Open the file, creating it if needed, and upgrade its schema."""
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn = conn
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                # The script and its version bump commit together, or not at all.
                conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")

    def close(self) -> None:
        """Close the file."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def checkpoint(self) -> None:
        """Move the write-ahead log into the main file, so the file alone is complete."""
        with self._lock:
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @property
    def _db(self) -> sqlite3.Connection:
        assert self._conn is not None, "database is not open"
        return self._conn

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, tuple(params))]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def schema_version(self) -> int:
        """The schema version the file is at."""
        with self._lock:
            return self._db.execute("PRAGMA user_version").fetchone()[0]

    # People

    def sync_people(self, people: Iterable[tuple[str, str]]) -> None:
        """Record each (key, name), so a removed person's name is remembered."""
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO people (key, name) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET name = excluded.name",
                list(people),
            )

    def key_for_name(self, name: str, exclude: Iterable[str]) -> str | None:
        """The key of a person once called `name`, ignoring case, unless in `exclude`."""
        excluded = set(exclude)
        for row in self._all("SELECT key, name FROM people"):
            if row["name"].casefold() == name.casefold() and row["key"] not in excluded:
                return row["key"]
        return None

    def delete_person(self, person: str) -> None:
        """Delete everything stored for a person."""
        with self._lock, self._db:
            for table in ("entries", "weights", "goals"):
                self._db.execute(f"DELETE FROM {table} WHERE person = ?", (person,))
            self._db.execute("DELETE FROM people WHERE key = ?", (person,))

    # Foods

    def add_food(self, food: dict[str, Any]) -> dict[str, Any]:
        """Save a new food and return it. Raises sqlite3.IntegrityError on a used barcode."""
        values = {k: food.get(k) for k in FOOD_FIELDS}
        values["portions"] = json.dumps(food.get("portions") or [])
        with self._lock, self._db:
            cursor = self._db.execute(
                f"INSERT INTO foods ({', '.join(values)}, updated_at) "
                f"VALUES ({', '.join('?' * len(values))}, ?)",
                (*values.values(), _now()),
            )
        return self.food(cursor.lastrowid)

    def update_food(self, food_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Change some of a food's fields and return it, or None if there is no such food."""
        values = {k: changes[k] for k in FOOD_FIELDS if k in changes}
        if "portions" in values:
            values["portions"] = json.dumps(values["portions"] or [])
        if values:
            with self._lock, self._db:
                self._db.execute(
                    f"UPDATE foods SET {', '.join(f'{k} = ?' for k in values)}, updated_at = ? "
                    "WHERE id = ?",
                    (*values.values(), _now(), food_id),
                )
        return self.food(food_id)

    def delete_food(self, food_id: int) -> bool:
        """Delete a food. Entries logged from it keep their copied numbers."""
        with self._lock, self._db:
            return self._db.execute("DELETE FROM foods WHERE id = ?", (food_id,)).rowcount > 0

    def food(self, food_id: int) -> dict[str, Any] | None:
        """One food, or None."""
        with self._lock:
            return _food(
                self._db.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
            )

    def food_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        """The food with this barcode, or None."""
        with self._lock:
            row = self._db.execute("SELECT * FROM foods WHERE barcode = ?", (barcode,)).fetchone()
            return _food(row)

    def search_foods(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Foods whose name contains `query`, ignoring case, or whose barcode is `query`."""
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM foods WHERE name LIKE ? ESCAPE '\\' OR barcode = ? "
                "ORDER BY name COLLATE NOCASE LIMIT ?",
                (pattern, query, limit),
            ).fetchall()
        return [_food(r) for r in rows]

    def recent_foods(self, person: str, limit: int) -> list[dict[str, Any]]:
        """The foods a person logged most recently, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT foods.* FROM foods JOIN ("
                "  SELECT food_id, MAX(id) AS last FROM entries"
                "  WHERE person = ? AND food_id IS NOT NULL GROUP BY food_id"
                ") recent ON recent.food_id = foods.id ORDER BY recent.last DESC LIMIT ?",
                (person, limit),
            ).fetchall()
        return [_food(r) for r in rows]

    # Entries

    def add_entry(self, person: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Log an entry and return it."""
        values = {k: entry.get(k) for k in ENTRY_FIELDS}
        with self._lock, self._db:
            cursor = self._db.execute(
                f"INSERT INTO entries (person, {', '.join(values)}, created_at) "
                f"VALUES (?, {', '.join('?' * len(values))}, ?)",
                (person, *values.values(), _now()),
            )
        return self.entry(cursor.lastrowid)

    def update_entry(self, entry_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Change some of an entry's fields and return it, or None if there is no such entry."""
        values = {k: changes[k] for k in ENTRY_FIELDS if k in changes}
        if values:
            with self._lock, self._db:
                self._db.execute(
                    f"UPDATE entries SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                    (*values.values(), entry_id),
                )
        return self.entry(entry_id)

    def delete_entry(self, entry_id: int) -> None:
        """Delete an entry."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))

    def entry(self, entry_id: int) -> dict[str, Any] | None:
        """One entry, or None."""
        return self._one("SELECT * FROM entries WHERE id = ?", (entry_id,))

    def day_entries(self, person: str, day: str) -> list[dict[str, Any]]:
        """A person's entries on `day`, in the order they were logged."""
        return self._all(
            "SELECT * FROM entries WHERE person = ? AND day = ? ORDER BY id", (person, day)
        )

    def meal_totals(self, person: str, start: str, end: str) -> dict[str, dict[str, dict]]:
        """Sums of each nutrient by day and meal, for days from `start` to `end`.

        Returns {day: {meal: {nutrient: sum}}}, with only days and meals that
        have entries.
        """
        sums = ", ".join(f"TOTAL({n}) AS {n}" for n in NUTRIENTS)
        rows = self._all(
            f"SELECT day, meal, {sums} FROM entries "
            "WHERE person = ? AND day BETWEEN ? AND ? GROUP BY day, meal",
            (person, start, end),
        )
        result: dict[str, dict[str, dict]] = {}
        for row in rows:
            result.setdefault(row["day"], {})[row["meal"]] = {n: row[n] for n in NUTRIENTS}
        return result

    # Weights

    def set_weight(self, person: str, day: str, kg: float) -> None:
        """Record a person's weight for `day`, replacing any earlier one that day."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO weights (person, day, kg, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (person, day) DO UPDATE SET kg = excluded.kg, "
                "updated_at = excluded.updated_at",
                (person, day, kg, _now()),
            )

    def delete_weight(self, person: str, day: str) -> None:
        """Delete a person's weight for `day`."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM weights WHERE person = ? AND day = ?", (person, day))

    def weights(self, person: str, start: str, end: str) -> list[dict[str, Any]]:
        """A person's weights from `start` to `end`, oldest first, as {day, kg}."""
        return self._all(
            "SELECT day, kg FROM weights WHERE person = ? AND day BETWEEN ? AND ? ORDER BY day",
            (person, start, end),
        )

    def latest_weight(self, person: str, day: str) -> dict[str, Any] | None:
        """A person's last weight on or before `day`, as {day, kg}, or None."""
        return self._one(
            "SELECT day, kg FROM weights WHERE person = ? AND day <= ? ORDER BY day DESC LIMIT 1",
            (person, day),
        )

    # Goals

    def goal_on(self, person: str, day: str) -> Goals | None:
        """The goals in force on `day`: the last ones set on or before it."""
        row = self._one(
            "SELECT kcal, protein, carbs, fat FROM goals WHERE person = ? AND day <= ? "
            "ORDER BY day DESC LIMIT 1",
            (person, day),
        )
        return Goals(**row) if row else None

    def goal_changes(self, person: str, end: str) -> list[tuple[str, Goals]]:
        """Each day up to `end` on which a person's goals were set, oldest first."""
        rows = self._all(
            "SELECT day, kcal, protein, carbs, fat FROM goals WHERE person = ? AND day <= ? "
            "ORDER BY day",
            (person, end),
        )
        return [(row.pop("day"), Goals(**row)) for row in rows]

    def set_goal(self, person: str, day: str, goals: Goals) -> None:
        """Set the goals from `day` on, until the next day that has its own."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO goals (person, day, kcal, protein, carbs, fat) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (person, day) DO UPDATE SET "
                "kcal = excluded.kcal, protein = excluded.protein, "
                "carbs = excluded.carbs, fat = excluded.fat",
                (person, day, goals.kcal, goals.protein, goals.carbs, goals.fat),
            )
