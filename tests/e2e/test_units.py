"""Weights in lb and heights in feet and inches, on a US customary install."""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from .conftest import Home
from .test_actions import act, refused, wait_for
from .test_cards import TIMEOUT, open_card, person_id, today


def weights(home: Home, name: str) -> list[dict[str, Any]]:
    return home.ws({"type": "zp_my_fitness/weights", "person": person_id(home, name)})


@pytest.mark.usefixtures("us_customary")
def test_the_weight_card_logs_shows_and_deletes_in_lb(home: Home, page: Page) -> None:
    day = (date.fromisoformat(today()) - timedelta(days=2)).isoformat()
    card = open_card(home, page, {"type": "custom:zp-weight-card", "person": "Debora"})
    # 62 kg.
    expect(card.locator(".chart")).to_contain_text("Goal 136.7 lb", timeout=TIMEOUT)
    expect(card.locator(".now")).to_contain_text(" lb")
    expect(card.locator(".log")).to_contain_text("lb")

    card.locator('[data-field="day"]').fill(day)
    card.locator('[data-field="weight"]').fill("152.4")
    card.locator('[data-action="log"]').click()
    item = card.locator(".recent .item", has_text="152.4 lb")
    expect(item).to_have_count(1, timeout=TIMEOUT)
    assert {"day": day, "kg": 69.13} in weights(home, "Debora")

    card.locator('[data-field="weight"]').fill("44")
    card.locator('[data-action="log"]').click()
    expect(card.locator(".error")).to_have_text("Enter a weight from 44.1 to 881.8 lb.")

    item.locator('[data-action="delete-weight"]').click()
    expect(card.locator(".recent .item", has_text="152.4 lb")).to_have_count(0, timeout=TIMEOUT)
    assert day not in {w["day"] for w in weights(home, "Debora")}


def test_open_cards_follow_a_change_of_unit_system(home: Home, page: Page) -> None:
    card = open_card(home, page, {"type": "custom:zp-summary-card", "person": "Debora"})
    weight = card.locator(".weight b")
    expect(weight).to_have_text(re.compile(r" kg$"), timeout=TIMEOUT)
    with home.us_customary():
        expect(weight).to_have_text(re.compile(r" lb$"), timeout=TIMEOUT)
    expect(weight).to_have_text(re.compile(r" kg$"), timeout=TIMEOUT)


@pytest.mark.usefixtures("us_customary")
def test_the_actions_weigh_in_lb(home: Home) -> None:
    day = (date.fromisoformat(today()) - timedelta(days=4)).isoformat()
    try:
        act(home, "log_weight", "Debora", weight=150, day=day)
        assert {"day": day, "kg": 68.04} in weights(home, "Debora")
        got = act(home, "get_day", "Debora", day=day)
        assert (got["weight"], got["weight_unit"], got["weight_kg"]) == (150, "lb", 68.04)

        act(home, "log_weight", "Debora", weight=69.5, unit="kg", day=day)
        assert {"day": day, "kg": 69.5} in weights(home, "Debora")

        message = refused(home, "log_weight", "Debora", weight=40, day=day)
        assert message == "Give a weight from 44.1 to 881.8 lb"
    finally:
        debora = person_id(home, "Debora")
        home.ws({"type": "zp_my_fitness/weight/delete", "person": debora, "day": day})


# The person form, in lb, feet and inches.

NAME = "Imperial e2e"


def entry_id(home: Home) -> str:
    [entry] = home.api("GET", "/api/config/config_entries/entry?domain=zp_my_fitness")
    return entry["entry_id"]


def fields(step: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in step["data_schema"]}


def person(home: Home, name: str) -> dict[str, Any]:
    """The person called `name`, once the integration has reloaded with them."""

    def find() -> dict[str, Any] | None:
        try:
            people = home.ws({"type": "zp_my_fitness/people"})
        except AssertionError:
            return None
        return next((p for p in people if p["name"] == name), None)

    return wait_for(find, seconds=30)


@pytest.mark.usefixtures("us_customary")
def test_adds_and_changes_a_person_in_lb_feet_and_inches(home: Home) -> None:
    flows = "/api/config/config_entries/subentries/flow"
    form = home.api("POST", flows, {"handler": [entry_id(home), "person"]})
    asked = fields(form)
    assert "height_cm" not in asked
    assert "start_weight_kg" not in asked
    assert asked["start_weight_lb"]["selector"]["number"]["unit_of_measurement"] == "lb"
    assert asked["height_ft"]["selector"]["number"]["unit_of_measurement"] == "ft"
    assert asked["height_in"]["selector"]["number"]["unit_of_measurement"] == "in"
    assert asked["pace"]["selector"]["select"]["options"] == [
        "lose_1_5_lb",
        "lose_1_lb",
        "lose_0_5_lb",
        "maintain",
    ]
    details = {
        "sex": "male",
        "birth_date": "1988-02-20",
        "height_ft": 5,
        "height_in": 9,
        "start_weight_lb": 200,
        "start_date": today(),
        "goal_weight_lb": 180,
        "activity": "light",
        "pace": "lose_1_lb",
        "protein_pct": 25,
        "carbs_pct": 45,
        "fat_pct": 30,
    }
    done = home.api("POST", f"{flows}/{form['flow_id']}", {"name": NAME, **details})
    assert done["type"] == "create_entry", done
    subentry = next(
        s["subentry_id"]
        for s in home.ws({"type": "config_entries/subentries/list", "entry_id": entry_id(home)})
        if s["title"] == NAME
    )
    try:
        added = person(home, NAME)
        assert (added["height_cm"], added["start_weight_kg"], added["goal_weight_kg"]) == (
            175.26,
            90.72,
            81.65,
        )

        menu = home.api(
            "POST", flows, {"handler": [entry_id(home), "person"], "subentry_id": subentry}
        )
        edit = home.api("POST", f"{flows}/{menu['flow_id']}", {"next_step_id": "edit"})
        shown = {
            name: f["description"]["suggested_value"]
            for name, f in fields(edit).items()
            if "description" in f
        }
        assert {k: shown[k] for k in ("height_ft", "height_in")} == {"height_ft": 5, "height_in": 9}
        assert (shown["start_weight_lb"], shown["goal_weight_lb"]) == (200, 180)
        done = home.api("POST", f"{flows}/{edit['flow_id']}", {**shown, "goal_weight_lb": 175.5})
        assert done["reason"] == "reconfigure_successful", done
        deadline = time.monotonic() + 30
        while (changed := person(home, NAME))["goal_weight_kg"] != 79.61:
            assert time.monotonic() < deadline, changed
            time.sleep(0.2)
        # Unchanged values keep what was stored.
        assert (changed["height_cm"], changed["start_weight_kg"]) == (175.26, 90.72)
    finally:
        home.ws(
            {
                "type": "config_entries/subentries/delete",
                "entry_id": entry_id(home),
                "subentry_id": subentry,
            }
        )


@pytest.mark.usefixtures("us_customary")
def test_the_person_form_shows_lb_feet_and_inches(home: Home, page: Page) -> None:
    page.goto(home.url + "/config/integrations/integration/zp_my_fitness")
    page.get_by_role("button", name="Add person").click()
    # The dialog's form is slotted into it, so look for its fields on the page.
    for field in ("Height (ft)*", "Height (in)*", "Starting weight*", "Goal weight*"):
        expect(page.get_by_role("spinbutton", name=field)).to_be_visible(timeout=TIMEOUT)
    expect(page.get_by_role("spinbutton", name="Height*")).to_have_count(0)
    expect(page.get_by_role("radio", name="Lose 1 lb a week")).to_be_visible()
    expect(page.get_by_role("radio", name="Lose 0.5 kg a week")).to_have_count(0)
    # The unit beside each weight.
    expect(page.get_by_text("lb", exact=True)).to_have_count(2)
