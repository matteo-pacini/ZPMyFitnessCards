"""README screenshots, taken from a brand-new Home Assistant with sample data.

Run with scripts/screenshots, which writes them to images/. The file name has
no test_ prefix, so the normal test runs skip it.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Browser, Page, expect

from .conftest import REPO, Home

IMAGES = REPO / "images"

# Sample foods per 100 g, with the grams eaten today by meal.
FOODS = [
    ("Porridge oats", 389, 16.9, 66, 6.9, [("Bowl", 40)], "breakfast", 60),
    ("Greek yogurt 2%", 73, 10, 3.6, 2, [("Pot", 170)], "breakfast", 170),
    ("Banana", 89, 1.1, 23, 0.3, [("Medium", 120)], "breakfast", 120),
    ("Chicken breast, grilled", 165, 31, 0, 3.6, [], "lunch", 150),
    ("Basmati rice, cooked", 130, 2.7, 28, 0.3, [], "lunch", 180),
    ("Broccoli", 34, 2.8, 7, 0.4, [], "lunch", 120),
    ("Olive oil", 884, 0, 0, 100, [("Tablespoon", 13.5)], "lunch", 10),
    ("Almonds", 579, 21, 22, 50, [("Handful", 25)], "snacks", 25),
    ("Salmon fillet", 208, 20, 0, 13, [], None, None),
    ("Wholemeal bread", 247, 13, 41, 3.4, [("Slice", 36)], None, None),
]


@pytest.fixture(scope="module")
def sample(home: Home) -> Home:
    """Debora's day so far, logged from saved foods."""
    debora = next(
        p["id"] for p in home.ws({"type": "zp_my_fitness/people"}) if p["name"] == "Debora"
    )
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    for name, kcal, protein, carbs, fat, portions, meal, grams in FOODS:
        food = home.ws(
            {
                "type": "zp_my_fitness/food/add",
                "name": name,
                "kcal": kcal,
                "protein": protein,
                "carbs": carbs,
                "fat": fat,
                "portions": [{"name": n, "grams": g} for n, g in portions],
            }
        )
        if meal:
            home.ws(
                {
                    "type": "zp_my_fitness/entry/add",
                    "person": debora,
                    "day": today,
                    "meal": meal,
                    "food_id": food["id"],
                    "grams": grams,
                }
            )
    # A year of Matteo weighing in every few days, slowly losing weight.
    matteo = next(
        p["id"] for p in home.ws({"type": "zp_my_fitness/people"}) if p["name"] == "Matteo"
    )
    first = date.fromisoformat(today) - timedelta(days=360)
    for n in range(0, 361, 4):
        wobble = ((n * 37) % 11 - 5) / 10
        home.ws(
            {
                "type": "zp_my_fitness/weight/set",
                "person": matteo,
                "day": (first + timedelta(days=n)).isoformat(),
                "kg": round(95 - n * 0.018 + wobble, 1),
            }
        )
    for n, kg in enumerate((69.8, 69.6, 69.7, 69.4, 69.2, 69.3, 69.0, 68.9)):
        day = (date.fromisoformat(today) - timedelta(days=28 - n * 4)).isoformat()
        home.ws({"type": "zp_my_fitness/weight/set", "person": debora, "day": day, "kg": kg})
    # Four weeks of Debora's meals before today, as quick adds.
    for n in range(1, 29):
        day = (date.fromisoformat(today) - timedelta(days=n)).isoformat()
        for meal, kcal in zip(
            ("breakfast", "lunch", "dinner", "snacks"),
            (380 + (n * 53) % 120, 560 + (n * 71) % 220, 620 + (n * 97) % 330, (n * 31) % 260),
            strict=True,
        ):
            home.ws(
                {
                    "type": "zp_my_fitness/entry/add",
                    "person": debora,
                    "day": day,
                    "meal": meal,
                    "name": "Sample",
                    "kcal": kcal,
                    "protein": kcal * 0.05,
                    "carbs": kcal * 0.12,
                    "fat": kcal * 0.035,
                }
            )
    return home


def shoot(
    home: Home, browser: Browser, card: dict, name: str, *, dark=False, width=480, setup=None
):
    context = browser.new_context(
        viewport={"width": width, "height": 1400},
        device_scale_factor=2,
        color_scheme="dark" if dark else "light",
    )
    page: Page = context.new_page()
    stored = {**home.tokens, "hassUrl": home.url, "clientId": home.url + "/"}
    stored["expires"] = int(datetime.now().timestamp() * 1000) + home.tokens["expires_in"] * 1000
    page.add_init_script(f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(stored))})")
    home.dashboard([card])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    element = page.locator(card["type"].removeprefix("custom:"))
    expect(element.locator(".title").first).to_be_visible(timeout=30_000)
    page.wait_for_timeout(500)
    if setup:
        setup(element)
        page.wait_for_timeout(500)
    IMAGES.mkdir(exist_ok=True)
    element.locator("ha-card").screenshot(path=str(IMAGES / f"{name}.png"), animations="disabled")
    context.close()


DIARY = {"type": "custom:zp-food-diary-card", "person": "Debora"}
FOODS_CARD = {"type": "custom:zp-foods-card"}
WEIGHT = {"type": "custom:zp-weight-card", "person": "Matteo"}
TRENDS = {"type": "custom:zp-trends-card", "person": "Debora"}
SUMMARY = {"type": "custom:zp-summary-card", "person": "Debora"}


def look_up_barcode(card) -> None:
    """Fill a new food from a barcode, with Open Food Facts answered locally."""
    card.page.route(
        "https://world.openfoodfacts.org/**",
        lambda route: route.fulfill(
            headers={"Access-Control-Allow-Origin": "*"},
            json={
                "status": 1,
                "product": {
                    "product_name": "Greek yogurt 2%",
                    "brands": "Fage",
                    "serving_quantity": 170,
                    "nutriments": {
                        "energy-kcal_100g": 73,
                        "proteins_100g": 10,
                        "carbohydrates_100g": 3.6,
                        "fat_100g": 2,
                        "sugars_100g": 3.6,
                        "saturated-fat_100g": 1.3,
                        "salt_100g": 0.1,
                    },
                },
            },
        ),
    )
    card.locator('[data-action="new"]').click()
    card.locator('.foodform [data-field="barcode"]').fill("5201054017111")
    card.locator('[data-action="lookup"]').click()
    card.locator(".panel .note").wait_for()


def pick_range(value: str):
    def setup(card) -> None:
        card.locator(f'[data-action="range"][data-range="{value}"]').click()

    return setup


def open_add(card) -> None:
    card.locator('.meal[data-meal="dinner"] [data-action="add"]').click()
    card.locator('[data-action="query"]').fill("salmon")
    card.locator('[data-action="choose"]', has_text="Salmon fillet").click(timeout=10_000)
    card.locator('[data-field="grams"]').fill("140")


def test_screenshots(sample: Home, browser: Browser) -> None:
    shoot(sample, browser, DIARY, "food-diary")
    shoot(sample, browser, DIARY, "food-diary-dark", dark=True)
    shoot(sample, browser, DIARY, "food-diary-add", setup=open_add)
    shoot(sample, browser, FOODS_CARD, "saved-foods")
    shoot(sample, browser, FOODS_CARD, "barcode-lookup", setup=look_up_barcode)
    shoot(sample, browser, WEIGHT, "weight", setup=pick_range("365"))
    shoot(sample, browser, TRENDS, "trends", setup=pick_range("30"))
    shoot(sample, browser, TRENDS, "trends-week")
    shoot(sample, browser, SUMMARY, "summary")
    shoot(sample, browser, SUMMARY, "summary-dark", dark=True)
    assert sorted(p.name for p in IMAGES.glob("*.png")) == sorted(
        f"{n}.png"
        for n in (
            "food-diary",
            "food-diary-dark",
            "food-diary-add",
            "saved-foods",
            "barcode-lookup",
            "weight",
            "trends",
            "trends-week",
            "summary",
            "summary-dark",
        )
    )
