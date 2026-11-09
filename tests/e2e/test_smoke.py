"""The integration in a brand-new Home Assistant: sensors, websocket and a card."""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, expect

from .conftest import PEOPLE, Home


def person_id(home: Home, name: str) -> str:
    return next(p["id"] for p in home.ws({"type": "zp_my_fitness/people"}) if p["name"] == name)


def state(home: Home, entity_id: str) -> float:
    return float(home.api("GET", f"/api/states/{entity_id}")["state"])


def eventually(home: Home, entity_id: str, value: float, seconds: float = 10) -> dict:
    """The entity's state once it equals `value`. Sensors refresh just after a write."""
    deadline = time.monotonic() + seconds
    while True:
        state = home.api("GET", f"/api/states/{entity_id}")
        if float(state["state"]) == value or time.monotonic() > deadline:
            assert float(state["state"]) == value, state
            return state
        time.sleep(0.1)


def test_lists_the_people_added_in_setup(home: Home) -> None:
    people = home.ws({"type": "zp_my_fitness/people"})
    assert [p["name"] for p in people] == PEOPLE


def test_logging_food_and_weight_updates_the_sensors(home: Home) -> None:
    matteo = person_id(home, "Matteo")
    # The test home is in London.
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    oats = home.ws(
        {
            "type": "zp_my_fitness/food/add",
            "name": "Porridge oats",
            "kcal": 389,
            "protein": 16.9,
            "carbs": 66,
            "fat": 6.9,
        }
    )
    # Other tests log food for Matteo too, so compare with what was there.
    calories = state(home, "sensor.matteo_calories_today")
    breakfast = state(home, "sensor.matteo_breakfast_calories")
    debora = state(home, "sensor.debora_calories_today")
    home.ws(
        {
            "type": "zp_my_fitness/entry/add",
            "person": matteo,
            "day": today,
            "meal": "breakfast",
            "food_id": oats["id"],
            "grams": 100,
        }
    )
    home.ws({"type": "zp_my_fitness/weight/set", "person": matteo, "day": today, "kg": 68.5})

    assert eventually(home, "sensor.matteo_calories_today", calories + 389)
    assert eventually(home, "sensor.matteo_breakfast_calories", breakfast + 389)
    weight = eventually(home, "sensor.matteo_weight", 68.5)
    assert weight["attributes"]["overweight_from_kg"] == 81.0
    assert state(home, "sensor.debora_calories_today") == debora


def test_the_food_diary_card_shows_its_person(home: Home, page: Page) -> None:
    home.dashboard([{"type": "custom:zp-food-diary-card", "person": "Debora"}])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    card = page.locator("zp-food-diary-card")
    expect(card.locator(".title")).to_have_text("Food diary", timeout=30_000)
    expect(card.locator(".person")).to_have_text("Debora")
    errors = [line for line in home.log().splitlines() if " ERROR " in line]
    assert not [line for line in errors if "zp_my_fitness" in line]
