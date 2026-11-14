"""The cards in a real browser, against a brand-new Home Assistant."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Locator, Page, expect

from .conftest import FakeSearch, Home
from .flows import goals_since, person_named

TIMEOUT = 15_000


def today() -> str:
    # The test home is in London.
    return datetime.now(ZoneInfo("Europe/London")).date().isoformat()


def person_id(home: Home, name: str) -> str:
    return next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == name)


def save_food(home: Home, name: str, **more) -> dict:
    return home.ws(
        {
            "type": "metron/food/add",
            "name": name,
            "kcal": 389,
            "protein": 16.9,
            "carbs": 66,
            "fat": 6.9,
            **more,
        }
    )


# For a test worth running on a phone as well: a phone's touch and narrow
# layout can hide or cover what a laptop shows.
ON_A_PHONE_TOO = pytest.mark.parametrize("page", ["laptop", "phone"], indirect=True)


@pytest.fixture
def on(request: pytest.FixtureRequest) -> str:
    """Where the test runs, to keep what it saves apart from its other run's."""
    callspec = getattr(request.node, "callspec", None)
    return callspec.params.get("page", "laptop") if callspec else "laptop"


def open_card(home: Home, page: Page, card: dict) -> Locator:
    home.dashboard([card])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    element = page.locator(card["type"].removeprefix("custom:"))
    expect(element.locator(".title").first).to_be_visible(timeout=30_000)
    return element


def diary(home: Home, page: Page, person: str) -> Locator:
    card = open_card(home, page, {"type": "custom:metron-food-diary-card", "person": person})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    return card


def meal(card: Locator, name: str) -> Locator:
    return card.locator(f'.meal[data-meal="{name}"]')


@ON_A_PHONE_TOO
def test_adds_a_saved_food_by_weight_then_edits_and_deletes_it(
    home: Home, page: Page, on: str
) -> None:
    save_food(home, f"Porridge oats e2e {on}", portions=[{"name": "Bowl", "grams": 40}])
    card = diary(home, page, "Debora")

    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("oats e2e")
    card.locator('[data-action="choose"]', has_text=f"Porridge oats e2e {on}").click()
    grams = card.locator('[data-field="grams"]')
    expect(grams).to_have_value("40")  # the first portion
    grams.fill("60")
    expect(card.locator(".preview")).to_contain_text("233")
    card.locator('[data-action="add-entry"]').click()

    row = meal(card, "breakfast").locator(".row", has_text=f"Porridge oats e2e {on}")
    expect(row).to_contain_text("60 g", timeout=TIMEOUT)
    expect(row).to_contain_text("233")
    expect(card.locator(".panel")).to_be_hidden()

    row.click()
    # An empty amount is refused, keeping the meal chosen.
    card.locator('.panel [data-field="meal"]').select_option("lunch")
    card.locator('.panel [data-field="grams"]').fill("")
    card.locator('[data-action="save-edit"]').click()
    expect(card.locator(".panel .error")).to_have_text("Enter an amount above 0.")
    expect(card.locator('.panel [data-field="meal"]')).to_have_value("lunch")
    card.locator('.panel [data-field="grams"]').fill("80")
    card.locator('[data-action="save-edit"]').click()
    moved = meal(card, "lunch").locator(".row", has_text=f"Porridge oats e2e {on}")
    expect(moved).to_contain_text("311", timeout=TIMEOUT)

    moved.click()
    card.locator('[data-action="delete-entry"]').click()
    card.locator('[data-action="really-delete"]').click()
    expect(meal(card, "lunch").locator(".row", has_text=f"Porridge oats e2e {on}")).to_have_count(
        0, timeout=TIMEOUT
    )


@ON_A_PHONE_TOO
def test_quick_adds_a_name_and_kcal(home: Home, page: Page, on: str) -> None:
    card = diary(home, page, "Debora")
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="quick"]').click()
    card.locator('.panel [data-field="name"]').fill(f"Restaurant pizza e2e {on}")
    card.locator('.panel [data-field="kcal"]').fill("900")
    card.locator('[data-action="quick-add"]').click()
    row = meal(card, "dinner").locator(".row", has_text=f"Restaurant pizza e2e {on}")
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


def test_quick_adds_macros_into_another_meal(home: Home, page: Page) -> None:
    card = diary(home, page, "Debora")
    meal(card, "lunch").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="quick"]').click()
    fields = {"name": "Burrito e2e", "kcal": "640", "protein": "30", "carbs": "70", "fat": "22"}
    for field, value in fields.items():
        card.locator(f'.panel [data-field="{field}"]').fill(value)
    card.locator('.panel [data-field="meal"]').select_option("dinner")
    card.locator('[data-action="quick-add"]').click()
    expect(meal(card, "dinner").locator(".row", has_text="Burrito e2e")).to_contain_text(
        "640", timeout=TIMEOUT
    )
    expect(meal(card, "lunch").locator(".row", has_text="Burrito e2e")).to_have_count(0)
    day = home.ws({"type": "metron/day", "person": person_id(home, "Debora"), "day": today()})
    [burrito] = [e for e in day["entries"] if e["name"] == "Burrito e2e"]
    assert (burrito["meal"], burrito["protein"], burrito["carbs"], burrito["fat"]) == (
        "dinner",
        30,
        70,
        22,
    )


def test_an_amount_must_be_above_0_to_add_or_save(home: Home, page: Page) -> None:
    save_food(home, "Rice cakes e2e")
    card = diary(home, page, "Matteo")
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("Rice cakes e2e")
    card.locator('[data-action="choose"]', has_text="Rice cakes e2e").click()
    grams = card.locator('.panel [data-field="grams"]')
    add = card.locator('[data-action="add-entry"]')
    for typed in ("", "0"):
        grams.fill(typed)
        expect(add).to_be_disabled()
        expect(card.locator(".preview b").first).to_have_text("\u2013")
    grams.fill("25")
    expect(add).to_be_enabled()
    expect(card.locator(".preview b").first).to_have_text("97")

    # A quick add's amount is its kcal, which an edit changes, and which must be above 0 too.
    card.locator('[data-action="close"]').first.click()
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="quick"]').click()
    card.locator('.panel [data-field="name"]').fill("Vending machine e2e")
    card.locator('.panel [data-field="kcal"]').fill("900")
    card.locator('[data-action="quick-add"]').click()
    row = meal(card, "snacks").locator(".row", has_text="Vending machine e2e")
    expect(row).to_contain_text("900", timeout=TIMEOUT)
    row.click()
    kcal = card.locator('.panel [data-field="kcal"]')
    kcal.fill("0")
    card.locator('[data-action="save-edit"]').click()
    expect(card.locator(".panel .error")).to_have_text("Enter an amount above 0.")
    kcal.fill("450")
    card.locator('[data-action="save-edit"]').click()
    expect(row).to_contain_text("450", timeout=TIMEOUT)


@ON_A_PHONE_TOO
def test_copies_a_meal_from_yesterday_and_moves_between_days(
    home: Home, page: Page, on: str
) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    home.ws(
        {
            "type": "metron/entry/add",
            "person": person_id(home, "Matteo"),
            "day": yesterday,
            "meal": "lunch",
            "name": f"Soup e2e {on}",
            "kcal": 250,
        }
    )
    card = diary(home, page, "Matteo")
    expect(card.locator('[data-action="next"]')).to_be_disabled()

    meal(card, "lunch").locator('[data-action="copy"]').click()
    card.locator('[data-action="do-copy"]').click()
    expect(meal(card, "lunch").locator(".row", has_text=f"Soup e2e {on}")).to_have_count(
        1, timeout=TIMEOUT
    )

    card.locator('[data-action="prev"]').click()
    expect(card.locator(".nav .label")).to_have_text("Yesterday")
    expect(meal(card, "lunch").locator(".row", has_text=f"Soup e2e {on}")).to_have_count(
        1, timeout=TIMEOUT
    )
    card.locator('[data-action="next"]').click()
    expect(card.locator(".nav .label")).to_have_text("Today")


def test_copying_an_empty_meal_says_so_keeping_what_was_chosen(home: Home, page: Page) -> None:
    earlier = (date.fromisoformat(today()) - timedelta(days=3)).isoformat()
    home.ws(
        {
            "type": "metron/entry/add",
            "person": person_id(home, "Matteo"),
            "day": earlier,
            "meal": "dinner",
            "name": "Copied curry e2e",
            "kcal": 640,
        }
    )
    card = diary(home, page, "Matteo")
    meal(card, "snacks").locator('[data-action="copy"]').click()
    from_day = card.locator('.panel [data-field="from_day"]')
    from_meal = card.locator('.panel [data-field="from_meal"]')
    from_day.fill("2000-01-01")
    from_meal.select_option("dinner")
    card.locator('[data-action="do-copy"]').click()
    expect(card.locator(".panel .error")).to_contain_text("Nothing to copy")
    expect(from_day).to_have_value("2000-01-01")
    expect(from_meal).to_have_value("dinner")

    from_day.fill(earlier)
    card.locator('[data-action="do-copy"]').click()
    copied = meal(card, "snacks").locator(".row", has_text="Copied curry e2e")
    expect(copied).to_contain_text("640", timeout=TIMEOUT)


# A barcode belongs to one food, so each run saves its own.
BARCODES = {"laptop": "5201054017111", "phone": "5201054017128"}


@ON_A_PHONE_TOO
def test_the_saved_foods_card_adds_edits_and_deletes(home: Home, page: Page, on: str) -> None:
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill(f"Greek yogurt e2e {on}")
    form.locator('[data-field="barcode"]').fill(BARCODES[on])
    for field, value in {"kcal": "73", "protein": "10", "carbs": "3.6", "fat": "2"}.items():
        form.locator(f'[data-field="{field}"]').fill(value)
    card.locator('[data-action="add-portion"]').click()
    form.locator('[data-portion="name"]').fill("Pot")
    form.locator('[data-portion="grams"]').fill("170")
    card.locator('[data-action="save"]').click()

    card.locator('[data-action="query"]').fill(f"yogurt e2e {on}")
    row = card.locator(".row", has_text=f"Greek yogurt e2e {on}")
    expect(row).to_contain_text("73 kcal per 100 g", timeout=TIMEOUT)
    saved = home.ws({"type": "metron/food/barcode", "barcode": BARCODES[on]})
    assert saved["portions"] == [{"name": "Pot", "grams": 170}]

    row.click()
    card.locator('.foodform [data-field="kcal"]').fill("75")
    card.locator('[data-action="save"]').click()
    expect(row).to_contain_text("75 kcal per 100 g", timeout=TIMEOUT)

    row.click()
    card.locator('[data-action="delete"]').click()
    card.locator('[data-action="really-delete"]').click()
    expect(card.locator(".row", has_text=f"Greek yogurt e2e {on}")).to_have_count(
        0, timeout=TIMEOUT
    )


def test_a_used_barcode_opens_the_food_that_has_it(home: Home, page: Page) -> None:
    save_food(home, "First e2e", barcode="400000000001")
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill("Second e2e")
    form.locator('[data-field="barcode"]').fill("400000000001")
    for field in ("kcal", "protein", "carbs", "fat"):
        form.locator(f'[data-field="{field}"]').fill("1")
    card.locator('[data-action="save"]').click()
    # Nothing is saved twice: the food that has the barcode opens instead.
    expect(card.locator(".panel .warning")).to_have_text("Already saved as First e2e.")
    expect(card.locator(".panel .title")).to_have_text("First e2e")
    expect(card.locator('.panel [data-action="delete"]')).to_be_visible()
    assert len(home.ws({"type": "metron/food/search", "query": "Second e2e"})) == 0


@pytest.mark.parametrize("language", ["it"])
def test_follows_the_locale_option(home: Home, page: Page, language: str) -> None:
    card = open_card(
        home,
        page,
        {"type": "custom:metron-food-diary-card", "person": "Debora", "locale": language},
    )
    expect(card.locator(".title").first).to_have_text("Diario alimentare")
    expect(meal(card, "breakfast").locator(".mealhead")).to_contain_text("Colazione")


@ON_A_PHONE_TOO
def test_the_weight_card_logs_and_deletes_a_day_s_weight(home: Home, page: Page, on: str) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    card = open_card(home, page, {"type": "custom:metron-weight-card", "person": "Debora"})
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
    expect(card.locator(".chart")).to_contain_text("Goal 62 kg")

    card.locator('[data-field="day"]').fill(yesterday)
    card.locator('[data-field="weight"]').fill("69.3")
    card.locator('[data-action="log"]').click()
    item = card.locator(".recent .item", has_text="69.3 kg")
    expect(item).to_have_count(1, timeout=TIMEOUT)
    weights = home.ws({"type": "metron/weights", "person": person_id(home, "Debora")})
    assert {"day": yesterday, "kg": 69.3} in weights

    card.locator('[data-field="weight"]').fill("5")
    card.locator('[data-action="log"]').click()
    expect(card.locator(".error")).to_contain_text("from 20 to 400 kg")

    # A finger can hit the delete button without hitting its neighbours: at
    # least 24 by 24 px, as WCAG asks of a target.
    delete = item.locator('[data-action="delete-weight"]')
    box = delete.bounding_box()
    assert box["width"] >= 24 and box["height"] >= 24, box
    delete.click()
    expect(card.locator(".recent .item", has_text="69.3 kg")).to_have_count(0, timeout=TIMEOUT)


def test_the_weight_card_s_headline_follows_the_weigh_ins(home: Home, page: Page) -> None:
    # Wade starts at 70 kg and 170 cm, today: a healthy weight.
    with person_named(home, "Wade e2e"):
        card = open_card(home, page, {"type": "custom:metron-weight-card", "person": "Wade e2e"})
        now = card.locator(".now")
        expect(now.locator("b")).to_have_text("70 kg", timeout=TIMEOUT)
        expect(now.locator(".sub")).to_have_text(re.compile(r"^±0 kg since "))
        expect(now.locator(".chip")).to_have_text("Healthy")
        expect(card.locator(".body .muted")).to_contain_text("No weigh-ins yet")

        home.ws(
            {
                "type": "metron/weight/set",
                "person": person_id(home, "Wade e2e"),
                "day": today(),
                "kg": 88,
            }
        )
        expect(now.locator("b")).to_have_text("88 kg", timeout=TIMEOUT)
        expect(now.locator(".sub")).to_have_text(re.compile(r"^\+18 kg since "))
        expect(now.locator(".chip")).to_have_text("Obese")
        expect(card.locator(".body .muted")).to_have_count(0)


def test_typing_key_by_key_keeps_the_box_focused(home: Home, page: Page) -> None:
    save_food(home, "Focus oats e2e")
    home.ws(
        {
            "type": "metron/meal/add",
            "name": "Focus latte e2e",
            "owner": None,
            "items": [{"name": "Latte", "kcal": 150}],
        }
    )

    def typed(box: Locator, text: str) -> None:
        box.click()
        box.press("Control+a")
        box.press_sequentially(text)
        expect(box).to_be_focused()
        expect(box).to_have_value(text)

    card = open_card(home, page, {"type": "custom:metron-meals-card"})
    card.locator('[data-action="new"]').click()
    panel = card.locator(".panel")
    typed(panel.locator('[data-field="meal-name"]'), "Focus bowl e2e")
    typed(panel.locator('[data-action="add-food"]'), "Focus oats")
    panel.locator('.addfood [data-action="add-item"]', has_text="Focus oats e2e").click()
    typed(panel.locator('[data-action="item-grams"]'), "120")
    expect(panel.locator(".mealitem .kcal")).to_have_text("467")
    panel.locator('[data-action="close"]').click()
    typed(card.locator('[data-action="query"]'), "Focus latte")
    card.locator(".mealrow", has_text="Focus latte e2e").click()
    typed(panel.locator('[data-action="fixed"][data-key="kcal"]'), "180")
    typed(panel.locator('[data-action="fixed"][data-key="name"]'), "Oat latte")

    foods = open_card(home, page, {"type": "custom:metron-foods-card"})
    typed(foods.locator('[data-action="query"]'), "Focus oats")
    expect(foods.locator(".row", has_text="Focus oats e2e")).to_be_visible()
    foods.locator('[data-action="new"]').click()
    typed(foods.locator('[data-action="off-query"]'), "muesli")


def test_after_logging_a_past_day_the_weight_card_logs_today(home: Home, page: Page) -> None:
    past = (date.fromisoformat(today()) - timedelta(days=20)).isoformat()
    with person_named(home, "Wendy e2e"):
        card = open_card(home, page, {"type": "custom:metron-weight-card", "person": "Wendy e2e"})
        expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
        card.locator('[data-field="day"]').fill(past)
        # A weight out of range is refused, keeping the day chosen.
        card.locator('[data-field="weight"]').fill("5")
        card.locator('[data-action="log"]').click()
        expect(card.locator(".error")).to_contain_text("from 20 to 400 kg")
        expect(card.locator('[data-field="day"]')).to_have_value(past)
        card.locator('[data-field="weight"]').fill("71.4")
        card.locator('[data-action="log"]').click()
        expect(card.locator(".recent .item", has_text="71.4 kg")).to_have_count(1, timeout=TIMEOUT)

        # The day goes back to today, so the next weigh-in is today's.
        expect(card.locator('[data-field="day"]')).to_have_value(today())
        card.locator('[data-field="weight"]').fill("71.2")
        card.locator('[data-action="log"]').click()
        expect(card.locator(".recent .item", has_text="71.2 kg")).to_have_count(1, timeout=TIMEOUT)
        weights = home.ws({"type": "metron/weights", "person": person_id(home, "Wendy e2e")})
        assert weights == [{"day": past, "kg": 71.4}, {"day": today(), "kg": 71.2}]


@ON_A_PHONE_TOO
def test_the_trends_card_opens_a_day_in_the_diary(home: Home, page: Page, on: str) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    matteo = person_id(home, "Matteo")
    home.ws(
        {
            "type": "metron/entry/add",
            "person": matteo,
            "day": yesterday,
            "meal": "breakfast",
            "name": f"Trend eggs e2e {on}",
            "kcal": 300,
        }
    )
    home.dashboard(
        [
            {"type": "custom:metron-trends-card", "person": "Matteo"},
            {"type": "custom:metron-food-diary-card", "person": "Matteo"},
        ]
    )
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    trends = page.locator("metron-trends-card")
    diary = page.locator("metron-food-diary-card")
    expect(trends.locator(".chart")).to_be_visible(timeout=30_000)
    expect(trends.locator(".stats")).to_contain_text("Average a day")
    expect(diary.locator(".nav .label")).to_have_text("Today", timeout=TIMEOUT)

    trends.locator(f'.bar[data-day="{yesterday}"] .hit').click()
    expect(diary.locator(".nav .label")).to_have_text("Yesterday")
    expect(diary.locator(".row", has_text=f"Trend eggs e2e {on}")).to_have_count(1, timeout=TIMEOUT)

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
            "type": "metron/entry/add",
            "person": debora,
            "day": today(),
            "meal": "lunch",
            "name": "Summary soup e2e",
            "kcal": 321,
        }
    )
    day = home.ws({"type": "metron/day", "person": debora, "day": today()})
    eaten = sum(e["kcal"] for e in day["entries"])
    card = open_card(
        home,
        page,
        {
            "type": "custom:metron-summary-card",
            "person": "Debora",
            "navigation_path": "/config",
        },
    )
    expect(card.locator(".big .centre")).to_be_visible(timeout=TIMEOUT)
    expect(card.locator(".body")).to_contain_text(f"{round(eaten):,} of", timeout=TIMEOUT)
    expect(card.locator(".legend")).to_contain_text("Lunch")
    expect(card.locator(".weight")).to_contain_text("kg")

    card.locator(".big").click()
    expect(page).to_have_url(re.compile(r"/config"), timeout=TIMEOUT)


def test_the_summary_card_shows_a_weigh_in_from_over_a_month_ago(home: Home, page: Page) -> None:
    long_ago = (date.fromisoformat(today()) - timedelta(days=45)).isoformat()
    # Sam starts at 70 kg and 170 cm: a healthy weight. 88 kg is obese.
    with person_named(home, "Sam e2e"):
        home.ws(
            {
                "type": "metron/weight/set",
                "person": person_id(home, "Sam e2e"),
                "day": long_ago,
                "kg": 88,
            }
        )
        card = open_card(home, page, {"type": "custom:metron-summary-card", "person": "Sam e2e"})
        expect(card.locator(".weight b")).to_have_text("88 kg", timeout=TIMEOUT)
        expect(card.locator(".weight .chip")).to_have_text("Obese")


def test_open_cards_move_to_the_new_day_at_midnight(home: Home, page: Page) -> None:
    midnight = datetime.now(ZoneInfo("Europe/London")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    new_day = midnight.date().isoformat()
    old_day = (midnight.date() - timedelta(days=1)).isoformat()
    with person_named(home, "Nell e2e"):
        home.ws(
            {
                "type": "metron/entry/add",
                "person": person_id(home, "Nell e2e"),
                "day": new_day,
                "meal": "lunch",
                "name": "Midnight soup e2e",
                "kcal": 321,
            }
        )
        # The browser's clock starts before last midnight, so the cards first
        # take yesterday for today.
        page.clock.install(time=midnight - timedelta(minutes=5))
        home.dashboard(
            [
                {"type": "custom:metron-food-diary-card", "person": "Nell e2e"},
                {"type": "custom:metron-food-diary-card", "person": "Nell e2e", "title": "Earlier"},
                {"type": "custom:metron-weight-card", "person": "Nell e2e"},
                {"type": "custom:metron-summary-card", "person": "Nell e2e"},
            ]
        )
        page.goto(home.url + "/" + home.DASHBOARD + "/0")
        diary = page.locator("metron-food-diary-card").first
        earlier = page.locator("metron-food-diary-card").last
        weight = page.locator("metron-weight-card")
        summary = page.locator("metron-summary-card")
        expect(diary.locator(".meal")).to_have_count(4, timeout=30_000)
        expect(diary.locator(".nav .label")).to_have_text("Today")
        expect(diary.locator(".body")).not_to_contain_text("Midnight soup e2e")
        earlier.locator('[data-action="prev"]').click()
        expect(earlier.locator(".nav .label")).to_have_text("Yesterday")
        expect(weight.locator('[data-field="day"]')).to_have_value(old_day, timeout=TIMEOUT)
        expect(summary.locator(".body")).not_to_contain_text("321 of", timeout=TIMEOUT)

        page.clock.fast_forward("05:10")
        # Any new state reaches the cards, as Metron's own sensors' do at midnight.
        home.api("POST", "/api/states/sensor.e2e_clock", {"state": "midnight"})

        # A diary on today moves to the new day; one on an earlier day stays.
        expect(diary.locator(".body")).to_contain_text("Midnight soup e2e", timeout=TIMEOUT)
        expect(diary.locator(".nav .label")).to_have_text("Today")
        expect(diary.locator('[data-action="next"]')).to_be_disabled()
        expect(diary.locator('[data-action="pick-day"]')).to_have_attribute("max", new_day)
        expect(earlier.locator(".nav .label")).not_to_have_text("Yesterday")
        expect(earlier.locator('[data-action="next"]')).to_be_enabled()
        expect(weight.locator('[data-field="day"]')).to_have_value(new_day)
        expect(weight.locator('[data-field="day"]')).to_have_attribute("max", new_day)
        expect(summary.locator(".body")).to_contain_text("321 of", timeout=TIMEOUT)


def test_a_card_on_another_tab_catches_up_when_its_tab_comes_back(home: Home, page: Page) -> None:
    with person_named(home, "Tabitha e2e"):
        home.dashboard([])
        home.ws(
            {
                "type": "lovelace/config/save",
                "url_path": home.DASHBOARD,
                "config": {
                    "views": [
                        {
                            "title": "Summary",
                            "cards": [
                                {"type": "custom:metron-summary-card", "person": "Tabitha e2e"}
                            ],
                        },
                        {
                            "title": "Diary",
                            "cards": [
                                {"type": "custom:metron-food-diary-card", "person": "Tabitha e2e"}
                            ],
                        },
                    ]
                },
            }
        )
        page.goto(home.url + "/" + home.DASHBOARD + "/0")
        summary = page.locator("metron-summary-card")
        expect(summary.locator(".body")).to_contain_text("0 of", timeout=30_000)
        # Home Assistant keeps a tab's cards while another tab shows: the card
        # that comes back must be this one, not a new one that loads afresh.
        summary.evaluate("card => { card.sameCard = true }")

        page.get_by_role("tab", name="Diary").click()
        card = page.locator("metron-food-diary-card")
        expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
        meal(card, "dinner").locator('[data-action="add"]').click()
        card.locator('[data-action="tab"][data-tab="quick"]').click()
        card.locator('.panel [data-field="name"]').fill("Tab pizza e2e")
        card.locator('.panel [data-field="kcal"]').fill("777")
        card.locator('[data-action="quick-add"]').click()
        expect(meal(card, "dinner").locator(".row", has_text="Tab pizza e2e")).to_be_visible(
            timeout=TIMEOUT
        )

        page.get_by_role("tab", name="Summary").click()
        expect(summary.locator(".title")).to_be_visible(timeout=TIMEOUT)
        assert summary.evaluate("card => card.sameCard === true")
        expect(summary.locator(".body")).to_contain_text("777 of", timeout=TIMEOUT)


# The streak card


def goal_kcal(home: Home, name: str) -> float:
    day = home.ws({"type": "metron/day", "person": person_id(home, name), "day": today()})
    return day["goals"]["kcal"]


def eat(home: Home, name: str, day: str, kcal: float) -> int:
    """Log `kcal` for `name` on `day`; return the entry's ID."""
    entry = home.ws(
        {
            "type": "metron/entry/add",
            "person": person_id(home, name),
            "day": day,
            "meal": "dinner",
            "name": "Streak stew e2e",
            "kcal": kcal,
        }
    )
    return entry["id"]


def has(name: str) -> re.Pattern:
    """A class attribute that includes `name`."""
    return re.compile(rf"(^|\s){name}(\s|$)")


@ON_A_PHONE_TOO
def test_the_streak_card_counts_good_days_and_follows_today(
    home: Home, page: Page, on: str
) -> None:
    name = f"Streak e2e {on}"
    now = date.fromisoformat(today())

    def ago(n: int) -> str:
        return (now - timedelta(days=n)).isoformat()

    with person_named(home, name):
        goals_since(home, name, ago(10))
        goal = goal_kcal(home, name)
        # On goal from 10 days ago to 6, nothing logged 5 days ago, over 4
        # days ago, and on goal again since 3 days ago.
        for n in (10, 9, 8, 7, 6, 3, 2, 1):
            eat(home, name, ago(n), 500)
        eat(home, name, ago(4), goal + 250)

        card = open_card(home, page, {"type": "custom:metron-streak-card", "person": name})
        streak = card.locator(".fig b")
        expect(streak).to_have_text("3", timeout=TIMEOUT)
        expect(streak).to_have_class(has("live"))
        expect(card.locator(".unit")).to_have_text("day streak")
        expect(card.locator(".best")).to_have_text("Best 5 in 30")
        expect(card.locator(".count")).to_have_text("8")
        expect(card.locator(".of")).to_have_text("of the last 30 days")
        expect(card.locator(".track i")).to_have_attribute("style", "width:27%")
        expect(card.locator(".today-line")).to_have_text("Nothing logged today")
        expect(card.locator(".cal")).to_have_attribute(
            "aria-label",
            f"{name}, the last 30 days: on goal 8, over goal 1, nothing logged 1. "
            "Current streak 3, best 5.",
        )

        def cell(n: int) -> Locator:
            return card.locator(f'.cell[data-day="{ago(n)}"]')

        of_goal = f"of {round(goal):,} kcal"
        expect(cell(1)).to_have_class(has("good"))
        expect(cell(1)).to_have_attribute("title", re.compile(rf": on goal, 500 {of_goal}$"))
        expect(cell(4)).to_have_class(has("over"))
        expect(cell(4)).to_have_attribute(
            "title", re.compile(rf": over goal, {round(goal + 250):,} {of_goal}$")
        )
        expect(cell(5)).to_have_class(has("unlogged"))
        expect(cell(5)).to_have_attribute("title", re.compile(r": nothing logged$"))
        expect(cell(11)).to_have_class(has("before"))
        expect(cell(11)).to_have_attribute("title", re.compile(r": no goal yet$"))
        # A run joins its neighbours within a week's row, Monday to Sunday,
        # and never today.
        joins = cell(2).get_attribute("class").split()
        weekday = (now - timedelta(days=2)).weekday()
        assert ("jl" in joins) == (weekday != 0)
        assert ("jr" in joins) == (weekday != 6)
        expect(cell(1)).not_to_have_class(has("jr"))
        today_cell = card.locator(".cell.today")
        expect(today_cell).to_have_attribute("data-day", today())
        expect(today_cell).to_have_class(has("pending"))
        expect(today_cell).to_have_attribute("title", re.compile(r": today, on goal so far$"))

        # Over today: the streak drops to 0 at once.
        over = eat(home, name, today(), goal + 100)
        expect(streak).to_have_text("0", timeout=TIMEOUT)
        expect(streak).not_to_have_class(has("live"))
        expect(card.locator(".today-line")).to_have_text("100 kcal over today")
        expect(card.locator(".today-line")).to_have_class(has("over"))
        expect(today_cell).to_have_class(has("over"))
        expect(today_cell).to_have_attribute(
            "title", re.compile(rf": over goal, {round(goal + 100):,} {of_goal}$")
        )
        expect(card.locator(".best")).to_have_text("Best 5 in 30")
        expect(card.locator(".count")).to_have_text("8")

        # Deleted, and the streak is back.
        home.ws({"type": "metron/entry/delete", "entry_id": over})
        expect(streak).to_have_text("3", timeout=TIMEOUT)
        expect(card.locator(".today-line")).to_have_text("Nothing logged today")
        expect(today_cell).to_have_class(has("pending"))

        # Under goal today: still pending, with what is left.
        eat(home, name, today(), 400)
        expect(card.locator(".today-line")).to_have_text(
            f"{round(goal - 400):,} kcal left today", timeout=TIMEOUT
        )
        expect(today_cell).to_have_attribute(
            "title", re.compile(rf": today, on goal so far, 400 {of_goal}$")
        )
        expect(streak).to_have_text("3")


def test_the_streak_card_shows_a_new_person_s_days_before_their_goals(
    home: Home, page: Page
) -> None:
    name = "Streak newcomer e2e"
    now = date.fromisoformat(today())
    yesterday = (now - timedelta(days=1)).isoformat()
    with person_named(home, name):
        # Food before the first goals counts for nothing.
        eat(home, name, yesterday, 500)
        card = open_card(home, page, {"type": "custom:metron-streak-card", "person": name})
        expect(card.locator(".cal")).to_have_attribute(
            "aria-label",
            f"{name}, the last 30 days: on goal 0, over goal 0, nothing logged 0. "
            "Current streak 0, best 0.",
            timeout=TIMEOUT,
        )
        expect(card.locator(".fig b")).to_have_text("0")
        expect(card.locator(".fig b")).not_to_have_class(has("live"))
        expect(card.locator(".best")).to_have_text("Best 0 in 30")
        expect(card.locator(".count")).to_have_text("0")
        expect(card.locator(".track i")).to_have_attribute("style", "width:0%")
        expect(card.locator(".today-line")).to_have_text("Nothing logged today")
        before = card.locator(f'.cell[data-day="{yesterday}"]')
        expect(before).to_have_class(has("before"))
        expect(before).to_have_attribute("title", re.compile(r": no goal yet$"))
        # Every day shown before today, from the Monday the calendar starts on.
        first = now - timedelta(days=29)
        expect(card.locator(".cell.before")).to_have_count(29 + first.weekday())
        expect(card.locator(".cell.today")).to_have_class(has("pending"))


def test_the_streak_card_moves_to_the_new_day_at_midnight(home: Home, page: Page) -> None:
    midnight = datetime.now(ZoneInfo("Europe/London")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    new_day = midnight.date()
    old_day = (new_day - timedelta(days=1)).isoformat()
    name = "Streak midnight e2e"
    with person_named(home, name):
        goals_since(home, name, (new_day - timedelta(days=3)).isoformat())
        for n in (1, 2):
            eat(home, name, (new_day - timedelta(days=n)).isoformat(), 500)
        # The browser's clock starts before last midnight, so the card first
        # takes yesterday for today, and counts its streak from the day before.
        page.clock.install(time=midnight - timedelta(minutes=5))
        card = open_card(home, page, {"type": "custom:metron-streak-card", "person": name})
        expect(card.locator(".fig b")).to_have_text("1", timeout=TIMEOUT)
        expect(card.locator(".cell.today")).to_have_attribute("data-day", old_day)
        expect(card.locator(".count")).to_have_text("1")

        page.clock.fast_forward("05:10")
        # Any new state reaches the card, as Metron's own sensors' do at midnight.
        home.api("POST", "/api/states/sensor.e2e_streak_clock", {"state": "midnight"})

        expect(card.locator(".fig b")).to_have_text("2", timeout=TIMEOUT)
        expect(card.locator(".cell.today")).to_have_attribute("data-day", new_day.isoformat())
        expect(card.locator(f'.cell[data-day="{old_day}"]')).to_have_class(has("good"))
        expect(card.locator(".count")).to_have_text("2")


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
    "4000417025005": {
        "product_name": "Dark chocolate 70%",
        "brands": "Ritter Sport",
        "nutriments": {
            "energy-kcal_100g": 598,
            "proteins_100g": 7.8,
            "carbohydrates_100g": 46,
            "fat_100g": 43,
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
    # Only scanned in the saved foods card, so never saved before it is.
    "40000000000600": {
        "product_name": "Rye crispbread",
        "brands": "Nordic",
        "nutriments": {
            "energy-kcal_100g": 334,
            "proteins_100g": 9,
            "carbohydrates_100g": 58,
            "fat_100g": 1.7,
        },
    },
    "40000000000501": {
        "product_name": "Kefir",
        "brands": "Mountain farm",
        "nutriments": {
            "energy-kcal_100g": 41,
            "proteins_100g": 3.4,
            "carbohydrates_100g": 4,
            "fat_100g": 1,
        },
    },
    "7613035974685": {
        "product_name": "Skyr nature",
        "brands": "Siggi's",
        "serving_quantity": 150,
        "nutriments": {
            "energy-kcal_100g": 63,
            "proteins_100g": 11,
            "carbohydrates_100g": 3.6,
            "fat_100g": 0.2,
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


def fake_camera(page: Page, code: str | None, *, refuse: bool = False) -> None:
    """A browser barcode reader that sees `code` (or nothing), and a camera.

    With `refuse`, the camera is denied, as when a person blocks it. Each
    stream the camera opens is kept in `window.cameraStreams`.
    """
    script = """
        (() => {
          window.BarcodeDetector = class {
            static async getSupportedFormats() { return ["ean_13", "ean_8"]; }
            async detect() { return CODE === null ? [] : [{ rawValue: CODE, format: "ean_13" }]; }
          };
          navigator.mediaDevices.getUserMedia = async () => {
            if (REFUSE) throw new DOMException("Permission denied", "NotAllowedError");
            const canvas = document.createElement("canvas");
            canvas.getContext("2d").fillRect(0, 0, 10, 10);
            const stream = canvas.captureStream();
            (window.cameraStreams ??= []).push(stream);
            return stream;
          };
        })();
    """
    page.add_init_script(
        script.replace("CODE", json.dumps(code)).replace("REFUSE", json.dumps(refuse))
    )


def wait_for_camera_off(page: Page) -> None:
    """Wait until every stream fake_camera's camera opened has stopped."""
    page.wait_for_function(
        "window.cameraStreams?.length && window.cameraStreams.every("
        "(s) => s.getTracks().every((t) => t.readyState === 'ended'))",
        timeout=TIMEOUT,
    )


def test_the_saved_foods_card_fills_a_food_from_its_barcode(home: Home, page: Page) -> None:
    asked = mock_open_food_facts(page)
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    search = card.locator('.panel [data-action="off-query"]')
    expect(search).to_be_focused()
    search.fill("5201054017111")
    look_up = card.locator('.panel .off [data-action="off-find"]')
    expect(look_up).to_have_text("Look up 5201054017111 on Open Food Facts")
    look_up.click()
    form = card.locator(".foodform")
    expect(card.locator(".panel .note")).to_contain_text("Filled in from Open Food Facts")
    review = card.locator(".panel .review")
    expect(review).to_contain_text(f"Greek yogurt 2% {DASH} Fage")
    expect(review).to_contain_text("5201054017111")
    expect(review.locator(".preview")).to_contain_text("73")
    expect(review).to_contain_text("Serving · 170 g")
    expect(form).to_have_count(0)
    assert asked == ["5201054017111"]
    card.locator('[data-action="save"]').click()
    expect(card.locator(".panel")).to_be_hidden(timeout=TIMEOUT)
    saved = home.ws({"type": "metron/food/barcode", "barcode": "5201054017111"})
    assert saved["name"] == f"Greek yogurt 2% {DASH} Fage"
    assert saved["portions"] == [{"name": "Serving", "grams": 170}]

    # Looking the same barcode up again, with Enter, opens the saved food.
    card.locator('[data-action="new"]').click()
    search.fill("5201054017111")
    search.press("Enter")
    expect(card.locator(".panel .note")).to_contain_text("already has this barcode")
    expect(card.locator('[data-action="delete"]')).to_be_visible()

    # A saved food looks its barcode up from its form.
    form.locator('[data-field="barcode"]').fill("123")
    form.locator('[data-action="lookup"]').click()
    expect(card.locator(".panel .error")).to_contain_text("8 to 14 digits")


def test_the_diary_looks_up_a_typed_barcode_it_does_not_have(home: Home, page: Page) -> None:
    mock_open_food_facts(page)
    card = diary(home, page, "Debora")
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("8076809513753")
    expect(card.locator(".results")).to_contain_text("No saved food matches", timeout=TIMEOUT)
    link = card.locator('.find [data-action="off-find"]')
    expect(link).to_have_text("Look up 8076809513753 on Open Food Facts")
    link.click()
    expect(card.locator('[data-action="tab"][data-tab="new"]')).to_have_attribute(
        "aria-selected", "true"
    )
    # The barcode goes into the food, and the search box empties.
    expect(card.locator('[data-action="off-query"]')).to_have_value("")
    review = card.locator(".panel .review")
    expect(review).to_contain_text("8076809513753")
    expect(review).to_contain_text(f"Spaghetti n.5 {DASH} Barilla")
    expect(card.locator(".panel .note")).to_contain_text("Filled in from Open Food Facts")
    card.locator('[data-action="save-new-food"]').click()
    # The food is saved now, so the note about the form's values goes.
    expect(card.locator(".picked")).to_contain_text("Spaghetti n.5", timeout=TIMEOUT)
    expect(card.locator(".panel .note")).to_have_count(0)
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
    card.locator('.find [data-action="off-find"]').click()
    expect(card.locator(".panel .error")).to_contain_text("does not know barcode 40000000000099")
    expect(card.locator('.foodform [data-field="barcode"]')).to_have_value("40000000000099")


def test_scanning_with_the_browser_reads_the_barcode(home: Home, page: Page) -> None:
    mock_open_food_facts(page)
    fake_camera(page, "40000000000600")
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    expect(card.locator('.foodform [data-action="scan"]')).to_have_count(0)
    card.locator('[data-action="off-scan"]').click()
    review = card.locator(".panel .review")
    expect(review).to_contain_text("40000000000600", timeout=TIMEOUT)
    expect(review).to_contain_text(f"Rye crispbread {DASH} Nordic")
    expect(card.locator(".scanner")).to_be_hidden()
    # Edit values opens the whole form, filled in.
    review.locator('[data-action="edit-values"]').click()
    form = card.locator(".foodform")
    expect(form.locator('[data-field="barcode"]')).to_have_value("40000000000600")
    expect(form.locator('[data-field="name"]')).to_be_focused()


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
    save_food(home, "No scanner e2e")
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    expect(card.locator('.panel [data-action="off-query"]')).to_be_visible()
    expect(card.locator('.panel [data-action="off-scan"]')).to_have_count(0)
    expect(card.locator('.panel [data-action="lookup"]')).to_have_count(0)
    card.locator('.panel [data-action="close"]').click()
    card.locator('[data-action="query"]').fill("No scanner e2e")
    card.locator(".row", has_text="No scanner e2e").click()
    expect(card.locator('.panel [data-action="lookup"]')).to_be_visible()
    expect(card.locator('.panel [data-action="scan"]')).to_have_count(0)
    expect(card.locator('.panel [data-action="off-query"]')).to_have_count(0)

    card = diary(home, page, "Debora")
    meal(card, "lunch").locator('[data-action="add"]').click()
    expect(card.locator('.panel [data-action="query"]')).to_be_visible()
    expect(card.locator('.panel [data-action="scan"]')).to_have_count(0)
    card.locator('[data-action="tab"][data-tab="new"]').click()
    expect(card.locator('.panel [data-action="off-query"]')).to_be_visible()
    expect(card.locator('.panel [data-action="off-scan"]')).to_have_count(0)


def test_the_diary_s_calendar_and_cancel(home: Home, page: Page) -> None:
    yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    card = diary(home, page, "Matteo")
    card.locator('[data-action="pick-day"]').fill(yesterday)
    expect(card.locator(".nav .label")).to_have_text("Yesterday")
    meal(card, "lunch").locator('[data-action="add"]').click()
    expect(card.locator(".panel")).to_be_visible()
    card.locator('.panel .mealhead [data-action="close"]').click()
    expect(card.locator(".panel")).to_be_hidden()


@ON_A_PHONE_TOO
def test_portions_and_meal_can_change_before_adding(home: Home, page: Page, on: str) -> None:
    save_food(
        home,
        f"Sliced bread e2e {on}",
        portions=[{"name": "Slice", "grams": 36}, {"name": "Half slice", "grams": 18}],
    )
    card = diary(home, page, "Matteo")
    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill(f"Sliced bread e2e {on}")
    card.locator('[data-action="choose"]', has_text=f"Sliced bread e2e {on}").click()
    expect(card.locator('[data-field="grams"]')).to_have_value("36")
    card.locator('[data-action="portion"]', has_text="Half slice").click()
    expect(card.locator('[data-field="grams"]')).to_have_value("18")
    card.locator('.picked [data-field="meal"]').select_option("lunch")
    expect(card.locator('[data-action="add-entry"]')).to_have_text("Add to Lunch")
    card.locator('[data-action="add-entry"]').click()
    row = meal(card, "lunch").locator(".row", has_text=f"Sliced bread e2e {on}")
    expect(row).to_contain_text("18 g", timeout=TIMEOUT)


def test_the_new_food_tab_edits_portions_and_finds_saved_barcodes(home: Home, page: Page) -> None:
    save_food(home, "Known oats e2e", barcode="96385074")
    card = diary(home, page, "Debora")
    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    card.locator('[data-action="add-portion"]').click()
    expect(card.locator(".foodform .portion")).to_have_count(1)
    card.locator('[data-action="remove-portion"]').click()
    expect(card.locator(".foodform .portion")).to_have_count(0)

    # The search box takes a barcode, and a saved food's opens that food.
    expect(card.locator('.foodform [data-action="lookup"]')).to_have_count(0)
    card.locator('[data-action="off-query"]').fill("96385074")
    card.locator('[data-action="off-query"]').press("Enter")
    expect(card.locator(".panel .note")).to_contain_text("Known oats e2e already has this barcode")
    expect(card.locator('[data-action="tab"][data-tab="search"]')).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.locator(".picked")).to_contain_text("Known oats e2e")


def test_the_new_food_tab_scans_a_barcode_straight_into_a_short_check(
    home: Home, page: Page
) -> None:
    asked = mock_open_food_facts(page)
    # A product no other test saves, so the scan fills a new food.
    fake_camera(page, "4000417025005")
    card = diary(home, page, "Debora")
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    expect(card.locator('.panel [data-action="off-scan"]')).to_have_count(0)
    search = card.locator('[data-action="off-query"]')
    search.fill("dark chocolate")
    card.locator('.panel .headactions [data-action="scan"]').click()
    review = card.locator(".panel .review")
    expect(review).to_contain_text("4000417025005", timeout=TIMEOUT)
    expect(review.locator(".preview")).to_contain_text("598")
    expect(card.locator(".panel .note")).to_contain_text("Filled in from Open Food Facts")
    # The scan replaces what was typed in the search box.
    expect(search).to_have_value("")
    expect(card.locator(".panel .off")).to_have_text(
        "Type a product's name or barcode, or fill in the form from the label."
    )
    expect(card.locator(".scanner")).to_be_hidden()
    assert asked == ["4000417025005"]


@pytest.mark.parametrize("where", ["diary", "new food", "foods"])
def test_a_scan_can_be_cancelled(home: Home, page: Page, where: str) -> None:
    fake_camera(page, None)
    if where == "foods":
        card = open_card(home, page, {"type": "custom:metron-foods-card"})
        card.locator('[data-action="new"]').click()
    else:
        card = diary(home, page, "Debora")
        meal(card, "lunch").locator('[data-action="add"]').click()
    if where == "new food":
        card.locator('[data-action="tab"][data-tab="new"]').click()
    query = card.locator('.panel [data-action="query"], .panel [data-action="off-query"]')
    query.fill("before")
    scan = '[data-action="off-scan"]' if where == "foods" else '.headactions [data-action="scan"]'
    card.locator(f".panel {scan}").click()
    expect(card.locator(".scanner video")).to_be_visible(timeout=TIMEOUT)
    card.locator('[data-action="stop-scan"]').click()
    expect(card.locator(".scanner")).to_be_hidden(timeout=TIMEOUT)
    expect(query).to_have_value("before")
    wait_for_camera_off(page)


def test_a_blocked_camera_is_explained(home: Home, page: Page) -> None:
    fake_camera(page, "12345670", refuse=True)
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    card.locator('[data-action="off-scan"]').click()
    expect(card.locator(".panel .error")).to_contain_text(
        "Could not use the camera: Permission denied", timeout=TIMEOUT
    )


def test_an_unreachable_open_food_facts_is_explained(home: Home, page: Page) -> None:
    page.route("https://world.openfoodfacts.org/**", lambda route: route.abort())
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    card.locator('.panel [data-action="off-query"]').fill("40000000000105")
    card.locator('.panel [data-action="off-query"]').press("Enter")
    expect(card.locator(".panel .error")).to_contain_text(
        "Could not reach Open Food Facts", timeout=TIMEOUT
    )
    expect(card.locator('.foodform [data-field="barcode"]')).to_have_value("40000000000105")


def hit(code: str, name: str, kcal: float, **more) -> dict:
    """A product as Open Food Facts' search gives it."""
    return {
        "code": code,
        "product_name": name,
        "brands": ["Test dairy"],
        "quantity": "500 g",
        "nutriments": {
            "energy-kcal_100g": kcal,
            "proteins_100g": 10,
            "carbohydrates_100g": 4,
            "fat_100g": 0.2,
        },
        **more,
    }


def test_the_diary_searches_open_food_facts_by_name(
    home: Home, page: Page, search: FakeSearch
) -> None:
    looked_up = mock_open_food_facts(page)
    # A page of ten, then two more. The last is one the barcode lookup knows,
    # with newer values than the search's.
    products = [hit(f"20000000000{n:02}", f"Skyr e2e {n}", 60 + n) for n in range(11)]
    products.append(hit("7613035974685", "Skyr e2e nature", 60))
    search.find(products)
    card = diary(home, page, "Debora")
    meal(card, "breakfast").locator('[data-action="add"]').click()
    expect(card.locator(".results")).to_contain_text("Recent", timeout=TIMEOUT)
    expect(card.locator(".find")).to_be_empty()

    # Saved foods searches only saved foods, and links to Open Food Facts.
    card.locator('[data-action="query"]').fill("skyr e2e")
    expect(card.locator(".results")).to_contain_text("No saved food matches", timeout=TIMEOUT)
    link = card.locator('.find [data-action="off-find"]')
    expect(link).to_have_text("Search Open Food Facts for “skyr e2e”")
    expect(card.locator('[data-action="off-pick"]')).to_have_count(0)
    assert search.asked == []

    # The link searches from New food.
    link.click()
    expect(card.locator('[data-action="tab"][data-tab="new"]')).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.locator('[data-action="off-query"]')).to_have_value("skyr e2e")
    rows = card.locator('[data-action="off-pick"]')
    expect(rows).to_have_count(10, timeout=TIMEOUT)
    expect(rows.first).to_have_text(
        re.compile(r"Skyr e2e 0\s+Test dairy · 500 g\s+60 kcal per 100 g")
    )
    asked = search.asked[0]
    assert asked["q"].startswith("skyr e2e nutriments.energy-kcal_100g:[0 TO *] ")
    assert (asked["langs"], asked["page"], asked["page_size"]) == ("en", "1", "10")

    card.locator('[data-action="off-next"]').click()
    expect(rows).to_have_count(12, timeout=TIMEOUT)
    expect(card.locator('[data-action="off-next"]')).to_have_count(0)
    assert search.asked[1]["page"] == "2"

    # Picking looks the barcode up for current values, as a lookup does.
    rows.last.click()
    review = card.locator(".panel .review")
    expect(review).to_contain_text(f"Skyr nature {DASH} Siggi's", timeout=TIMEOUT)
    expect(review.locator(".preview")).to_contain_text("63")
    expect(review).to_contain_text("7613035974685")
    expect(review).to_contain_text("Serving · 150 g")
    expect(card.locator(".panel .note")).to_contain_text("Filled in from Open Food Facts")
    expect(card.locator(".panel .warning")).to_have_count(0)
    assert looked_up == ["7613035974685"]
    # The products stay, to pick another, and nothing is saved until asked.
    expect(rows).to_have_count(12)
    assert home.ws({"type": "metron/food/barcode", "barcode": "7613035974685"}) is None

    card.locator('[data-action="save-new-food"]').click()
    card.locator('[data-field="grams"]').fill("100")
    card.locator('[data-action="add-entry"]').click()
    row = meal(card, "breakfast").locator(".row", has_text="Skyr nature")
    expect(row).to_contain_text("63", timeout=TIMEOUT)


@pytest.mark.parametrize("lookup", ["unknown", "unreachable"])
def test_a_failed_lookup_fills_the_food_from_the_search_with_a_warning(
    home: Home, page: Page, search: FakeSearch, lookup: str
) -> None:
    if lookup == "unknown":
        mock_open_food_facts(page)
        code = "40000000000310"
    else:
        page.route("https://world.openfoodfacts.org/**", lambda route: route.abort())
        code = "40000000000327"
    search.find([hit(code, f"Old crackers e2e {lookup}", 421, brands=["Crunchy"], quantity="")])
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="query"]').fill(f"crackers e2e {lookup}")
    card.locator('.find [data-action="off-find"]').click()
    card.locator('[data-action="off-pick"]').click()

    review = card.locator(".panel .review")
    expect(review).to_contain_text(f"Old crackers e2e {lookup} {DASH} Crunchy", timeout=TIMEOUT)
    expect(review.locator(".preview")).to_contain_text("421")
    expect(review).to_contain_text(code)
    expect(review.locator(".chip")).to_have_count(0)
    expect(card.locator(".panel .warning")).to_have_text(
        "Filled in from an Open Food Facts search, whose values may be out of date. "
        "Check them against the label."
    )
    expect(card.locator(".panel .error")).to_have_count(0)
    card.locator('[data-action="save"]').click()
    expect(card.locator(".panel")).to_be_hidden(timeout=TIMEOUT)
    assert home.ws({"type": "metron/food/barcode", "barcode": code})["kcal"] == 421


def test_a_failed_search_can_be_retried_and_may_find_nothing(
    home: Home, page: Page, search: FakeSearch
) -> None:
    card = diary(home, page, "Matteo")
    meal(card, "lunch").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("nothing e2e")
    # The fake fails every search until it is told what to find.
    card.locator('.find [data-action="off-find"]').click()
    expect(card.locator(".off .error")).to_have_text(
        "Could not search Open Food Facts: HTTP 503", timeout=TIMEOUT
    )
    search.find([])
    card.locator('.off [data-action="off-next"]', has_text="Try again").click()
    expect(card.locator(".off")).to_contain_text(
        "Open Food Facts has no product matching \u201cnothing e2e\u201d "
        "with kcal, protein, carbs and fat.",
        timeout=TIMEOUT,
    )
    assert [a["page"] for a in search.asked] == ["1", "1"]


def test_searches_open_food_facts_in_the_card_s_language(
    home: Home, page: Page, search: FakeSearch
) -> None:
    search.find(
        [
            hit(
                "40000000000334",
                "Yoghurt",
                97,
                product_name_it="Yogurt greco e2e",
                product_name_en="Greek yogurt e2e",
            )
        ]
    )
    card = open_card(
        home,
        page,
        {"type": "custom:metron-food-diary-card", "person": "Debora", "locale": "it"},
    )
    meal(card, "dinner").locator('[data-action="add"]').click()
    card.locator('[data-action="query"]').fill("yogurt greco")
    card.locator('.find [data-action="off-find"]').click()
    expect(card.locator('[data-action="off-pick"]')).to_contain_text(
        "Yogurt greco e2e", timeout=TIMEOUT
    )
    assert search.asked[0]["langs"] == "it,en"
    assert search.asked[0]["fields"] == (
        "code,product_name,product_name_it,product_name_en,brands,quantity,nutriments"
    )


def test_picking_a_product_already_saved_opens_the_saved_food(
    home: Home, page: Page, search: FakeSearch
) -> None:
    mock_open_food_facts(page)
    save_food(home, "Saved skyr e2e", barcode="40000000000341")
    search.find([hit("40000000000341", "Skyr e2e already saved", 60)])
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="query"]').fill("skyr e2e already saved")
    card.locator('.find [data-action="off-find"]').click()
    card.locator('[data-action="off-pick"]').click()
    expect(card.locator(".panel .note")).to_contain_text(
        "Saved skyr e2e already has this barcode", timeout=TIMEOUT
    )
    expect(card.locator('[data-action="delete"]')).to_be_visible()


@pytest.mark.parametrize("where", ["diary", "foods"])
def test_searching_saved_foods_shows_only_saved_foods(
    home: Home, page: Page, search: FakeSearch, where: str
) -> None:
    code = {"diary": "40000000000440", "foods": "40000000000457"}[where]
    name = f"Crunchy oats e2e {where}"
    save_food(home, name, barcode=code)
    search.find([hit("40000000000464", "Crunchy oats e2e elsewhere", 420)])
    if where == "diary":
        card = diary(home, page, "Matteo")
        meal(card, "breakfast").locator('[data-action="add"]').click()
        found = card.locator(".results")
    else:
        card = open_card(home, page, {"type": "custom:metron-foods-card"})
        found = card.locator(".list")
    query = card.locator('[data-action="query"]')
    link = card.locator('.find [data-action="off-find"]')

    # A saved food that matches still leaves a way to other products.
    query.fill(f"crunchy oats e2e {where}")
    expect(found).to_contain_text(name, timeout=TIMEOUT)
    expect(link).to_have_text(f"Search Open Food Facts for “crunchy oats e2e {where}”")
    # A barcode that a saved food has needs no lookup.
    query.fill(code)
    expect(found).to_contain_text(name, timeout=TIMEOUT)
    expect(link).to_have_count(0)
    # What was typed reaches the search as it is.
    query.fill('oats "<e2e>"')
    expect(link).to_have_text('Search Open Food Facts for “oats "<e2e>"”', timeout=TIMEOUT)
    expect(card.locator('[data-action="off-pick"]')).to_have_count(0)
    assert search.asked == []
    link.click()
    expect(card.locator('.panel [data-action="off-query"]')).to_have_value('oats "<e2e>"')
    expect(card.locator('[data-action="off-pick"]')).to_have_count(1, timeout=TIMEOUT)
    assert len(search.asked) == 1


def test_new_food_searches_on_enter_and_keeps_the_form(
    home: Home, page: Page, search: FakeSearch
) -> None:
    search.find(
        [
            hit("40000000000471", "Quark e2e plain", 67),
            hit("40000000000488", "Quark e2e vanilla", 98),
        ]
    )
    card = diary(home, page, "Matteo")
    meal(card, "snacks").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    hint = "Type a product's name or barcode, or fill in the form from the label."
    expect(card.locator(".panel .off")).to_have_text(hint)
    form = card.locator(".foodform")
    form.locator('[data-field="name"]').fill("My own quark e2e")
    form.locator('[data-field="kcal"]').fill("70")
    box = card.locator('[data-action="off-query"]')
    button = card.locator('.panel .off [data-action="off-find"]')

    # Enter on an empty box does nothing.
    box.press("Enter")
    expect(card.locator(".panel .off")).to_have_text(hint)
    box.fill("quark e2e")
    expect(button).to_have_text("Search Open Food Facts for “quark e2e”")
    assert search.asked == []
    box.press("Enter")
    rows = card.locator('[data-action="off-pick"]')
    expect(rows).to_have_count(2, timeout=TIMEOUT)
    assert len(search.asked) == 1
    # Searching keeps what was typed in the form.
    expect(form.locator('[data-field="name"]')).to_have_value("My own quark e2e")
    expect(form.locator('[data-field="kcal"]')).to_have_value("70")

    # Another tab and back keeps the search.
    card.locator('[data-action="tab"][data-tab="quick"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    expect(box).to_have_value("quark e2e")
    expect(rows).to_have_count(2)

    # Typing more puts the results out of date until searched again.
    box.fill("quark e2e vanilla")
    expect(rows).to_have_count(0)
    expect(button).to_have_text("Search Open Food Facts for “quark e2e vanilla”")
    assert len(search.asked) == 1
    button.click()
    expect(rows).to_have_count(2, timeout=TIMEOUT)
    assert len(search.asked) == 2


def test_scanning_a_saved_food_on_new_food_chooses_it(home: Home, page: Page) -> None:
    save_food(
        home,
        "Scanned muesli e2e",
        barcode="40000000000495",
        portions=[{"name": "Bowl", "grams": 45}],
    )
    fake_camera(page, "40000000000495")
    card = diary(home, page, "Matteo")
    meal(card, "breakfast").locator('[data-action="add"]').click()
    card.locator('[data-action="tab"][data-tab="new"]').click()
    card.locator('.panel .headactions [data-action="scan"]').click()
    expect(card.locator(".panel .note")).to_contain_text(
        "Scanned muesli e2e already has this barcode", timeout=TIMEOUT
    )
    expect(card.locator('[data-action="tab"][data-tab="search"]')).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.locator(".picked")).to_contain_text("Scanned muesli e2e")
    expect(card.locator('[data-field="grams"]')).to_have_value("45")


@pytest.mark.parametrize("how", ["diary", "diary tab", "foods", "foods edit"])
def test_leaving_a_scan_stops_the_camera(home: Home, page: Page, how: str) -> None:
    fake_camera(page, None)
    if how.startswith("diary"):
        card = diary(home, page, "Debora")
        meal(card, "lunch").locator('[data-action="add"]').click()
        card.locator('[data-action="tab"][data-tab="new"]').click()
        scan = '.headactions [data-action="scan"]'
    elif how == "foods":
        card = open_card(home, page, {"type": "custom:metron-foods-card"})
        card.locator('[data-action="new"]').click()
        scan = '[data-action="off-scan"]'
    else:
        save_food(home, "Scan then close e2e")
        card = open_card(home, page, {"type": "custom:metron-foods-card"})
        card.locator('[data-action="query"]').fill("Scan then close e2e")
        card.locator(".row", has_text="Scan then close e2e").click()
        scan = '[data-action="scan"]'
    # Errors from here on: the scan, and leaving it.
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    card.locator(f".panel {scan}").click()
    expect(card.locator(".scanner video")).to_be_visible(timeout=TIMEOUT)
    if how == "diary tab":
        card.locator('[data-action="tab"][data-tab="quick"]').click()
        expect(card.locator(".scanner video")).to_have_count(0)
    else:
        card.locator('.panel [data-action="close"]').first.click()
        expect(card.locator(".panel")).to_be_hidden()
    wait_for_camera_off(page)
    assert errors == []


def test_the_saved_foods_card_finds_a_new_food_on_open_food_facts(
    home: Home, page: Page, search: FakeSearch
) -> None:
    looked_up = mock_open_food_facts(page)
    search.find([hit("40000000000501", "Kefir e2e", 41)])
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="query"]').fill("kefir e2e")
    expect(card.locator(".list")).to_contain_text("No saved food matches", timeout=TIMEOUT)
    expect(card.locator('[data-action="off-pick"]')).to_have_count(0)
    card.locator('.find [data-action="off-find"]').click()
    panel = card.locator(".panel")
    expect(panel.locator(".title")).to_have_text("New food")
    expect(panel.locator('[data-action="off-query"]')).to_have_value("kefir e2e")
    rows = panel.locator('[data-action="off-pick"]')
    expect(rows).to_have_count(1, timeout=TIMEOUT)
    rows.click()
    form = panel.locator(".foodform")
    expect(panel.locator(".review")).to_contain_text(f"Kefir {DASH} Mountain farm", timeout=TIMEOUT)
    expect(rows).to_have_count(1)
    assert looked_up == ["40000000000501"]
    card.locator('[data-action="save"]').click()
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    card.locator('[data-action="query"]').fill("Mountain farm")
    expect(card.locator(".list")).to_contain_text("Kefir", timeout=TIMEOUT)

    # An open new food keeps what was typed in it when the link searches.
    card.locator('[data-action="new"]').click()
    form.locator('[data-field="name"]').fill("Half typed e2e")
    card.locator('[data-action="query"]').fill("kefir again e2e")
    link = card.locator('.find [data-action="off-find"]')
    expect(link).to_have_text("Search Open Food Facts for “kefir again e2e”", timeout=TIMEOUT)
    link.click()
    expect(panel.locator('[data-action="off-query"]')).to_have_value("kefir again e2e")
    expect(form.locator('[data-field="name"]')).to_have_value("Half typed e2e")

    # A saved food has no search, and looks barcodes up from its form.
    panel.locator('[data-action="close"]').click()
    card.locator('[data-action="query"]').fill("Mountain farm")
    card.locator(".row", has_text="Kefir").click()
    expect(panel.locator('[data-action="off-query"]')).to_have_count(0)
    expect(panel.locator('[data-action="lookup"]')).to_be_visible()


def test_the_saved_foods_form_removes_portions_and_cancels(home: Home, page: Page) -> None:
    card = open_card(home, page, {"type": "custom:metron-foods-card"})
    card.locator('[data-action="new"]').click()
    card.locator('[data-action="add-portion"]').click()
    card.locator('[data-action="add-portion"]').click()
    card.locator(".foodform .portion").first.locator('[data-portion="name"]').fill("Keep")
    card.locator(".foodform .portion").nth(1).locator('[data-action="remove-portion"]').click()
    expect(card.locator(".foodform .portion")).to_have_count(1)
    expect(card.locator('.foodform [data-portion="name"]')).to_have_value("Keep")
    card.locator('.panel [data-action="close"]').click()
    expect(card.locator(".panel")).to_be_hidden()


def test_the_weight_card_switches_range(home: Home, page: Page) -> None:
    card = open_card(home, page, {"type": "custom:metron-weight-card", "person": "Matteo"})
    for value in ("all", "365", "90"):
        card.locator(f'[data-action="range"][data-range="{value}"]').click()
        expect(card.locator(f'[data-action="range"][data-range="{value}"]')).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(card.locator(".chart")).to_be_visible()
