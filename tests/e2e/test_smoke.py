"""The integration loads in a brand-new Home Assistant and its card renders."""

from playwright.sync_api import Page, expect

from .conftest import PEOPLE, Home


def test_lists_the_people_added_in_setup(home: Home) -> None:
    people = home.ws({"type": "zp_my_fitness/people"})
    assert [p["name"] for p in people] == PEOPLE


def test_the_food_diary_card_shows_its_person(home: Home, page: Page) -> None:
    home.dashboard([{"type": "custom:zp-food-diary-card", "person": "Debora"}])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    card = page.locator("zp-food-diary-card")
    expect(card.locator(".title")).to_have_text("Food diary", timeout=30_000)
    expect(card.locator(".person")).to_have_text("Debora")
    errors = [line for line in home.log().splitlines() if " ERROR " in line]
    assert not [line for line in errors if "zp_my_fitness" in line]
