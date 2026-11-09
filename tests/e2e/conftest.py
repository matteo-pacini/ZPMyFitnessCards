"""A brand-new Home Assistant for each test session, set up as a person would.

The `home` fixture starts Home Assistant from .venv on a free localhost port,
with an empty configuration folder that links this repo's integration. It
then completes onboarding, adds the integration and its people through the
same REST API the UI uses, and saves a test dashboard. The folder is deleted
afterwards, so every session starts from nothing.
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
import time
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from playwright.sync_api import Browser, Page, sync_playwright

REPO = Path(__file__).resolve().parents[2]

# Test values for the throwaway instance; it only ever listens on 127.0.0.1.
OWNER = {"name": "Test Owner", "username": "owner", "password": "test-password-e2e"}

PEOPLE = ["Matteo", "Debora"]

# The person form, as filled in for each of PEOPLE.
PERSON_FORM = {
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

    DASHBOARD = "zp-test"

    def dashboard(self, cards: list[dict[str, Any]]) -> None:
        """Show `cards` on the test dashboard, creating it the first time."""
        dashboards = self.ws({"type": "lovelace/dashboards/list"})
        if not any(d["url_path"] == self.DASHBOARD for d in dashboards):
            self.ws(
                {
                    "type": "lovelace/dashboards/create",
                    "url_path": self.DASHBOARD,
                    "title": "ZP test",
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


def _add_integration(home: Home) -> str:
    """Add ZPMyFitnessCards and each person, as the UI's dialogs would."""
    flow = home.api("POST", "/api/config/config_entries/flow", {"handler": "zp_my_fitness"})
    entry = home.api("POST", f"/api/config/config_entries/flow/{flow['flow_id']}", {})
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
            {"name": name, **PERSON_FORM},
        )
        assert done["type"] == "create_entry", done
    # Adding a person reloads the entry in the background. Wait until the
    # reloaded entry answers with everyone.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            people = home.ws({"type": "zp_my_fitness/people"})
        except AssertionError:
            people = []
        if sorted(p["name"] for p in people) == sorted(PEOPLE):
            return entry_id
        time.sleep(0.2)
    raise TimeoutError("ZPMyFitnessCards did not finish loading its people")


@pytest.fixture(scope="session")
def home() -> Iterator[Home]:
    """A brand-new, onboarded Home Assistant with the integration and two people."""
    config_dir = Path(tempfile.mkdtemp(prefix="zp-my-fitness-e2e-"))
    port = _free_port()
    (config_dir / "configuration.yaml").write_text(CONFIGURATION.format(port=port))
    (config_dir / "custom_components").mkdir()
    (config_dir / "custom_components" / "zp_my_fitness").symlink_to(
        REPO / "custom_components" / "zp_my_fitness"
    )
    home = Home(url=f"http://127.0.0.1:{port}", config_dir=config_dir)
    # --skip-pip: everything this test needs is already in .venv, and the
    # integrations that fail without their packages are not ones it uses.
    process = subprocess.Popen(
        [sys.executable, "-m", "homeassistant", "--config", str(config_dir), "--skip-pip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_up(home, process)
        _onboard(home)
        _add_integration(home)
        yield home
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(config_dir, ignore_errors=True)


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
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(home: Home, browser: Browser) -> Iterator[Page]:
    """A browser tab, logged in as the owner."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
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
