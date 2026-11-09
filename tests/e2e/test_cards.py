"""The cards in a real browser, against a brand-new Home Assistant."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Locator, Page, expect

from .conftest import Home

TIMEOUT = 15_000


def today() -> str:
    # The test home is in London.
    return datetime.now(ZoneInfo("Europe/London")).date().isoformat()


def person_id(home: Home, name: str) -> str:
    return next(p["id"] for p in home.ws({"type": "zp_my_fitness/people"}) if p["name"] == name)


def save_food(home: Home, name: str, **more) -> dict:
    return home.ws(
        {
            "type": "zp_my_fitness/food/add",
            "name": name,
            "kcal": 389,
            "protein": 16.9,
            "carbs": 66,
            "fat": 6.9,
            **more,
        }
    )


def open_card(home: Home, page: Page, card: dict) -> Locator:
    home.dashboard([card])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    element = page.locator(card["type"].removeprefix("custom:"))
    expect(element.locator(".title").first).to_be_visible(timeout=30_000)
    return element


def diary(home: Home, page: Page, person: str) -> Locator:
    card = open_card(home, page, {"type": "custom:zp-food-diary-card", "person": person})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    return card


def meal(card: Locator, name: str) -> Locator:
    return card.locator(f'.meal[data-meal="{name}"]')


def test_adds_a_saved_food_by_weight_then_edits_and_deletes_it(home: Home, page: Page) -> None:
    save_food(home, "Porridge oats e2e", portions=[{"name": "Bowl", "grams": 40}])
    card = diary(home, page, "Debora")

    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("oats e2e")
    card.locator('[data-action="choose"]', has_text="Porridge oats e2e").click()
    grams = card.locator('[data-field="grams"]')
    expect(grams).to_have_value("40")  # the first portion
    grams.fill("60")
    expect(card.locator(".preview")).to_contain_text("233")
    card.locator('[data-action="add-entry"]').click()

    row = meal(card, "breakfast").locator(".row", has_text="Porridge oats e2e")
    expect(row).to_contain_text("60 g", timeout=TIMEOUT)
    expect(row).to_contain_text("233")
    expect(card.locator(".panel")).to_be_hidden()

    row.click()
    card.locator('.panel [data-field="grams"]').fill("80")
    card.locator('.panel [data-field="meal"]').select_option("lunch")
    card.locator('[data-action="save-edit"]').click()
    moved = meal(card, "lunch").locator(".row", has_text="Porridge oats e2e")
    expect(moved).to_contain_text("311", timeout=TIMEOUT)

    moved.click()
    card.locator('[data-action="delete-entry"]').click()
    card.locator('[data-action="really-delete"]').click()
    expect(meal(card, "lunch").locator(".row", has_text="Porridge oats e2e")).to_have_count(
        0, timeout=TIMEOUT
    )


def test_quick_adds_a_name_and_kcal(home: Home, page: Page) -> None:
    card = diary(home, page, "Debora")
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="quick"]').click()
    card.locator('.panel [data-field="name"]').fill("Restaurant pizza e2e")
    card.locator('.panel [data-field="kcal"]').fill("900")
    card.locator('[data-action="quick-add"]').click()
    row = meal(card, "dinner").locator(".row", has_text="Restaurant pizza e2e")
    expect(row).to_contain_text("900", timeout=TIMEOUT)
    expect(row).not_to_contain_text(" g")


def test_saves_a_new_food_from_the_diary_and_logs_it(home: Home, page: Page) -> None:
    card = diary(home, page, "Debora")
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill("Almonds e2e")
    for field, value in {"kcal": "579", "protein": "21", "carbs": "22", "fat": "50"}.items():
        form.locator(f'[data-field="{field}"]').fill(value)
    card.locator('[data-action="save-new-food"]').click()
    card.locator('[data-field="grams"]').fill("25")
    card.locator('[data-action="add-entry"]').click()
    row = meal(card, "snacks").locator(".row", has_text="Almonds e2e")
    expect(row).to_contain_text("145", timeout=TIMEOUT)


def test_rejects_an_incomplete_new_food(home: Home, page: Page) -> None:
    card = diary(home, page, "Debora")
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    card.locator('.foodform [data-field="name"]').fill("Nothing else")
    card.locator('[data-action="save-new-food"]').click()
    expect(card.locator(".panel .error")).to_contain_text("Fill in the name")


def test_copies_a_meal_from_yesterday_and_moves_between_days(home: Home, page: Page) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    home.ws(
        {
            "type": "zp_my_fitness/entry/add",
            "person": person_id(home, "Matteo"),
            "day": yesterday,
            "meal": "lunch",
            "name": "Soup e2e",
            "kcal": 250,
        }
    )
    card = diary(home, page, "Matteo")
    expect(card.locator('[data-action="next"]')).to_be_disabled()

    meal(card, "lunch").locator('[data-action="copy"]').click()
    card.locator('[data-action="do-copy"]').click()
    expect(meal(card, "lunch").locator(".row", has_text="Soup e2e")).to_have_count(
        1, timeout=TIMEOUT
    )

    card.locator('[data-action="prev"]').click()
    expect(card.locator(".nav .label")).to_have_text("Yesterday")
    expect(meal(card, "lunch").locator(".row", has_text="Soup e2e")).to_have_count(
        1, timeout=TIMEOUT
    )
    card.locator('[data-action="next"]').click()
    expect(card.locator(".nav .label")).to_have_text("Today")


def test_copying_an_empty_meal_says_so(home: Home, page: Page) -> None:
    card = diary(home, page, "Matteo")
    meal(card, "snacks").locator('[data-action="copy"]').click()
    card.locator('.panel [data-field="from_day"]').fill("2000-01-01")
    card.locator('[data-action="do-copy"]').click()
    expect(card.locator(".panel .error")).to_contain_text("Nothing to copy")


def test_the_saved_foods_card_adds_edits_and_deletes(home: Home, page: Page) -> None:
    card = open_card(home, page, {"type": "custom:zp-foods-card"})
    card.locator('[data-action="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill("Greek yogurt e2e")
    form.locator('[data-field="barcode"]').fill("5201054017111")
    for field, value in {"kcal": "73", "protein": "10", "carbs": "3.6", "fat": "2"}.items():
        form.locator(f'[data-field="{field}"]').fill(value)
    card.locator('[data-action="add-portion"]').click()
    form.locator('[data-portion="name"]').fill("Pot")
    form.locator('[data-portion="grams"]').fill("170")
    card.locator('[data-action="save"]').click()

    card.locator('[data-action="query"]').fill("yogurt e2e")
    row = card.locator(".row", has_text="Greek yogurt e2e")
    expect(row).to_contain_text("73 kcal per 100 g", timeout=TIMEOUT)
    saved = home.ws({"type": "zp_my_fitness/food/barcode", "barcode": "5201054017111"})
    assert saved["portions"] == [{"name": "Pot", "grams": 170}]

    row.click()
    card.locator('.foodform [data-field="kcal"]').fill("75")
    card.locator('[data-action="save"]').click()
    expect(row).to_contain_text("75 kcal per 100 g", timeout=TIMEOUT)

    row.click()
    card.locator('[data-action="delete"]').click()
    card.locator('[data-action="really-delete"]').click()
    expect(card.locator(".row", has_text="Greek yogurt e2e")).to_have_count(0, timeout=TIMEOUT)


def test_a_used_barcode_is_refused(home: Home, page: Page) -> None:
    save_food(home, "First e2e", barcode="400000000001")
    card = open_card(home, page, {"type": "custom:zp-foods-card"})
    card.locator('[data-action="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill("Second e2e")
    form.locator('[data-field="barcode"]').fill("400000000001")
    for field in ("kcal", "protein", "carbs", "fat"):
        form.locator(f'[data-field="{field}"]').fill("1")
    card.locator('[data-action="save"]').click()
    expect(card.locator(".panel .error")).to_contain_text("Another saved food has this barcode")


@pytest.mark.parametrize("language", ["it"])
def test_follows_the_locale_option(home: Home, page: Page, language: str) -> None:
    card = open_card(
        home, page, {"type": "custom:zp-food-diary-card", "person": "Debora", "locale": language}
    )
    expect(card.locator(".title").first).to_have_text("Diario alimentare")
    expect(meal(card, "breakfast").locator(".mealhead")).to_contain_text("Colazione")
