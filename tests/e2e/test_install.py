"""Installing as the README says: its "Add integration" button, then "Add person".

HACS's download is not tested here: it needs GitHub. CI's HACS check covers
what HACS reads from this repository, and tests/integration/test_readme.py
checks where the README's buttons lead.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import ExitStack

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from custom_components.fork_and_scale.db import key_for_name

from ..conftest import new_database
from ..integration.test_readme import buttons
from .conftest import CONFIGURATION, FakeSearch, Home, _home, logged_in_page
from .test_cards import TIMEOUT

# Home Assistant's "my" integration answers the links my.home-assistant.io
# sends a browser to; default_config loads it, so most installs have it.
WITH_MY = CONFIGURATION + "my:\n"


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def new_home(request: pytest.FixtureRequest, search_server: FakeSearch) -> Iterator[Home]:
    """A brand-new Home Assistant with the integration installed, but not added."""
    with ExitStack() as cleanup:
        db_url = None
        if request.param == "postgresql":
            server = request.getfixturevalue("postgres_server")
            db_url = cleanup.enter_context(new_database(server))
        yield from _home(
            db_url, configuration=WITH_MY, search_url=search_server.url, integration=False
        )


@pytest.fixture
def new_page(new_home: Home, browser: Browser) -> Iterator[Page]:
    """A browser tab on `new_home`, logged in as the owner."""
    yield from logged_in_page(new_home, browser)


def type_number(dialog: Locator, name: str, value: str) -> None:
    # Key by key: Home Assistant's number fields ignore a value set in one go.
    field = dialog.get_by_role("spinbutton", name=name)
    field.click()
    field.press("Control+a")
    field.press_sequentially(value)
    field.press("Tab")


def pick_birth_date(page: Page, dialog: Locator, years_ago: int) -> None:
    """Choose the 15th of this month, `years_ago` years back, in the date picker."""
    dialog.get_by_role("textbox", name="Birth date*").click()
    picker = page.locator("ha-dialog-date-picker")
    picker.get_by_role("button", pressed=True).focus()
    for _ in range(years_ago):
        page.keyboard.press("Shift+PageUp")
    # Day buttons are named in the browser's locale: "15 November" or "November 15".
    picker.get_by_role("button", name=re.compile(r"(^|\D)15(\D|$)")).click()
    picker.get_by_role("button", name="OK").click()


def test_installs_with_the_readme_s_button_and_shows_cards_after_a_reload(
    new_home: Home, new_page: Page
) -> None:
    page = new_page
    # Step 3's button leads, through my.home-assistant.io, to this address.
    domain = buttons()["config_flow_start"]["domain"]
    page.goto(f"{new_home.url}/_my_redirect/config_flow_start?domain={domain}")
    expect(page.get_by_text("Do you want to set up Fork & Scale?")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="OK").click()
    dialog = page.locator("dialog-data-entry-flow")
    expect(dialog.get_by_text("Choose where Fork & Scale keeps its data.")).to_be_visible(
        timeout=TIMEOUT
    )
    if new_home.db_url.startswith("postgresql"):
        dialog.get_by_role("radio", name="Postgres").check()
        dialog.get_by_role("button", name="Submit").click()
        dialog.get_by_role("textbox", name="Database URL*").fill(new_home.db_url)
    else:
        expect(dialog.get_by_role("radio", name="SQLite (recommended)")).to_be_checked()
    dialog.get_by_role("button", name="Submit").click()
    expect(dialog.get_by_text("before you add cards")).to_be_visible(timeout=TIMEOUT)
    dialog.get_by_role("button", name="Finish").click()

    # Step 4: "Add person" on the integration's page.
    page.get_by_text("Fork & Scale", exact=True).click()
    page.get_by_role("button", name="Add person").click()
    dialog.get_by_role("textbox", name="Name*").fill("Nora")
    # The form takes only a birth date in the past, so this must work for it to save.
    pick_birth_date(page, dialog, years_ago=36)
    type_number(dialog, "Height*", "168")
    type_number(dialog, "Starting weight*", "72")
    type_number(dialog, "Goal weight*", "65")
    dialog.get_by_role("radio", name="Lose 0.5 kg a week").check()
    dialog.get_by_role("button", name="Submit").click()
    dialog.get_by_role("button", name="Finish").click()

    [nora] = new_home.ws({"type": "fork_and_scale/people"})
    assert (nora["name"], nora["height_cm"], nora["start_weight_kg"], nora["goal_weight_kg"]) == (
        "Nora",
        168,
        72,
        65,
    )
    assert key_for_name(new_home.db_url, "Nora", exclude=[]) == nora["id"]
    assert float(new_home.api("GET", "/api/states/sensor.nora_weight")["state"]) == 72

    # As the success message says: reload, and the cards are there, with no
    # dashboard resource added.
    new_home.dashboard([{"type": "custom:fork-and-scale-weight-card", "person": "Nora"}])
    page.reload()
    page.locator("ha-sidebar").get_by_text("FS test").click()
    card = page.locator("fork-and-scale-weight-card")
    expect(card.locator(".chart")).to_contain_text("Goal 65 kg", timeout=30_000)
