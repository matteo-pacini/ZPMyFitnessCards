"""A Home Assistant that starts on a database an older release left, and upgrades it.

Each test here shares one Home Assistant per database engine, separate from
the other tests' `home`, since it starts from a version 1 database with the
sample's data on today's date. Every test leaves it loaded and upgraded.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from ..conftest import new_database
from ..schemas import (
    LATEST,
    add_version_1_sample,
    contents,
    database_at,
    empty_database,
    failing_version_bumps,
    layout,
    set_version,
    version,
)
from .conftest import FakeSearch, Home, _home, logged_in_page
from .test_cards import TIMEOUT, diary, meal, open_card, today
from .test_import_export import day, summary, upload


def old_database(url: str) -> None:
    """Leave a version 1 database at `url`, with the sample's data on today's date."""
    database_at(url, 1)
    add_version_1_sample(url, today())


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def old_home(request: pytest.FixtureRequest, search_server: FakeSearch) -> Iterator[Home]:
    """A brand-new Home Assistant whose integration starts on a version 1 database.

    Its people are added one right after the other, under the names the
    database knows, so the second is added while the first's reload runs.
    Each gets their data back all the same.
    """
    with ExitStack() as cleanup:
        db_url = None
        if request.param == "postgresql":
            server = request.getfixturevalue("postgres_server")
            db_url = cleanup.enter_context(new_database(server))
        yield from _home(db_url, search_url=search_server.url, database=old_database)


@pytest.fixture
def old_page(old_home: Home, browser: Browser) -> Iterator[Page]:
    """A browser tab on `old_home`, logged in as the owner."""
    yield from logged_in_page(old_home, browser)


def config_entry(home: Home) -> dict[str, Any]:
    [entry] = home.ws({"type": "config_entries/get", "domain": "zp_my_fitness"})
    return entry


def wait_for_state(home: Home, state: str, seconds: float = 60) -> dict[str, Any]:
    """Wait until the integration's entry is in `state`; return the entry."""
    deadline = time.monotonic() + seconds
    while (entry := config_entry(home))["state"] != state:
        assert time.monotonic() < deadline, entry
        time.sleep(0.2)
    return entry


def reload(home: Home) -> None:
    home.api("POST", f"/api/config/config_entries/entry/{config_entry(home)['entry_id']}/reload")


def set_disabled(home: Home, disabled: bool) -> None:
    home.ws(
        {
            "type": "config_entries/disable",
            "entry_id": config_entry(home)["entry_id"],
            "disabled_by": "user" if disabled else None,
        }
    )


NUTRITION_HEADER = (
    "Date,Meal,Calories,Fat (g),Saturated Fat,Polyunsaturated Fat,Monounsaturated Fat,"
    "Trans Fat,Cholesterol,Sodium (mg),Potassium,Carbohydrates (g),Fiber,Sugar,Protein (g),"
    "Vitamin A,Vitamin C,Calcium,Iron,Note"
)


def nutrition_csv(folder: Path, kcal: int) -> Path:
    """A MyFitnessPal Nutrition-Summary with one breakfast today, of `kcal`."""
    path = folder / "Nutrition-Summary-upgraded.csv"
    path.write_text(f"{NUTRITION_HEADER}\n{today()},Breakfast,{kcal}{',0' * 16},\n")
    return path


OLD_ENTRIES = [("breakfast", "Old porridge oats", 155.6), ("dinner", "Old quick add", 640)]


def test_upgrades_the_old_database_and_the_cards_show_its_data(
    old_home: Home, old_page: Page
) -> None:
    assert version(old_home.db_url) == LATEST
    assert "source" in layout(old_home.db_url)["entries"]
    assert config_entry(old_home)["state"] == "loaded"
    assert day(old_home, "Matteo", today()) == OLD_ENTRIES
    assert day(old_home, "Debora", today()) == OLD_ENTRIES

    card = diary(old_home, old_page, "Matteo")
    expect(meal(card, "breakfast")).to_contain_text("Old porridge oats", timeout=TIMEOUT)
    expect(meal(card, "dinner")).to_contain_text("Old quick add")

    card = open_card(old_home, old_page, {"type": "custom:zp-weight-card", "person": "Debora"})
    expect(card.locator(".recent .item", has_text="80.1 kg")).to_have_count(1, timeout=TIMEOUT)
    expect(card.locator(".recent .item", has_text="80.5 kg")).to_have_count(1)

    card = open_card(old_home, old_page, {"type": "custom:zp-foods-card"})
    expect(card).to_contain_text("Old porridge oats", timeout=TIMEOUT)


def test_entries_from_before_the_upgrade_survive_myfitnesspal_imports(
    old_home: Home, old_page: Page, tmp_path: Path
) -> None:
    for kcal in (300, 350):
        dialog = upload(old_home, old_page, "Matteo", nutrition_csv(tmp_path, kcal))
        summary(dialog, days=1, entries=1, added=0, skipped=0)
        # The second import replaces the first one's entry, and only that.
        assert day(old_home, "Matteo", today()) == [
            *OLD_ENTRIES,
            ("breakfast", "MyFitnessPal", kcal),
        ]
    assert day(old_home, "Debora", today()) == OLD_ENTRIES


def test_a_failed_upgrade_leaves_the_database_as_it_was_and_a_reload_finishes_it(
    old_home: Home, old_page: Page
) -> None:
    url = old_home.db_url
    set_disabled(old_home, True)
    try:
        wait_for_state(old_home, "not_loaded")
        empty_database(url)
        old_database(url)
        before = layout(url), contents(url)
        with failing_version_bumps(url):
            set_disabled(old_home, False)
            wait_for_state(old_home, "setup_error")
            assert (layout(url), contents(url)) == before
            assert version(url) == 1

            old_page.goto(old_home.url + "/config/integrations/integration/zp_my_fitness")
            expect(old_page.get_by_text("Failed to set up").first).to_be_visible(timeout=TIMEOUT)
    finally:
        if config_entry(old_home)["disabled_by"]:
            set_disabled(old_home, False)
        reload(old_home)
        wait_for_state(old_home, "loaded")
    assert version(url) == LATEST
    assert day(old_home, "Matteo", today()) == OLD_ENTRIES
    card = diary(old_home, old_page, "Matteo")
    expect(meal(card, "dinner")).to_contain_text("Old quick add", timeout=TIMEOUT)


def test_refuses_a_database_a_newer_release_upgraded_and_says_why(
    old_home: Home, old_page: Page
) -> None:
    url = old_home.db_url
    set_version(url, LATEST + 1)
    try:
        before = layout(url), contents(url)
        reload(old_home)
        entry = wait_for_state(old_home, "setup_error")
        message = (
            f"A newer release of ZPMyFitnessCards upgraded this database to version {LATEST + 1}."
            f" This release knows up to version {LATEST}, so it left the database as it is."
            " Update ZPMyFitnessCards to use it again"
        )
        assert entry["reason"] == message
        assert entry["error_reason_translation_key"] == "newer_database"
        assert (layout(url), contents(url)) == before

        old_page.goto(old_home.url + "/config/integrations/integration/zp_my_fitness")
        expect(old_page.get_by_text(f"Failed to set up: {message}")).to_be_visible(timeout=TIMEOUT)

        card = open_card(
            old_home, old_page, {"type": "custom:zp-food-diary-card", "person": "Matteo"}
        )
        expect(card.locator(".muted")).to_have_text("Loading…", timeout=TIMEOUT)
    finally:
        set_version(url, LATEST)
        reload(old_home)
        wait_for_state(old_home, "loaded")
    # The card kept trying, and shows the day once the database loads again.
    expect(meal(card, "dinner")).to_contain_text("Old quick add", timeout=TIMEOUT)
