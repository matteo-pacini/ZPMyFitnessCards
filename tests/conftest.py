"""A throwaway Postgres server, for the tests that run against Postgres.

The Nix dev shell provides the server. Each test session starts its own in
a temporary folder, listening only on a Unix socket in that folder, and each
test gets a database of its own. Everything is stopped and deleted
afterwards, even when a test fails.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine

_names = itertools.count()


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[str]:
    """Start a Postgres server for the session; yield its URL with a {database} slot."""
    if shutil.which("initdb") is None:
        pytest.fail("initdb is not on PATH: run the tests in the Nix dev shell")
    # Under /tmp, not $TMPDIR: a socket path must stay under about 100 bytes.
    root = Path(tempfile.mkdtemp(prefix="fork-and-scale-pg-", dir="/tmp"))
    data = root / "data"
    try:
        subprocess.run(
            [
                "initdb",
                "-D",
                data,
                "-U",
                "postgres",
                "--auth=trust",
                "--no-sync",
                "--encoding=UTF8",
                "--locale=C",
            ],
            check=True,
            capture_output=True,
        )
        # No TCP at all: nothing to clash with, and Home Assistant's test
        # plugin, which blocks sockets, does not see libpq's.
        options = (
            f"-c listen_addresses='' -c unix_socket_directories={root} "
            "-c fsync=off -c full_page_writes=off"
        )
        subprocess.run(
            ["pg_ctl", "-D", data, "-l", root / "server.log", "-w", "-o", options, "start"],
            check=True,
            capture_output=True,
        )
        yield f"postgresql://postgres@/{{database}}?host={root}"
    finally:
        if (data / "postmaster.pid").exists():
            subprocess.run(
                ["pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True
            )
        shutil.rmtree(root, ignore_errors=True)


@contextmanager
def new_database(server: str) -> Iterator[str]:
    """Create an empty database on `server`; yield its URL, then drop it."""
    name = f"test_{os.getpid()}_{next(_names)}"
    admin = create_engine(server.format(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
        yield server.format(database=name)
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        admin.dispose()


@pytest.fixture
def postgres_database(postgres_server: str) -> Iterator[str]:
    """A new, empty Postgres database; yield its URL. It is dropped afterwards."""
    with new_database(postgres_server) as url:
        yield url


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """A database URL: an SQLite file, then a Postgres database, for each test using it."""
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    return request.getfixturevalue("postgres_database")
