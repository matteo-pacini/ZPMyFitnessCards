"""The actions, called as an automation would, and as a person would in the action editor."""

from __future__ import annotations

import json
import time
import urllib.error
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from .conftest import Home
from .test_cards import TIMEOUT, diary, meal, open_card, person_id, save_food, today


def device_id(home: Home, name: str) -> str:
    key = person_id(home, name)
    devices = home.ws({"type": "config/device_registry/list"})
    return next(d["id"] for d in devices if ["zp_my_fitness", key] in d["identifiers"])


def act(home: Home, action: str, person: str, **data: Any) -> Any:
    """Call an action through the REST API; return get_day's response."""
    path = f"/api/services/zp_my_fitness/{action}"
    if action == "get_day":
        path += "?return_response"
    reply = home.api("POST", path, {"device_id": device_id(home, person), **data})
    return reply["service_response"] if action == "get_day" else reply


def refused(home: Home, action: str, person: str, **data: Any) -> str:
    """The message of the error an action answers with."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        act(home, action, person, **data)
    assert caught.value.code == 400
    return json.loads(caught.value.read())["message"]


def test_logged_food_shows_in_an_open_diary(home: Home, page: Page) -> None:
    save_food(home, "Action oats e2e")
    card = diary(home, page, "Debora")

    act(home, "log_food", "Debora", meal="breakfast", food="action OATS e2e", grams=60)
    act(home, "log_food", "Debora", meal="snacks", name="Action pizza e2e", kcal=900)

    oats = meal(card, "breakfast").locator(".row", has_text="Action oats e2e")
    expect(oats).to_contain_text("60 g", timeout=TIMEOUT)
    expect(oats).to_contain_text("233")
    expect(meal(card, "snacks").locator(".row", has_text="Action pizza e2e")).to_contain_text(
        "900", timeout=TIMEOUT
    )


def test_a_logged_weight_shows_in_the_weight_card(home: Home, page: Page) -> None:
    day = (date.fromisoformat(today()) - timedelta(days=3)).isoformat()
    card = open_card(home, page, {"type": "custom:zp-weight-card", "person": "Debora"})
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)

    act(home, "log_weight", "Debora", weight="67.7", day=day)

    expect(card.locator(".recent .item", has_text="67.7 kg")).to_have_count(1, timeout=TIMEOUT)
    debora = person_id(home, "Debora")
    home.ws({"type": "zp_my_fitness/weight/delete", "person": debora, "day": day})


def test_get_day_returns_the_day(home: Home) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    quick_add = {"name": "Action stew e2e", "kcal": 321.04}
    act(home, "log_food", "Matteo", meal="lunch", day=yesterday, **quick_add)

    day = act(home, "get_day", "Matteo", day=yesterday)

    assert day["person"] == "Matteo"
    assert day["day"] == yesterday
    stew = next(e for e in day["meals"]["lunch"]["entries"] if e["name"] == "Action stew e2e")
    assert stew["kcal"] == 321.0
    assert day["totals"]["kcal"] >= 321.0
    assert set(day["meals"]) == {"breakfast", "lunch", "dinner", "snacks"}


def test_errors_are_explained(home: Home) -> None:
    message = refused(home, "log_food", "Debora", meal="lunch", food="Nothing e2e", grams=10)
    assert message == "There is no saved food called Nothing e2e"
    tomorrow = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
    message = refused(home, "log_weight", "Debora", weight=68, day=tomorrow)
    assert message == f"{tomorrow} is in the future"


# In the action editor, where its fields, person picker and response show.


def open_action(home: Home, page: Page, name: str, action: str, person: str) -> None:
    page.goto(home.url + "/config/tools/action")
    page.get_by_text("Action", exact=True).first.click()
    page.get_by_placeholder("Search").fill(name)
    page.get_by_text(f"zp_my_fitness.{action}", exact=True).click()
    page.get_by_text("Select a device").click()
    # Only the people are offered.
    expect(page.get_by_text("ZPMyFitnessCards", exact=True)).to_have_count(2)
    page.get_by_text(person, exact=True).click()


def fill(page: Page, label: str, value: str, *, optional: bool = False) -> None:
    """Type into an action's field, ticking it first if it is optional."""
    row = page.locator("ha-settings-row").filter(has=page.get_by_text(label, exact=True))
    if optional:
        row.locator("ha-checkbox").click()
    row.locator("#input").click()
    # Typed, because the editor ignores a value set without key presses; and
    # over what is there, since ticking a number field fills in 0.
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type(value)


def wait_for(check: Callable[[], Any], seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while not (result := check()):
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.2)
    return result


def test_the_action_editor_logs_a_weight(home: Home, page: Page) -> None:
    open_action(home, page, "Log weight", "log_weight", "Debora")
    expect(page.get_by_text("In kg, from 20 to 400.")).to_be_visible()
    fill(page, "Weight", "66.6")
    page.get_by_role("button", name="Perform action").click()

    debora = person_id(home, "Debora")
    weights = {"type": "zp_my_fitness/weights", "person": debora}
    wait_for(lambda: {"day": today(), "kg": 66.6} in home.ws(weights))
    home.ws({"type": "zp_my_fitness/weight/delete", "person": debora, "day": today()})


def test_the_action_editor_quick_adds_food(home: Home, page: Page) -> None:
    open_action(home, page, "Log food", "log_food", "Matteo")
    page.get_by_role("radio", name="Dinner").check()
    fill(page, "Name", "Editor pizza e2e", optional=True)
    fill(page, "kcal", "700", optional=True)
    page.get_by_role("button", name="Perform action").click()

    day = {"type": "zp_my_fitness/day", "person": person_id(home, "Matteo"), "day": today()}
    entries = wait_for(
        lambda: [e for e in home.ws(day)["entries"] if e["name"] == "Editor pizza e2e"]
    )
    assert (entries[0]["meal"], entries[0]["kcal"]) == ("dinner", 700)


def test_the_action_editor_shows_a_day(home: Home, page: Page) -> None:
    open_action(home, page, "Get day", "get_day", "Matteo")
    page.get_by_role("button", name="Perform action").click()
    response = page.locator(".cm-content")
    expect(response).to_contain_text("person: Matteo", timeout=TIMEOUT)
    expect(response).to_contain_text(f"day: '{today()}'")
    expect(response).to_contain_text("breakfast:")
