"""Active calories in a browser, on a laptop and on a phone.

The flows are in active_calories.py. The units a sensor may have are tried
here too, through Add person, on a laptop.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from . import active_calories as ac
from . import flows
from .conftest import PHONE, Home, logged_in_page
from .test_cards import TIMEOUT, open_card
from .test_meals import opener
from .test_person_form import enter_date, fill_person, open_person_form, remove_person


@pytest.fixture(params=["laptop", "phone"])
def screen(request: pytest.FixtureRequest, home: Home, browser: Browser) -> Iterator[ac.Screen]:
    pages = logged_in_page(home, browser, **(PHONE if request.param == "phone" else {}))
    page = next(pages)
    s = ac.Screen(home, page, request.param, opener(home, page), flows.OpenFoodFacts())
    try:
        with s.cleanup:
            yield s
    finally:
        pages.close()


@pytest.mark.parametrize("flow", ac.FLOWS, ids=flows.flow_id)
def test_active_calories(screen: ac.Screen, flow: Callable[[ac.Screen], None]) -> None:
    flow(screen)


ENERGY_WH = {"unit_of_measurement": "Wh", "device_class": "energy"}

# The spec's units, each a sensor posted with the attributes its integration
# gives it, and what the person form says to it: None where it is accepted,
# then the diary's line starts with what was measured, in kcal.
UNITS = {
    "kcal": (ac.WATCH, 906, None),
    "kcal, energy": (ac.ENERGY_KCAL, 906, None),
    "calories": (ac.WITHINGS | {"last_reset": ac.midnight()}, 906, None),
    "kJ": (ac.ENERGY_KJ, 3790, None),
    "Wh, energy": (ENERGY_WH, 250, ac.UNIT_SETTING.format("Wh")),
    "cal": ({"unit_of_measurement": "cal"}, 412, ac.UNIT.format("cal")),
    "W": ({"unit_of_measurement": "W", "device_class": "power"}, 250, ac.UNIT.format("W")),
    "no unit": ({}, 906, ac.NO_UNIT),
    "12,000 kcal": (ac.WATCH, 12000, ac.RUNNING_TOTAL.format(12000)),
    # 10,755 kcal.
    "45,000 kJ": (ac.ENERGY_KJ, 45000, ac.RUNNING_TOTAL.format(10755)),
}


@pytest.mark.parametrize("unit", list(UNITS))
def test_active_calories_units_in_the_person_form(home: Home, page: Page, unit: str) -> None:
    attributes, state, error = UNITS[unit]
    # As Home Assistant would make it part of an entity ID.
    tag = re.sub(r"[^a-z0-9]+", "_", unit.lower())
    entity_id = f"sensor.units_{tag}_active_calories"
    name = f"Units {tag} e2e"
    friendly = f"Units {unit} active calories"
    home.api(
        "POST",
        f"/api/states/{entity_id}",
        {"state": str(state), "attributes": {"friendly_name": friendly, **attributes}},
    )
    try:
        open_person_form(home, page)
        fill_person(page, name)
        enter_date(page, page.locator('input[type="date"]'), "1996-03-15")
        dialog = page.locator("dialog-data-entry-flow")
        page.get_by_text("Active calories", exact=True).click()
        dialog.get_by_label("Allow active calories").click()
        dialog.locator('ha-picker-field[aria-label="Sensor (optional)"]').click()
        dialog.locator("ha-picker-combo-box ha-input-search input").fill(friendly)
        dialog.locator("ha-picker-combo-box ha-combo-box-item", has_text=friendly).click()
        dialog.get_by_role("button", name="Submit").click()
        if error:
            ac.expect_refused(dialog, error)
            return
        card = open_card(home, page, {"type": "custom:metron-food-diary-card", "person": name})
        line = card.locator(".body > .activity")
        expect(line).to_contain_text(f"{friendly} measured 906 kcal.", timeout=TIMEOUT)
    finally:
        remove_person(home, name)
        home.api("DELETE", f"/api/states/{entity_id}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The diary names the sensor from the states it had when it last drew, and draws again "
        "only when Metron's data changes (src/cards/person-card.js, ShowsPerson's set hass), "
        "so a renamed sensor keeps its old name until its next reading"
    ),
)
def test_the_line_follows_a_renamed_sensor(home: Home, page: Page) -> None:
    s = ac.Screen(home, page, "laptop", opener(home, page), flows.OpenFoodFacts())
    with s.cleanup:
        watch = ac.sensor(s, "Garmin Active calories rename", ac.WATCH, 500)
        anna = ac.add_person(s, ac.ANNA, "rename", enabled=True, sensor=watch)
        diary, _summary = ac.open_cards(s, anna)
        line = diary.locator(".body > .activity")
        expect(line).to_contain_text(f"{watch.name} measured 500 kcal.", timeout=TIMEOUT)
        # The same reading, under the name given in the sensor's settings.
        watch.name = "Anna's rename watch"
        watch.post(500)
        page.wait_for_function(
            "([id, name]) => document.querySelector('home-assistant').hass.states[id]"
            "?.attributes.friendly_name === name",
            arg=[watch.entity_id, watch.name],
        )
        expect(line).to_contain_text(f"{watch.name} measured 500 kcal.", timeout=5_000)
