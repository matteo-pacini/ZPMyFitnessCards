"""The integration in a brand-new Home Assistant: sensors, websocket and a card."""

from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, expect

from .conftest import PEOPLE, Home


def person_id(home: Home, name: str) -> str:
    return next(p["id"] for p in home.ws({"type": "zp_my_fitness/people"}) if p["name"] == name)


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

    assert float(home.api("GET", "/api/states/sensor.matteo_calories_today")["state"]) == 389
    assert float(home.api("GET", "/api/states/sensor.matteo_breakfast_calories")["state"]) == 389
    weight = home.api("GET", "/api/states/sensor.matteo_weight")
    assert float(weight["state"]) == 68.5
    assert weight["attributes"]["overweight_from_kg"] == 68.1
    assert float(home.api("GET", "/api/states/sensor.debora_calories_today")["state"]) == 0


def test_the_food_diary_card_shows_its_person(home: Home, page: Page) -> None:
    home.dashboard([{"type": "custom:zp-food-diary-card", "person": "Debora"}])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    card = page.locator("zp-food-diary-card")
    expect(card.locator(".title")).to_have_text("Food diary", timeout=30_000)
    expect(card.locator(".person")).to_have_text("Debora")
    errors = [line for line in home.log().splitlines() if " ERROR " in line]
    assert not [line for line in errors if "zp_my_fitness" in line]
