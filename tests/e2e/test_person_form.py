"""Adding a person through the person form, on a laptop and on a phone.

tests/e2e/test_android.py picks the birth date with Android's own date picker.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from .conftest import Home, logged_in_page
from .flows import people, wait_for
from .test_meals import PHONE
from .test_units import entry_id, fields

TIMEOUT = 15_000


@pytest.fixture(params=["laptop", "phone"])
def device(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def device_page(device: str, home: Home, browser: Browser) -> Iterator[Page]:
    # A British laptop, whose date fields take the day first.
    options = PHONE if device == "phone" else {"locale": "en-GB"}
    yield from logged_in_page(home, browser, **options)


def type_number(form: Page | Locator, name: str, value: str) -> None:
    # Key by key: Home Assistant's number fields ignore a value set in one go.
    field = form.get_by_role("spinbutton", name=name)
    field.click()
    field.press("Control+a")
    field.press_sequentially(value)
    field.press("Tab")


def enter_date(page: Page, field: Locator, day: str, typed: bool = True) -> None:
    """Enter `day`, as YYYY-MM-DD: typed key by key, in a British browser's order.

    A phone's date field takes no typing: it opens the system's picker, which
    only the app test can reach. Unless `typed`, it is set as that picker sets it.
    """
    if typed:
        field.focus()
        year, month, date_ = day.split("-")
        page.keyboard.type(date_ + month + year)
    else:
        field.fill(day)
    expect(field).to_have_value(day)


def open_person_form(home: Home, page: Page) -> None:
    page.goto(home.url + "/config/integrations/integration/metron")
    page.get_by_role("button", name="Add person").click()
    expect(page.get_by_role("spinbutton", name="Height*")).to_be_visible(timeout=TIMEOUT)


def fill_person(page: Page, name: str) -> None:
    """Fill in the person form, all but the birth date."""
    page.get_by_role("textbox", name="Name*").fill(name)
    type_number(page, "Height*", "168")
    type_number(page, "Starting weight*", "72")
    type_number(page, "Goal weight*", "66")


def subentry_id(home: Home, name: str) -> str | None:
    subs = home.ws({"type": "config_entries/subentries/list", "entry_id": entry_id(home)})
    return next((s["subentry_id"] for s in subs if s["title"] == name), None)


def has_sensors(home: Home, name: str) -> bool:
    weight = f"sensor.{name.lower().replace(' ', '_')}_weight"
    return any(s["entity_id"] == weight for s in home.api("GET", "/api/states"))


def remove_person(home: Home, name: str) -> None:
    """Remove `name` if they were saved, once the reload that added them is done."""
    if sub := subentry_id(home, name):
        wait_for(lambda: has_sensors(home, name))
        home.ws(
            {
                "type": "config_entries/subentries/delete",
                "entry_id": entry_id(home),
                "subentry_id": sub,
            }
        )
    wait_for(lambda: people(home) and name not in {p["name"] for p in people(home)})


def saved_person(home: Home, name: str) -> dict:
    """What `name` was saved with, as their Change person form shows it."""
    sub = wait_for(lambda: subentry_id(home, name))
    flows = "/api/config/config_entries/subentries/flow"
    menu = home.api("POST", flows, {"handler": [entry_id(home), "person"], "subentry_id": sub})
    edit = home.api("POST", f"{flows}/{menu['flow_id']}", {"next_step_id": "edit"})
    return {
        k: f["description"]["suggested_value"]
        for k, f in fields(edit).items()
        if "description" in f
    }


def test_the_birth_date_is_typed_in(home: Home, device: str, device_page: Page) -> None:
    page = device_page
    name = f"Bea e2e {device}"
    open_person_form(home, page)
    birth_date = page.locator('input[type="date"]')
    # It starts empty, not on today.
    expect(birth_date).to_have_value("")
    fill_person(page, name)
    typed = device == "laptop"
    try:
        enter_date(page, birth_date, "1896-03-15", typed)
        page.get_by_role("button", name="Submit").click()
        expect(page.get_by_text("The birth date must be within the last 120 years.")).to_be_visible(
            timeout=TIMEOUT
        )
        enter_date(page, birth_date, "1996-03-15", typed)
        page.get_by_role("button", name="Submit").click()
        saved = saved_person(home, name)
        assert (saved["birth_date"], saved["height_cm"], saved["start_weight_kg"]) == (
            "1996-03-15",
            168,
            72,
        )
    finally:
        remove_person(home, name)
