"""A brand-new Home Assistant for each test session, set up as a person would.

The `home` fixture starts Home Assistant from .venv on a free localhost port,
with an empty configuration folder that links this repo's integration. It
then completes onboarding, adds the integration and its people through the
same REST API the UI uses, and saves a test dashboard. The folder is deleted
afterwards, so every session starts from nothing.

That Home Assistant searches Open Food Facts on a local fake (`search`), set
through METRON_SEARCH_URL, since the VM checks run with no network.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from custom_components.metron.const import DB_FILE
from custom_components.metron.db import sqlite_url

from ..conftest import new_database

REPO = Path(__file__).resolve().parents[2]

# Test values for the throwaway instance; it only ever listens on 127.0.0.1.
OWNER = {"name": "Test Owner", "username": "owner", "password": "test-password-e2e"}

PEOPLE = ["Matteo", "Debora"]

# The person form, as filled in for each of PEOPLE.
PERSON_FORMS = {
    "Matteo": {
        "sex": "male",
        "birth_date": "1990-06-01",
        "height_cm": 180,
        "start_weight_kg": 95,
        "start_date": "2025-11-01",
        "goal_weight_kg": 82,
        "activity": "light",
        "pace": "lose_0_5",
        "protein_pct": 25,
        "carbs_pct": 45,
        "fat_pct": 30,
    },
    "Debora": {
        "sex": "female",
        "birth_date": "1996-03-15",
        "height_cm": 165,
        "start_weight_kg": 70,
        "start_date": "2026-11-01",
        "goal_weight_kg": 62,
        "activity": "moderate",
        "pace": "lose_0_5",
        "protein_pct": 20,
        "carbs_pct": 50,
        "fat_pct": 30,
    },
}

CONFIGURATION = """\
homeassistant:
  name: Test home
  time_zone: Europe/London
  unit_system: metric
  country: GB
  currency: GBP
  latitude: 51.5
  longitude: -0.12
  elevation: 0
http:
  server_host: 127.0.0.1
  server_port: {port}
frontend:
config:
person:
lovelace:
"""


@dataclass
class Home:
    """A running Home Assistant and the owner's tokens."""

    url: str
    config_dir: Path
    # The integration's database: SQLite in config_dir, or a Postgres database.
    db_url: str
    tokens: dict[str, Any] = field(default_factory=dict)

    def api(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> Any:
        """Call the REST API and return the decoded JSON reply."""
        request = urllib.request.Request(
            self.url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        if auth:
            request.add_header("Authorization", f"Bearer {self.tokens['access_token']}")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or "null")

    def ws(self, message: dict[str, Any]) -> Any:
        """Send one websocket command and return its result."""

        async def call() -> Any:
            async with (
                aiohttp.ClientSession() as session,
                session.ws_connect(self.url + "/api/websocket") as ws,
            ):
                await ws.receive_json()
                await ws.send_json({"type": "auth", "access_token": self.tokens["access_token"]})
                assert (await ws.receive_json())["type"] == "auth_ok"
                await ws.send_json({"id": 1, **message})
                reply = await ws.receive_json()
                assert reply["success"], reply
                return reply["result"]

        # Playwright's sync API keeps an event loop running on this thread.
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, call()).result()

    DASHBOARD = "metron-test"

    def dashboard(self, cards: list[dict[str, Any]]) -> None:
        """Show `cards` on the test dashboard, creating it the first time."""
        dashboards = self.ws({"type": "lovelace/dashboards/list"})
        if not any(d["url_path"] == self.DASHBOARD for d in dashboards):
            self.ws(
                {
                    "type": "lovelace/dashboards/create",
                    "url_path": self.DASHBOARD,
                    "title": "Food",
                    "mode": "storage",
                }
            )
        self.ws(
            {
                "type": "lovelace/config/save",
                "url_path": self.DASHBOARD,
                "config": {"views": [{"title": "Test", "cards": cards}]},
            }
        )

    def log(self) -> str:
        """Home Assistant's log so far."""
        return (self.config_dir / "home-assistant.log").read_text()

    @contextmanager
    def us_customary(self) -> Iterator[None]:
        """Switch to US customary units, then back to metric, whatever happens.

        Both switches update the sensors' units too, as Settings > General
        offers to.
        """

        def switch(system: str) -> None:
            self.ws({"type": "config/core/update", "unit_system": system, "update_units": True})

        switch("us_customary")
        try:
            yield
        finally:
            switch("metric")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(home: Home, process: subprocess.Popen, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Home Assistant exited early:\n{home.log()[-4000:]}")
        try:
            home.api("GET", "/api/onboarding", auth=False)
            return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Home Assistant did not start in {seconds} s")


def _wait_until_running(home: Home, seconds: float = 300) -> None:
    """Wait for startup to finish.

    Until then the frontend shows a "Starting ..." toast over the bottom of
    the page, where it can catch the tests' clicks. Onboarding's weather
    integration keeps startup going for minutes with no network.
    """
    deadline = time.monotonic() + seconds
    while home.api("GET", "/api/config")["state"] != "RUNNING":
        if time.monotonic() > deadline:
            raise TimeoutError(f"Home Assistant did not finish starting in {seconds} s")
        time.sleep(0.5)


def _onboard(home: Home) -> None:
    """Create the owner, then finish the remaining onboarding steps."""
    client_id = home.url + "/"
    code = home.api(
        "POST",
        "/api/onboarding/users",
        {**OWNER, "client_id": client_id, "language": "en"},
        auth=False,
    )["auth_code"]
    form = urllib.parse.urlencode(
        {"grant_type": "authorization_code", "code": code, "client_id": client_id}
    ).encode()
    with urllib.request.urlopen(home.url + "/auth/token", data=form, timeout=30) as response:
        home.tokens = json.loads(response.read())
    home.api("POST", "/api/onboarding/core_config", {})
    home.api("POST", "/api/onboarding/analytics", {})
    home.api(
        "POST", "/api/onboarding/integration", {"client_id": client_id, "redirect_uri": client_id}
    )
    # Home Assistant holds the port and address from configuration.yaml as
    # pending until someone confirms them, and asks in a dialog over the
    # dashboard. This is that dialog's Confirm.
    home.ws({"type": "http/config/promote"})


def _add_integration(home: Home, db_url: str | None) -> str:
    """Add Metron on SQLite, or on Postgres at `db_url`, then each person.

    Everything goes through the same REST calls the UI's dialogs make.
    """
    flow = home.api("POST", "/api/config/config_entries/flow", {"handler": "metron"})
    step = f"/api/config/config_entries/flow/{flow['flow_id']}"
    if db_url is None:
        entry = home.api("POST", step, {"engine": "sqlite"})
    else:
        home.api("POST", step, {"engine": "postgresql"})
        entry = home.api("POST", step, {"db_url": db_url})
    assert entry["type"] == "create_entry", entry
    entry_id = entry["result"]["entry_id"]
    for name in PEOPLE:
        flow = home.api(
            "POST",
            "/api/config/config_entries/subentries/flow",
            {"handler": [entry_id, "person"]},
        )
        done = home.api(
            "POST",
            f"/api/config/config_entries/subentries/flow/{flow['flow_id']}",
            {"name": name, **PERSON_FORMS[name]},
        )
        assert done["type"] == "create_entry", done
    # Adding a person reloads the entry in the background. Wait until the
    # reloaded entry answers with everyone.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            people = home.ws({"type": "metron/people"})
        except AssertionError:
            people = []
        if sorted(p["name"] for p in people) == sorted(PEOPLE):
            return entry_id
        time.sleep(0.2)
    raise TimeoutError("Metron did not finish loading its people")


class FakeSearch:
    """Search-a-licious for the test Home Assistant, on a free localhost port.

    It answers each request with `answer(params)`, a (status, JSON body)
    pair, and keeps each request's query parameters in `asked`.
    """

    def __init__(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                fake.asked.append(params)
                status, body = fake.answer(params)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/search"
        self.reset()

    def reset(self) -> None:
        """Forget what was asked, and fail every search until told otherwise."""
        self.asked: list[dict[str, str]] = []
        self.answer: Callable[[dict[str, str]], tuple[int, Any]] = lambda _params: (
            503,
            {"detail": "the test gave no answer"},
        )

    def find(self, products: list[dict[str, Any]]) -> None:
        """Answer every search with `products`, ten to a page."""

        def answer(params: dict[str, str]) -> tuple[int, Any]:
            page = int(params["page"])
            return 200, {
                "hits": products[(page - 1) * 10 : page * 10],
                "page": page,
                "page_size": 10,
                "page_count": -(-len(products) // 10),
                "count": len(products),
                "debug": {"query": {}},
                "took": 1,
                "timed_out": False,
                "is_count_exact": True,
            }

        self.answer = answer


@pytest.fixture(scope="session")
def search_server() -> Iterator[FakeSearch]:
    """The fake Search-a-licious, running for the whole session."""
    fake = FakeSearch()
    thread = threading.Thread(target=fake.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        fake.server.shutdown()
        fake.server.server_close()
        thread.join()


@pytest.fixture
def search(search_server: FakeSearch) -> FakeSearch:
    """The fake Search-a-licious, failing every search until the test says what to find."""
    search_server.reset()
    return search_server


@pytest.fixture(scope="session", params=["sqlite", "postgresql"])
def home(request: pytest.FixtureRequest, search_server: FakeSearch) -> Iterator[Home]:
    """A brand-new, onboarded Home Assistant with the integration and two people.

    Every test using it runs twice: with the data in SQLite, then in Postgres.
    """
    with ExitStack() as cleanup:
        db_url = None
        if request.param == "postgresql":
            server = request.getfixturevalue("postgres_server")
            db_url = cleanup.enter_context(new_database(server))
        yield from _home(db_url, search_url=search_server.url)


def _home(
    db_url: str | None,
    configuration: str = CONFIGURATION,
    search_url: str | None = None,
    database: Callable[[str], None] | None = None,
    integration: bool = True,
) -> Iterator[Home]:
    """Start Home Assistant, set it up, yield it, then stop it and delete it.

    `configuration` is configuration.yaml with a `{port}` slot. With
    `search_url`, the integration searches Open Food Facts there. With
    `database`, it gets the integration's database URL before Home Assistant
    starts, to leave a database there as an older release would have. With
    `integration` False, the integration is installed but not added.
    """
    config_dir = Path(tempfile.mkdtemp(prefix="metron-e2e-"))
    port = _free_port()
    (config_dir / "configuration.yaml").write_text(configuration.format(port=port))
    (config_dir / "custom_components").mkdir()
    (config_dir / "custom_components" / "metron").symlink_to(REPO / "custom_components" / "metron")
    home = Home(
        url=f"http://127.0.0.1:{port}",
        config_dir=config_dir,
        db_url=db_url or sqlite_url(str(config_dir / DB_FILE)),
    )
    if database:
        database(home.db_url)
    # Uploaded files go to Home Assistant's temporary folder, kept here so
    # that they go with the run.
    (config_dir / "tmp").mkdir()
    # --skip-pip: everything this test needs is already in .venv, and the
    # integrations that fail without their packages are not ones it uses.
    env = {**os.environ, "TMPDIR": str(config_dir / "tmp")}
    if search_url:
        env["METRON_SEARCH_URL"] = search_url
    process = subprocess.Popen(
        [sys.executable, "-m", "homeassistant", "--config", str(config_dir), "--skip-pip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        try:
            _wait_until_up(home, process)
            _onboard(home)
            if integration:
                _add_integration(home, db_url)
            _wait_until_running(home)
        except Exception as err:
            # The temporary folder goes with the run, so keep the log's end here.
            log = home.log()[-6000:] if (config_dir / "home-assistant.log").exists() else ""
            raise RuntimeError(
                f"Setting up the test Home Assistant failed: {err!r}\n{log}"
            ) from err
        yield home
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(config_dir, ignore_errors=True)


@pytest.fixture
def us_customary(home: Home) -> Iterator[None]:
    """The test Home Assistant in US customary units, which weigh in lb, for one test."""
    with home.us_customary():
        yield


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """Chromium from the Nix dev shell."""
    driver = os.environ.get("PLAYWRIGHT_DRIVER_VERSION")
    if driver is None:
        pytest.skip("run inside the Nix dev shell, which provides Chromium")
    assert version("playwright") == driver, (
        f"Playwright for Python is {version('playwright')}, but the Nix shell's driver is "
        f"{driver}: set playwright=={driver} in pyproject.toml"
    )
    # The shell's fonts in place of the host's, so pages render alike everywhere.
    env = {**os.environ, "FONTCONFIG_FILE": os.environ["METRON_FONTCONFIG_FILE"]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(env=env)
        yield browser
        browser.close()


@pytest.fixture
def page(home: Home, browser: Browser) -> Iterator[Page]:
    """A browser tab, logged in as the owner."""
    yield from logged_in_page(home, browser)


def logged_in_page(home: Home, browser: Browser, **options: Any) -> Iterator[Page]:
    """A browser tab on `home`, logged in as the owner, closed when the generator ends.

    `options` are the browser context's, such as a phone's size and touch;
    the window is a laptop's unless they say otherwise.
    """
    context = browser.new_context(**{"viewport": {"width": 1280, "height": 900}, **options})
    stored = {
        **home.tokens,
        "hassUrl": home.url,
        "clientId": home.url + "/",
        "expires": int(time.time() * 1000) + home.tokens["expires_in"] * 1000,
    }
    context.add_init_script(f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(stored))})")
    page = context.new_page()
    yield page
    context.close()
