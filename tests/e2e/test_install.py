"""Installing as the README says: its "Add integration" button, then "Add person".

HACS's download is not tested here: it needs GitHub. CI's HACS check covers
what HACS reads from this repository, and tests/integration/test_readme.py
checks where the README's buttons lead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest
from playwright.sync_api import Browser, Page, expect

from custom_components.metron.db import key_for_name

from ..conftest import new_database
from ..integration.test_readme import buttons
from .conftest import CONFIGURATION, FakeSearch, Home, _home, logged_in_page
from .test_cards import TIMEOUT
from .test_person_form import enter_date, type_number
from .test_units import person

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
    """A browser tab on `new_home`, logged in as the owner, in a British browser."""
    yield from logged_in_page(new_home, browser, locale="en-GB")


def test_installs_with_the_readme_s_button_and_shows_cards_after_a_reload(
    new_home: Home, new_page: Page
) -> None:
    page = new_page
    # Step 3's button leads, through my.home-assistant.io, to this address.
    domain = buttons()["config_flow_start"]["domain"]
    page.goto(f"{new_home.url}/_my_redirect/config_flow_start?domain={domain}")
    expect(page.get_by_text("Do you want to set up Metron?")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="OK").click()
    dialog = page.locator("dialog-data-entry-flow")
    expect(dialog.get_by_text("Choose where Metron keeps its data.")).to_be_visible(timeout=TIMEOUT)
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
    page.get_by_text("Metron", exact=True).click()
    page.get_by_role("button", name="Add person").click()
    dialog.get_by_role("textbox", name="Name*").fill("Nora")
    # The form takes only a birth date in the past, so this must work for it to save.
    enter_date(page, dialog.locator('input[type="date"]'), "1990-03-15")
    type_number(dialog, "Height*", "168")
    type_number(dialog, "Starting weight*", "72")
    type_number(dialog, "Goal weight*", "65")
    dialog.get_by_role("radio", name="Lose 0.5 kg a week").check()
    dialog.get_by_role("button", name="Submit").click()
    dialog.get_by_role("button", name="Finish").click()

    # Adding a person reloads the integration in the background.
    nora = person(new_home, "Nora")
    assert [p["name"] for p in new_home.ws({"type": "metron/people"})] == ["Nora"]
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
    new_home.dashboard([{"type": "custom:metron-weight-card", "person": "Nora"}])
    page.reload()
    page.locator("ha-sidebar").get_by_text("Food", exact=True).click()
    card = page.locator("metron-weight-card")
    expect(card.locator(".chart")).to_contain_text("Goal 65 kg", timeout=30_000)
