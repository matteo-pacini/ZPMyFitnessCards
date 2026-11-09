"""README screenshots, taken from a brand-new Home Assistant with sample data.

Run with scripts/screenshots, which writes them to images/. The file name has
no test_ prefix, so the normal test runs skip it.
"""

from __future__ import annotations

import json
from datetime import datetime
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
    assert sorted(p.name for p in IMAGES.glob("*.png")) == sorted(
        f"{n}.png"
        for n in (
            "food-diary",
            "food-diary-dark",
            "food-diary-add",
            "saved-foods",
        )
    )
