"""The cards' visual editor, reached as a person would: edit the dashboard, then Add card."""

from __future__ import annotations

import re
from datetime import date, timedelta

from playwright.sync_api import Locator, Page, expect

from .conftest import Home
from .test_cards import TIMEOUT, person_id, save_food, today

EDITOR = "fork-and-scale-card-editor"


def edit_dashboard(home: Home, page: Page, cards: list[dict]) -> None:
    home.dashboard(cards)
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    page.get_by_role("button", name="Edit dashboard").click()


def pick_card(home: Home, page: Page, name: str) -> Locator:
    """Start adding the card called `name` to an empty dashboard; return its editor's dialog."""
    edit_dashboard(home, page, [])
    page.get_by_role("button", name="Add card").click()
    page.get_by_role("tab", name="By card").click()
    page.get_by_placeholder("Search cards").fill(name)
    # Each result lies under an overlay, which takes the click.
    page.locator("hui-card-picker .card").filter(has=page.get_by_text(name, exact=True)).click()
    dialog = page.locator("hui-dialog-edit-card")
    expect(dialog.locator(f"{EDITOR} ha-form")).to_be_visible(timeout=TIMEOUT)
    return dialog


def choose(dialog: Locator, field: str, choice: str) -> None:
    dialog.get_by_label(field).click()
    dialog.get_by_role("menuitem", name=choice, exact=True).click()


def save(page: Page, dialog: Locator, element: str) -> Locator:
    """Save the card in the editor, and return it on the dashboard."""
    dialog.get_by_role("button", name="Save", exact=True).click()
    card = page.locator("hui-masonry-view").locator(element)
    expect(card.locator(".title").first).to_be_visible(timeout=TIMEOUT)
    return card


def saved_cards(home: Home) -> list[dict]:
    return home.ws({"type": "lovelace/config", "url_path": home.DASHBOARD})["views"][0]["cards"]


def log(home: Home, person: str, day: str, name: str, kcal: float = 210) -> None:
    home.ws(
        {
            "type": "fork_and_scale/entry/add",
            "person": person_id(home, person),
            "day": day,
            "meal": "lunch",
            "name": name,
            "kcal": kcal,
        }
    )


def add_with_person(home: Home, page: Page, name: str, element: str) -> Locator:
    """Add the card called `name`, choosing Debora in its editor; return it on the dashboard."""
    dialog = pick_card(home, page, name)
    choose(dialog, "Person", "Debora")
    expect(dialog.locator(f"{element} .person")).to_have_text("Debora", timeout=TIMEOUT)
    card = save(page, dialog, element)
    expect(card.locator(".person")).to_have_text("Debora", timeout=TIMEOUT)
    assert saved_cards(home) == [{"type": f"custom:{element}", "person": "Debora"}]
    return card


def test_adds_a_food_diary_from_the_card_picker(home: Home, page: Page) -> None:
    log(home, "Debora", today(), "Picked soup e2e")
    card = add_with_person(home, page, "Food diary", "fork-and-scale-food-diary-card")
    expect(card.locator(".row", has_text="Picked soup e2e")).to_have_count(1, timeout=TIMEOUT)


def test_adds_a_saved_foods_card_from_the_card_picker(home: Home, page: Page) -> None:
    save_food(home, "Picked oats e2e")
    dialog = pick_card(home, page, "Saved foods")
    expect(dialog.get_by_role("textbox", name="Title")).to_be_visible()
    expect(dialog.get_by_label("Person")).to_have_count(0)
    card = save(page, dialog, "fork-and-scale-foods-card")
    expect(card.locator(".list")).to_contain_text("Picked oats e2e", timeout=TIMEOUT)
    assert saved_cards(home) == [{"type": "custom:fork-and-scale-foods-card"}]


def test_adds_a_weight_card_from_the_card_picker(home: Home, page: Page) -> None:
    card = add_with_person(home, page, "Weight", "fork-and-scale-weight-card")
    # Debora's goal; Matteo's is 82 kg.
    expect(card.locator(".chart")).to_contain_text("Goal 62 kg", timeout=TIMEOUT)


def test_adds_a_trends_card_from_the_card_picker(home: Home, page: Page) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    log(home, "Debora", yesterday, "Picked eggs e2e")
    card = add_with_person(home, page, "Trends", "fork-and-scale-trends-card")
    expect(card.locator(f'.bar[data-day="{yesterday}"]')).not_to_have_class(
        re.compile(r"\bempty\b"), timeout=TIMEOUT
    )


def test_adds_a_summary_card_that_opens_a_page_from_the_card_picker(home: Home, page: Page) -> None:
    log(home, "Debora", today(), "Picked salad e2e")
    debora = person_id(home, "Debora")
    day = home.ws({"type": "fork_and_scale/day", "person": debora, "day": today()})
    eaten = sum(e["kcal"] for e in day["entries"])
    dialog = pick_card(home, page, "Fitness summary")
    choose(dialog, "Person", "Debora")
    dialog.locator("ha-selector-navigation").click()
    dialog.locator("ha-combo-box-item", has_text="Settings").click()
    card = save(page, dialog, "fork-and-scale-summary-card")
    expect(card.locator(".body")).to_contain_text(f"{round(eaten):,} of", timeout=TIMEOUT)
    assert saved_cards(home) == [
        {
            "type": "custom:fork-and-scale-summary-card",
            "person": "Debora",
            "navigation_path": "/config",
        }
    ]


def test_the_language_dropdown_sets_the_card_s_language(home: Home, page: Page) -> None:
    element = "fork-and-scale-food-diary-card"
    dialog = pick_card(home, page, "Food diary")
    choose(dialog, "Person", "Debora")
    choose(dialog, "Language", "Italiano")
    expect(dialog.locator(f"{element} .title")).to_have_text("Diario alimentare", timeout=TIMEOUT)
    card = save(page, dialog, element)
    expect(card.locator('.meal[data-meal="breakfast"] .mealhead')).to_contain_text(
        "Colazione", timeout=TIMEOUT
    )
    assert saved_cards(home) == [{"type": f"custom:{element}", "person": "Debora", "locale": "it"}]

    # Home Assistant's language, which is English here, takes the option out.
    page.locator("hui-card-options").get_by_role("button", name="Edit").click()
    choose(dialog, "Language", "Home Assistant's language")
    card = save(page, dialog, element)
    expect(card.locator(".title")).to_have_text("Food diary", timeout=TIMEOUT)
    assert saved_cards(home) == [{"type": f"custom:{element}", "person": "Debora"}]


def test_a_config_typed_by_hand_opens_with_its_choices(home: Home, page: Page) -> None:
    element = "fork-and-scale-food-diary-card"
    typed = {"type": f"custom:{element}", "person": "debora", "locale": "pt-br"}
    edit_dashboard(home, page, [typed])
    page.locator("hui-card-options").get_by_role("button", name="Edit").click()
    dialog = page.locator("hui-dialog-edit-card")
    expect(dialog.get_by_label("Person")).to_contain_text("Debora", timeout=TIMEOUT)
    expect(dialog.get_by_label("Language")).to_contain_text("Português (Brasil)")
    expect(dialog.locator(f"{element} .person")).to_have_text("Debora", timeout=TIMEOUT)
    # Brazilian Portuguese, not Portugal's "Pequeno-almoço".
    expect(dialog.locator(f'{element} .meal[data-meal="breakfast"]')).to_contain_text(
        "Café da manhã"
    )
