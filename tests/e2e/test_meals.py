"""Saved meals and one Scan in a browser, on a laptop and on a phone.

The flows are in flows.py; tests/e2e/test_android.py runs them in the app.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from . import flows
from .conftest import FakeSearch, Home, logged_in_page

# A phone's window: small, touched, and laid out as the frontend lays out
# phones.
PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
}


@pytest.fixture(params=["laptop", "phone"])
def screen(
    request: pytest.FixtureRequest, home: Home, browser: Browser, search: FakeSearch
) -> Iterator[flows.Screen]:
    pages = logged_in_page(home, browser, **(PHONE if request.param == "phone" else {}))
    page = next(pages)
    off = flows.OpenFoodFacts()
    flows.install(page, off)
    try:
        yield flows.Screen(home, page, request.param, opener(home, page), off, search)
    finally:
        off.release()
        pages.close()


def opener(home: Home, page: Page) -> Callable[[dict], Locator]:
    def open_card(card: dict) -> Locator:
        home.dashboard([card])
        page.goto(home.url + "/" + home.DASHBOARD + "/0")
        element = page.locator(card["type"].removeprefix("custom:"))
        expect(element.locator(".title").first).to_be_visible(timeout=30_000)
        return element

    return open_card


@pytest.mark.parametrize("flow", flows.FLOWS, ids=flows.flow_id)
def test_saved_meals_and_scanning(screen: flows.Screen, flow: Callable) -> None:
    flow(screen)
