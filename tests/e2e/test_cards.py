"""The cards in a real browser, against a brand-new Home Assistant."""

from __future__ import annotations

import json
import re
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


def test_the_weight_card_logs_and_deletes_a_day_s_weight(home: Home, page: Page) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    card = open_card(home, page, {"type": "custom:zp-weight-card", "person": "Debora"})
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
    expect(card.locator(".chart")).to_contain_text("Goal 62 kg")

    card.locator('[data-field="day"]').fill(yesterday)
    card.locator('[data-field="kg"]').fill("69.3")
    card.locator('[data-action="log"]').click()
    item = card.locator(".recent .item", has_text="69.3 kg")
    expect(item).to_have_count(1, timeout=TIMEOUT)
    weights = home.ws({"type": "zp_my_fitness/weights", "person": person_id(home, "Debora")})
    assert {"day": yesterday, "kg": 69.3} in weights

    card.locator('[data-field="kg"]').fill("5")
    card.locator('[data-action="log"]').click()
    expect(card.locator(".error")).to_contain_text("from 20 to 400 kg")

    item.locator('[data-action="delete-weight"]').click()
    expect(card.locator(".recent .item", has_text="69.3 kg")).to_have_count(0, timeout=TIMEOUT)


def test_the_trends_card_opens_a_day_in_the_diary(home: Home, page: Page) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    matteo = person_id(home, "Matteo")
    home.ws(
        {
            "type": "zp_my_fitness/entry/add",
            "person": matteo,
            "day": yesterday,
            "meal": "breakfast",
            "name": "Trend eggs e2e",
            "kcal": 300,
        }
    )
    home.dashboard(
        [
            {"type": "custom:zp-trends-card", "person": "Matteo"},
            {"type": "custom:zp-food-diary-card", "person": "Matteo"},
        ]
    )
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    trends = page.locator("zp-trends-card")
    diary = page.locator("zp-food-diary-card")
    expect(trends.locator(".chart")).to_be_visible(timeout=30_000)
    expect(trends.locator(".stats")).to_contain_text("Average a day")
    expect(diary.locator(".nav .label")).to_have_text("Today", timeout=TIMEOUT)

    trends.locator(f'.bar[data-day="{yesterday}"] .hit').click()
    expect(diary.locator(".nav .label")).to_have_text("Yesterday")
    expect(diary.locator(".row", has_text="Trend eggs e2e")).to_have_count(1, timeout=TIMEOUT)

    trends.locator('[data-action="range"][data-range="90"]').click()
    expect(trends.locator('[data-action="range"][data-range="90"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    # 90 days are weekly bars, which do not open a day.
    expect(trends.locator(".bar[data-action]")).to_have_count(0, timeout=TIMEOUT)


def test_the_summary_card_shows_today_and_opens_its_path(home: Home, page: Page) -> None:
    debora = person_id(home, "Debora")
    home.ws(
        {
            "type": "zp_my_fitness/entry/add",
            "person": debora,
            "day": today(),
            "meal": "lunch",
            "name": "Summary soup e2e",
            "kcal": 321,
        }
    )
    eaten = sum(
        e["kcal"]
        for e in home.ws({"type": "zp_my_fitness/day", "person": debora, "day": today()})["entries"]
    )
    card = open_card(
        home,
        page,
        {"type": "custom:zp-summary-card", "person": "Debora", "navigation_path": "/config"},
    )
    expect(card.locator(".big .centre")).to_be_visible(timeout=TIMEOUT)
    expect(card.locator(".body")).to_contain_text(f"{round(eaten):,} of", timeout=TIMEOUT)
    expect(card.locator(".legend")).to_contain_text("Lunch")
    expect(card.locator(".weight")).to_contain_text("kg")

    card.locator(".big").click()
    expect(page).to_have_url(re.compile(r"/config"), timeout=TIMEOUT)


# Open Food Facts is answered here, so the tests never call the real service.
OFF_PRODUCTS = {
    "5201054017111": {
        "product_name": "Greek yogurt 2%",
        "brands": "Fage",
        "serving_quantity": 170,
        "nutriments": {
            "energy-kcal_100g": 73,
            "proteins_100g": 10,
            "carbohydrates_100g": 3.6,
            "fat_100g": 2,
        },
    },
    "8076809513753": {
        "product_name": "Spaghetti n.5",
        "brands": "Barilla",
        "nutriments": {
            "energy-kcal_100g": 359,
            "proteins_100g": 12.5,
            "carbohydrates_100g": 71.2,
            "fat_100g": 2,
        },
    },
}


def mock_open_food_facts(page: Page) -> list[str]:
    asked: list[str] = []

    def answer(route) -> None:
        code = route.request.url.split("/product/")[1].split(".json")[0]
        asked.append(code)
        product = OFF_PRODUCTS.get(code)
        if product is None:
            route.fulfill(status=404, json={"status": 0}, headers=CORS)
        else:
            route.fulfill(json={"status": 1, "product": product}, headers=CORS)

    page.route("https://world.openfoodfacts.org/**", answer)
    return asked


# Open Food Facts joins a product's name and brand with an en dash.
DASH = "\u2013"

CORS = {"Access-Control-Allow-Origin": "*"}


def fake_camera(page: Page, code: str) -> None:
    """A browser barcode reader that sees `code`, and a camera to read with."""
    script = """
        (() => {
          window.BarcodeDetector = class {
            static async getSupportedFormats() { return ["ean_13", "ean_8"]; }
            async detect() { return [{ rawValue: CODE, format: "ean_13" }]; }
          };
          navigator.mediaDevices.getUserMedia = async () => {
            const canvas = document.createElement("canvas");
            canvas.getContext("2d").fillRect(0, 0, 10, 10);
            return canvas.captureStream();
          };
        })();
    """
    page.add_init_script(script.replace("CODE", json.dumps(code)))


def test_the_saved_foods_card_fills_a_food_from_its_barcode(home: Home, page: Page) -> None:
    asked = mock_open_food_facts(page)
    card = open_card(home, page, {"type": "custom:zp-foods-card"})
    card.locator('[data-action="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="barcode"]').fill("123")
    card.locator('[data-action="lookup"]').click()
    expect(card.locator(".panel .error")).to_contain_text("8 to 14 digits")

    form.locator('[data-field="barcode"]').fill("5201054017111")
    card.locator('[data-action="lookup"]').click()
    expect(card.locator(".panel .note")).to_contain_text("Filled in from Open Food Facts")
    expect(form.locator('[data-field="name"]')).to_have_value(f"Greek yogurt 2% {DASH} Fage")
    expect(form.locator('[data-field="kcal"]')).to_have_value("73")
    expect(form.locator('[data-portion="grams"]')).to_have_value("170")
    assert asked == ["5201054017111"]
    card.locator('[data-action="save"]').click()
    expect(card.locator(".panel")).to_be_hidden(timeout=TIMEOUT)
    saved = home.ws({"type": "zp_my_fitness/food/barcode", "barcode": "5201054017111"})
    assert saved["name"] == f"Greek yogurt 2% {DASH} Fage"
    assert saved["portions"] == [{"name": "Serving", "grams": 170}]

    # Looking the same barcode up again opens the saved food.
    card.locator('[data-action="new"]').click()
    card.locator('.foodform [data-field="barcode"]').fill("5201054017111")
    card.locator('[data-action="lookup"]').click()
    expect(card.locator(".panel .note")).to_contain_text("already has this barcode")
    expect(card.locator('[data-action="delete"]')).to_be_visible()


def test_the_diary_looks_up_a_typed_barcode_it_does_not_have(home: Home, page: Page) -> None:
    mock_open_food_facts(page)
    card = diary(home, page, "Debora")
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("8076809513753")
    card.locator('[data-action="lookup-query"]').click()
    expect(card.locator('.foodform [data-field="name"]')).to_have_value(
        f"Spaghetti n.5 {DASH} Barilla"
    )
    card.locator('[data-action="save-new-food"]').click()
    card.locator('[data-field="grams"]').fill("80")
    card.locator('[data-action="add-entry"]').click()
    row = meal(card, "dinner").locator(".row", has_text="Spaghetti n.5")
    expect(row).to_contain_text("287", timeout=TIMEOUT)


def test_the_diary_says_when_open_food_facts_does_not_know_a_barcode(
    home: Home, page: Page
) -> None:
    mock_open_food_facts(page)
    card = diary(home, page, "Debora")
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("40000000000099")
    card.locator('[data-action="lookup-query"]').click()
    expect(card.locator(".panel .error")).to_contain_text("does not know barcode 40000000000099")
    expect(card.locator('.foodform [data-field="barcode"]')).to_have_value("40000000000099")


def test_scanning_with_the_browser_reads_the_barcode(home: Home, page: Page) -> None:
    mock_open_food_facts(page)
    fake_camera(page, "8076809513753")
    card = open_card(home, page, {"type": "custom:zp-foods-card"})
    card.locator('[data-action="new"]').click()
    card.locator('[data-action="scan"]').click()
    form = card.locator(".foodform")
    expect(form.locator('[data-field="barcode"]')).to_have_value("8076809513753", timeout=TIMEOUT)
    expect(form.locator('[data-field="name"]')).to_have_value(f"Spaghetti n.5 {DASH} Barilla")
    expect(card.locator(".scanner")).to_be_hidden()


def test_scanning_a_saved_food_in_the_diary_chooses_it(home: Home, page: Page) -> None:
    save_food(home, "Scanned oats e2e", barcode="12345670")
    fake_camera(page, "12345670")
    card = diary(home, page, "Debora")
    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('.panel [data-action="scan"]').click()
    expect(card.locator(".picked")).to_contain_text("Scanned oats e2e", timeout=TIMEOUT)
    expect(card.locator('[data-field="grams"]')).to_have_value("100")


def test_without_a_scanner_there_is_no_scan_button(home: Home, page: Page) -> None:
    page.add_init_script("delete window.BarcodeDetector")
    card = open_card(home, page, {"type": "custom:zp-foods-card"})
    card.locator('[data-action="new"]').click()
    expect(card.locator('[data-action="lookup"]')).to_be_visible()
    expect(card.locator('[data-action="scan"]')).to_have_count(0)
