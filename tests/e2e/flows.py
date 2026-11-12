"""Saved meals and one Scan, as people use them: the draft's happy paths and edge cases.

Each flow runs on a Screen: a browser on a laptop, a phone-sized browser with
touch, or the Home Assistant app on Android (tests/e2e/test_android.py). The
flows are H1 to H10 and E1 to E10 of the saved meals draft, in that order.

Tests share one Home Assistant, so each flow logs on a day of its own, long
past, and names what it saves with the screen's tag. Barcodes differ by flow
and screen, so no flow finds what another saved.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, Route, expect

from .conftest import FakeSearch, Home

TIMEOUT = 15_000
KINDS = ["laptop", "phone", "app"]

# Open Food Facts joins a product's name and brand with an en dash.
EXTERNAL = 'document.querySelector("home-assistant").hass.auth.external'
DASH = "\u2013"
CORS = {"Access-Control-Allow-Origin": "*"}

# A browser barcode reader that reads `window.fakeBarcode` once it is set,
# and a camera that, when `window.refuseCamera` is set, is blocked. Streams
# go in `window.cameraStreams`, to check the camera stops.
FAKE_CAMERA = """
(() => {
  window.fakeBarcode = null;
  window.BarcodeDetector = class {
    static async getSupportedFormats() { return ["ean_13", "ean_8"]; }
    async detect() {
      const code = window.fakeBarcode;
      window.fakeBarcode = null;
      return code === null ? [] : [{ rawValue: code, format: "ean_13" }];
    }
  };
  navigator.mediaDevices.getUserMedia = async () => {
    if (window.refuseCamera) throw new DOMException("Permission denied", "NotAllowedError");
    const canvas = document.createElement("canvas");
    canvas.getContext("2d").fillRect(0, 0, 10, 10);
    const stream = canvas.captureStream();
    (window.cameraStreams ??= []).push(stream);
    return stream;
  };
})();
"""


def today() -> str:
    # The test home is in London.
    return datetime.now(ZoneInfo("Europe/London")).date().isoformat()


def off_product(name: str, kcal: float, **more: Any) -> dict[str, Any]:
    """A product as Open Food Facts' barcode lookup gives it."""
    return {
        "product_name": name,
        "brands": "Test dairy",
        "serving_quantity": "150",
        "nutriments": {
            "energy-kcal_100g": kcal,
            "proteins_100g": 11,
            "carbohydrates_100g": 4,
            "fat_100g": 0.2,
        },
        **more,
    }


@dataclass
class OpenFoodFacts:
    """Open Food Facts' barcode lookup, as a page sees it.

    `products` maps a code to its product; other codes are unknown. A code in
    `failing` answers 503, and one in `slow` waits until released.
    """

    products: dict[str, dict] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    slow: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)
    held: list[tuple[Route, str]] = field(default_factory=list)

    def answer(self, route: Route) -> None:
        code = route.request.url.split("/product/")[1].split(".json")[0]
        self.asked.append(code)
        if code in self.slow:
            self.held.append((route, code))
            return
        self._fulfil(route, code)

    def _fulfil(self, route: Route, code: str) -> None:
        if code in self.failing:
            route.fulfill(status=503, json={"status": 0}, headers=CORS)
        elif code in self.products:
            route.fulfill(json={"status": 1, "product": self.products[code]}, headers=CORS)
        else:
            route.fulfill(status=404, json={"status": 0}, headers=CORS)

    def release(self) -> None:
        """Answer the lookups held back."""
        self.slow.clear()
        while self.held:
            self._fulfil(*self.held.pop(0))


@dataclass
class Screen:
    """Where a flow runs, and how a person there taps, types and scans."""

    home: Home
    page: Page
    kind: str
    open_card: Callable[[dict], Locator]
    off: OpenFoodFacts
    search: FakeSearch | None = None

    @property
    def tag(self) -> str:
        return self.kind

    @property
    def app(self) -> bool:
        return self.kind == "app"

    def day(self, flow: int) -> str:
        """The day flow `flow` logs on: its own, long past, for this screen."""
        offset = 200 + flow * 3 + KINDS.index(self.kind)
        return (date.fromisoformat(today()) - timedelta(days=offset)).isoformat()

    def barcode(self, flow: int, n: int = 0) -> str:
        """A barcode only flow `flow` uses on this screen."""
        return f"29{flow:02}{KINDS.index(self.kind)}{n:02}0000000"[:13]

    def name(self, text: str) -> str:
        """`text`, made this screen's own."""
        return f"{text} {self.tag}"

    # Touching

    def tap(self, target: Locator) -> None:
        if self.app:
            # Through the DOM: the soft keyboard can resize the WebView while
            # Playwright aims a real tap.
            target.dispatch_event("click")
        elif self.kind == "phone":
            target.tap()
        else:
            target.click()

    def type(self, target: Locator, text: str) -> None:
        target.fill(text)

    def press(self, target: Locator, key: str) -> None:
        target.press(key)

    # Scanning, after Scan was tapped

    def scan(self, code: str) -> None:
        """The scanner reads `code`."""
        if self.app:
            self.page.evaluate(
                f"""code => {EXTERNAL}.receiveMessage({{
                  id: 1, type: "command", command: "bar_code/scan_result",
                  payload: {{ rawValue: code, format: "ean_13" }},
                }})""",
                code,
            )
        else:
            self.page.evaluate("code => { window.fakeBarcode = code; }", code)

    def leave_scanner(self, card: Locator) -> None:
        """Back out of the scanner without reading anything."""
        if self.app:
            self.page.evaluate(
                f"""() => {EXTERNAL}.receiveMessage({{
                  id: 2, type: "command", command: "bar_code/aborted", payload: {{}},
                }})"""
            )
        else:
            self.tap(card.locator('.scanner [data-action="stop-scan"]'))

    def scanner_open(self, card: Locator) -> None:
        """Wait until the scanner shows: the camera in the card, or the app's own."""
        if not self.app:
            expect(card.locator(".scanner video")).to_be_visible(timeout=TIMEOUT)

    def camera_off(self) -> None:
        if not self.app:
            self.page.wait_for_function(
                "window.cameraStreams?.length && window.cameraStreams.every("
                "(s) => s.getTracks().every((t) => t.readyState === 'ended'))",
                timeout=TIMEOUT,
            )

    # Data and cards

    def ws(self, message: dict[str, Any]) -> Any:
        return self.home.ws(message)

    def person(self, name: str) -> str:
        return next(p["id"] for p in self.ws({"type": "metron/people"}) if p["name"] == name)

    def food(self, name: str, kcal: float = 100, **more: Any) -> dict:
        return self.ws(
            {
                "type": "metron/food/add",
                "name": name,
                "kcal": kcal,
                "protein": 10,
                "carbs": 20,
                "fat": 5,
                **more,
            }
        )

    def entry(self, person: str, day: str, meal: str, **fields: Any) -> dict:
        return self.ws(
            {
                "type": "metron/entry/add",
                "person": self.person(person),
                "day": day,
                "meal": meal,
                **fields,
            }
        )

    def saved_meal(self, name: str, owner: str | None, items: list[dict]) -> dict:
        return self.ws(
            {
                "type": "metron/meal/add",
                "name": name,
                "owner": owner and self.person(owner),
                "items": items,
            }
        )

    def entries(self, person: str, day: str) -> list[dict]:
        return self.ws({"type": "metron/day", "person": self.person(person), "day": day})["entries"]

    def diary(self, person: str, day: str, **config: Any) -> Locator:
        card = self.open_card({"type": "custom:metron-food-diary-card", "person": person, **config})
        expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
        card.locator('[data-action="pick-day"]').fill(day)
        expect(card.locator('[data-action="pick-day"]')).to_have_value(day)
        return card

    def meals_card(self, **config: Any) -> Locator:
        card = self.open_card({"type": "custom:metron-meals-card", **config})
        expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)
        return card

    def foods_card(self, **config: Any) -> Locator:
        card = self.open_card({"type": "custom:metron-foods-card", **config})
        expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)
        return card


def meal_section(card: Locator, meal: str) -> Locator:
    return card.locator(f'.meal[data-meal="{meal}"]')


def open_add(s: Screen, card: Locator, meal: str) -> Locator:
    s.tap(meal_section(card, meal).locator('[data-action="add"]'))
    panel = card.locator(".panel")
    expect(panel).to_be_visible()
    return panel


def tab(s: Screen, card: Locator, name: str) -> None:
    button = card.locator(f'.panel [data-action="tab"][data-tab="{name}"]')
    s.tap(button)
    expect(button).to_have_attribute("aria-selected", "true")


def tick(card: Locator, n: int) -> Locator:
    return card.locator(f'.panel [data-action="tick"][data-index="{n}"]')


def scan_from_head(s: Screen, card: Locator, code: str) -> None:
    s.tap(card.locator('.panel .headactions [data-action="scan"]'))
    s.scanner_open(card)
    s.scan(code)


@contextmanager
def person_named(home: Home, name: str) -> Iterator[Callable[[], None]]:
    """A person added for a test, as the person form adds one; removed after.

    Yields what removes them sooner.
    """
    [found] = home.api("GET", "/api/config/config_entries/entry?domain=metron")
    entry = found["entry_id"]
    flows = "/api/config/config_entries/subentries/flow"
    form = home.api("POST", flows, {"handler": [entry, "person"]})
    details = {
        "sex": "female",
        "birth_date": "1990-01-01",
        "height_cm": 170,
        "start_weight_kg": 70,
        "start_date": today(),
        "goal_weight_kg": 65,
        "activity": "light",
        "pace": "maintain",
        "protein_pct": 25,
        "carbs_pct": 45,
        "fat_pct": 30,
    }
    done = home.api("POST", f"{flows}/{form['flow_id']}", {"name": name, **details})
    assert done["type"] == "create_entry", done
    subentry = next(
        x["subentry_id"]
        for x in home.ws({"type": "config_entries/subentries/list", "entry_id": entry})
        if x["title"] == name
    )

    def remove() -> None:
        home.ws(
            {"type": "config_entries/subentries/delete", "entry_id": entry, "subentry_id": subentry}
        )

    try:
        wait_for(lambda: name in {p["name"] for p in people(home)})
        yield remove
    finally:
        if any(p["name"] == name for p in people(home)):
            remove()


def people(home: Home) -> list[dict]:
    try:
        return home.ws({"type": "metron/people"})
    except AssertionError:
        return []  # reloading


def wait_for(check: Callable[[], Any], seconds: float = 30) -> Any:
    deadline = time.monotonic() + seconds
    while not (found := check()):
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.2)
    return found


# Happy paths


def h1_save_breakfast_as_meal(s: Screen) -> None:
    """Debora saves her breakfast as a meal, leaving out the coffee."""
    day = s.day(1)
    oats = s.food(s.name("H1 oats"), 380, portions=[{"name": "Bowl", "grams": 60}])
    s.entry("Debora", day, "breakfast", food_id=oats["id"], grams=60)
    s.entry("Debora", day, "breakfast", name=s.name("H1 coffee"), kcal=20, protein=1)
    card = s.diary("Debora", day)
    s.tap(meal_section(card, "breakfast").locator('[data-action="save-as-meal"]'))
    panel = card.locator(".panel")
    expect(panel.locator(".mealhead")).to_have_text("Save Breakfast as a meal")
    name = panel.locator('[data-field="meal-name"]')
    expect(name).to_be_focused()
    save = panel.locator('[data-action="save-meal"]')
    # Every entry starts ticked; unticking them all greys Save meal out.
    expect(tick(card, 0)).to_be_checked()
    expect(tick(card, 1)).to_be_checked()
    expect(panel.locator(".preview")).to_contain_text("248")
    s.tap(tick(card, 0))
    s.tap(tick(card, 1))
    expect(save).to_be_disabled()
    expect(panel.locator(".preview b").first).to_have_text("0")
    s.tap(tick(card, 0))
    expect(save).to_be_enabled()
    expect(panel.locator(".preview")).to_contain_text("228")
    # A quick add is a fixed item, tagged so.
    expect(panel.locator(".item").nth(1)).to_contain_text("Quick add")
    s.type(name, s.name("H1 usual breakfast"))
    expect(panel.locator('[data-action="share"]')).not_to_be_checked()
    s.tap(save)
    expect(panel).to_be_hidden(timeout=TIMEOUT)

    meals = s.meals_card()
    row = meals.locator(".mealrow", has_text=s.name("H1 usual breakfast"))
    expect(row).to_contain_text("Debora", timeout=TIMEOUT)
    expect(row).to_contain_text("228 kcal")
    expect(row).not_to_contain_text("coffee")


def h2_add_everyone_s_meal(s: Screen) -> None:
    """Matteo adds Everyone's porridge bowl from Snacks, without the honey, under Breakfast."""
    day = s.day(2)
    oats = s.food(s.name("H2 porridge oats"), 380)
    milk = s.food(s.name("H2 milk"), 50)
    honey = s.food(s.name("H2 honey"), 300)
    items = [
        {"food_id": oats["id"], "grams": 60},
        {"food_id": milk["id"], "grams": 200},
        {"food_id": honey["id"], "grams": 20},
    ]
    s.saved_meal(s.name("H2 porridge bowl"), None, items)
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "snacks")
    results = panel.locator(".results")
    expect(results).to_contain_text("Saved meals", timeout=TIMEOUT)
    s.type(panel.locator('[data-action="query"]'), "H2 porridge")
    # A meal and a food both match; the meal shows its foods and owner.
    row = results.locator(".mealrow", has_text=s.name("H2 porridge bowl"))
    expect(row).to_contain_text("Everyone", timeout=TIMEOUT)
    expect(row).to_contain_text(s.name("H2 milk"))
    expect(
        results.locator('[data-action="choose"]', has_text=s.name("H2 porridge oats"))
    ).to_be_visible()
    s.tap(row)
    expect(results.locator(".row")).to_have_count(1)
    add = panel.locator('[data-action="log-meal"]')
    expect(add).to_have_text("Add to Snacks")
    for n in range(3):
        s.tap(tick(card, n))
    expect(add).to_be_disabled()
    for n in range(3):
        s.tap(tick(card, n))
    s.tap(tick(card, 2))
    panel.locator('.picked [data-field="meal"]').select_option("breakfast")
    expect(add).to_have_text("Add to Breakfast")
    expect(panel.locator(".picked .preview")).to_contain_text("328")
    s.tap(add)
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    rows = meal_section(card, "breakfast").locator(".row")
    expect(rows).to_have_count(2, timeout=TIMEOUT)
    expect(rows.nth(0)).to_contain_text(s.name("H2 porridge oats"))
    expect(rows.nth(1)).to_contain_text(s.name("H2 milk"))
    expect(meal_section(card, "snacks").locator(".row")).to_have_count(0)


def h3_scan_a_saved_product_from_quick_add(s: Screen) -> None:
    """Matteo scans a product he saved before, from the Quick add tab."""
    day = s.day(3)
    code = s.barcode(3)
    s.food(s.name("H3 Greek yogurt"), 73, barcode=code, portions=[{"name": "Pot", "grams": 170}])
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "snacks")
    tab(s, card, "quick")
    scan_from_head(s, card, code)
    # A saved barcode chooses that food on Saved.
    expect(panel.locator('[data-action="tab"][data-tab="search"]')).to_have_attribute(
        "aria-selected", "true", timeout=TIMEOUT
    )
    expect(panel.locator(".picked")).to_contain_text(s.name("H3 Greek yogurt"))
    expect(panel.locator('[data-field="grams"]')).to_have_value("170")
    s.tap(panel.locator('[data-action="add-entry"]'))
    expect(meal_section(card, "snacks").locator(".row")).to_contain_text(
        s.name("H3 Greek yogurt"), timeout=TIMEOUT
    )
    s.camera_off()


def h4_scan_a_new_product(s: Screen) -> None:
    """Debora scans a new product: a short check, then its whole form, then Save and choose."""
    day = s.day(4)
    code = s.barcode(4)
    s.off.products[code] = off_product(s.name("H4 Total 0%"), 54, serving_quantity="170")
    s.off.slow.add(code)
    card = s.diary("Debora", day)
    panel = open_add(s, card, "breakfast")
    scan_from_head(s, card, code)
    lookup = panel.locator(".lookup")
    expect(lookup).to_contain_text(f"Looking up {code}…", timeout=TIMEOUT)
    s.off.release()
    review = panel.locator(".review")
    expect(review).to_contain_text(f"{s.name('H4 Total 0%')} {DASH} Test dairy", timeout=TIMEOUT)
    expect(lookup).to_have_count(0)
    expect(review).to_contain_text(code)
    expect(review).to_contain_text("54")
    expect(review).to_contain_text("Serving · 170 g")
    expect(panel.locator(".note")).to_contain_text("Filled in from Open Food Facts")
    expect(panel.locator(".foodform")).to_have_count(0)
    s.tap(review.locator('[data-action="edit-values"]'))
    form = panel.locator(".foodform")
    expect(form.locator('[data-field="kcal"]')).to_have_value("54")
    s.type(form.locator('[data-field="kcal"]'), "55")
    s.tap(panel.locator('[data-action="save-new-food"]'))
    expect(panel.locator(".picked")).to_contain_text(s.name("H4 Total 0%"), timeout=TIMEOUT)
    expect(panel.locator('[data-field="grams"]')).to_have_value("170")
    s.tap(panel.locator('[data-action="add-entry"]'))
    expect(meal_section(card, "breakfast").locator(".row")).to_contain_text("94", timeout=TIMEOUT)
    saved = s.ws({"type": "metron/food/barcode", "barcode": code})
    assert (saved["kcal"], saved["saved_by"]) == (55, s.person("Debora"))


def h5_build_a_meal_in_the_card(s: Screen) -> None:
    """A meal built from saved foods in the Saved meals card, for Matteo."""
    s.food(s.name("H5 whey"), 400, portions=[{"name": "Scoop", "grams": 30}])
    s.food(s.name("H5 banana"), 89)
    card = s.meals_card()
    s.tap(card.locator('[data-action="new"]'))
    panel = card.locator(".panel")
    expect(panel.locator(".title")).to_have_text("Add meal")
    s.type(panel.locator('[data-field="meal-name"]'), s.name("H5 shake"))
    owner = panel.locator('[data-action="owner"]')
    expect(owner).to_have_value("")
    owner.select_option(label="Matteo")
    search = panel.locator('[data-action="add-food"]')
    for food in ("H5 whey", "H5 banana"):
        s.type(search, s.name(food))
        s.tap(panel.locator('.addfood [data-action="add-item"]', has_text=s.name(food)))
    grams = panel.locator('[data-action="item-grams"]')
    expect(grams).to_have_count(2)
    expect(grams.nth(0)).to_have_value("30")
    expect(grams.nth(1)).to_have_value("100")
    s.type(grams.nth(1), "120")
    expect(panel.locator(".mealitem .kcal").nth(1)).to_have_text("107")
    expect(panel.locator(".preview")).to_contain_text("227")
    s.tap(panel.locator('[data-action="save-meal"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    row = card.locator(".mealrow", has_text=s.name("H5 shake"))
    expect(row).to_contain_text("Matteo", timeout=TIMEOUT)
    expect(row).to_contain_text("227 kcal")


def h6_values_follow_the_food(s: Screen) -> None:
    """Changing a saved food changes the meals it is in."""
    whey = s.food(s.name("H6 whey"), 400)
    s.saved_meal(s.name("H6 shake"), "Matteo", [{"food_id": whey["id"], "grams": 30}])
    meals = s.meals_card(person="Matteo")
    row = meals.locator(".mealrow", has_text=s.name("H6 shake"))
    expect(row).to_contain_text("120 kcal", timeout=TIMEOUT)
    s.ws({"type": "metron/food/update", "food_id": whey["id"], "kcal": 380})
    expect(row).to_contain_text("114 kcal", timeout=TIMEOUT)
    # In the foods card too.
    foods = s.foods_card()
    s.type(foods.locator('[data-action="query"]'), s.name("H6 whey"))
    s.tap(foods.locator(".row", has_text=s.name("H6 whey")))
    s.type(foods.locator('.panel [data-field="kcal"]'), "360")
    s.tap(foods.locator('.panel [data-action="save"]'))
    expect(foods.locator(".panel")).to_be_hidden(timeout=TIMEOUT)
    meals = s.meals_card(person="Matteo")
    expect(meals.locator(".mealrow", has_text=s.name("H6 shake"))).to_contain_text(
        "108 kcal", timeout=TIMEOUT
    )


def h7_type_a_barcode(s: Screen) -> None:
    """A barcode typed into New food's search, then Enter, gives a short check."""
    day = s.day(7)
    code = s.barcode(7)
    s.off.products[code] = off_product(s.name("H7 spaghetti"), 359, serving_quantity="80")
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "dinner")
    tab(s, card, "new")
    search = panel.locator('[data-action="off-query"]')
    s.type(search, code)
    s.press(search, "Enter")
    review = panel.locator(".review")
    expect(review).to_contain_text(s.name("H7 spaghetti"), timeout=TIMEOUT)
    expect(search).to_have_value("")
    s.tap(panel.locator('[data-action="save-new-food"]'))
    expect(panel.locator(".picked")).to_contain_text(s.name("H7 spaghetti"), timeout=TIMEOUT)
    s.tap(panel.locator('[data-action="add-entry"]'))
    expect(meal_section(card, "dinner").locator(".row")).to_contain_text("287", timeout=TIMEOUT)


def h8_pick_from_a_name_search(s: Screen) -> None:
    """A product picked from Open Food Facts' search by name gives a short check."""
    assert s.search is not None
    day = s.day(8)
    code = s.barcode(8)
    s.off.products[code] = off_product(s.name("H8 granola"), 484, serving_quantity="50")
    s.search.find(
        [
            {
                "code": code,
                "product_name": s.name("H8 granola"),
                "brands": ["Test dairy"],
                "quantity": "500 g",
                "nutriments": {
                    "energy-kcal_100g": 480,
                    "proteins_100g": 11,
                    "carbohydrates_100g": 49,
                    "fat_100g": 25,
                },
            }
        ]
    )
    card = s.diary("Debora", day)
    panel = open_add(s, card, "breakfast")
    tab(s, card, "new")
    search = panel.locator('[data-action="off-query"]')
    s.type(search, s.name("H8 granola"))
    s.press(search, "Enter")
    pick = panel.locator('[data-action="off-pick"]')
    expect(pick).to_have_count(1, timeout=TIMEOUT)
    s.tap(pick)
    review = panel.locator(".review")
    # The lookup's values, which are newer than the search's.
    expect(review).to_contain_text("484", timeout=TIMEOUT)
    s.tap(panel.locator('[data-action="save-new-food"]'))
    expect(panel.locator(".picked")).to_contain_text(s.name("H8 granola"), timeout=TIMEOUT)
    expect(panel.locator('[data-field="grams"]')).to_have_value("50")


def h9_scan_in_the_saved_foods_card(s: Screen) -> None:
    """The saved foods card keeps Scan barcode, now with a short check ending in Save food."""
    code = s.barcode(9)
    s.off.products[code] = off_product(s.name("H9 skyr"), 63)
    card = s.foods_card()
    s.tap(card.locator('[data-action="new"]'))
    panel = card.locator(".panel")
    s.tap(panel.locator('[data-action="off-scan"]'))
    s.scanner_open(card)
    s.scan(code)
    review = panel.locator(".review")
    expect(review).to_contain_text(s.name("H9 skyr"), timeout=TIMEOUT)
    expect(panel.locator('[data-action="save"]')).to_have_text("Save food")
    s.tap(panel.locator('[data-action="save"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    assert s.ws({"type": "metron/food/barcode", "barcode": code})["kcal"] == 63
    s.camera_off()


def h10_delete_a_meal(s: Screen) -> None:
    """Deleting a meal leaves the entries logged from it."""
    day = s.day(10)
    meal = s.saved_meal(s.name("H10 toast"), None, [{"name": "Toast", "kcal": 150}])
    s.ws(
        {
            "type": "metron/meal/log",
            "person": s.person("Debora"),
            "day": day,
            "meal": "breakfast",
            "meal_id": meal["id"],
            "version": meal["version"],
            "items": [meal["items"][0]["id"]],
        }
    )
    card = s.meals_card()
    s.type(card.locator('[data-action="query"]'), s.name("H10 toast"))
    s.tap(card.locator(".mealrow", has_text=s.name("H10 toast")))
    panel = card.locator(".panel")
    s.tap(panel.locator('[data-action="delete-meal"]'))
    expect(panel).to_contain_text("Entries already logged from it stay in the diary.")
    s.tap(panel.locator('[data-action="really-delete"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    expect(card.locator(".list")).to_contain_text("No saved meal matches", timeout=TIMEOUT)
    assert [e["name"] for e in s.entries("Debora", day)] == ["Toast"]


# Edge cases


def e1_name_clashes(s: Screen) -> None:
    """Names are unique within what one person sees, ignoring case."""
    day = s.day(11)
    s.saved_meal(s.name("E1 pasta night"), None, [{"name": "Pasta", "kcal": 500}])
    s.entry("Debora", day, "lunch", name="Soup", kcal=200)
    card = s.diary("Debora", day)
    s.tap(meal_section(card, "lunch").locator('[data-action="save-as-meal"]'))
    panel = card.locator(".panel")
    name = panel.locator('[data-field="meal-name"]')
    s.type(name, s.name("E1 PASTA NIGHT"))
    s.tap(panel.locator('[data-action="save-meal"]'))
    error = panel.locator(".error")
    expect(error).to_have_text(
        f"There is already a meal called “{s.name('E1 PASTA NIGHT')}” for everyone.",
        timeout=TIMEOUT,
    )
    # The message is above the button.
    assert (
        error.bounding_box()["y"] < panel.locator('[data-action="save-meal"]').bounding_box()["y"]
    )
    s.type(name, s.name("E1 soup"))
    s.tap(panel.locator('[data-action="save-meal"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)

    # In the card: Debora's own name clashes when the meal is for everyone,
    # and a meal may take its own name in another case.
    card = s.meals_card()
    s.tap(card.locator('[data-action="new"]'))
    panel = card.locator(".panel")
    s.type(panel.locator('[data-field="meal-name"]'), s.name("e1 SOUP"))
    s.type(panel.locator('[data-action="add-food"]'), "zz-nothing-matches")
    expect(panel.locator(".addfood")).to_contain_text("No saved food matches", timeout=TIMEOUT)
    s.tap(panel.locator('[data-action="save-meal"]'))
    expect(panel.locator(".error")).to_contain_text("Add at least one food")
    s.saved_meal(s.name("E1 mine"), "Matteo", [{"name": "Toast", "kcal": 150}])
    s.tap(panel.locator('[data-action="close"]'))
    s.type(card.locator('[data-action="query"]'), s.name("E1 mine"))
    s.tap(card.locator(".mealrow", has_text=s.name("E1 mine")))
    s.type(panel.locator('[data-field="meal-name"]'), s.name("e1 SOUP"))
    panel.locator('[data-action="owner"]').select_option("")
    s.tap(panel.locator('[data-action="save-meal"]'))
    expect(panel.locator(".error")).to_have_text(
        f"Debora already has a meal called “{s.name('e1 SOUP')}”.", timeout=TIMEOUT
    )
    s.type(panel.locator('[data-field="meal-name"]'), s.name("E1 MINE"))
    s.tap(panel.locator('[data-action="save-meal"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    s.type(card.locator('[data-action="query"]'), s.name("E1 MINE"))
    row = card.locator(".mealrow", has_text=s.name("E1 MINE"))
    expect(row).to_contain_text("Everyone", timeout=TIMEOUT)


def e2_two_people_at_once(s: Screen) -> None:
    """What someone else saves or deletes meanwhile."""
    day = s.day(12)
    code = s.barcode(12)
    s.off.products[code] = off_product(s.name("E2 oat drink"), 46)
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "breakfast")
    tab(s, card, "new")
    search = panel.locator('[data-action="off-query"]')
    s.type(search, code)
    s.press(search, "Enter")
    expect(panel.locator(".review")).to_be_visible(timeout=TIMEOUT)
    # Debora saves the same product on her phone.
    hers = s.food(s.name("E2 her oat drink"), 46, barcode=code, person=s.person("Debora"))
    s.tap(panel.locator('[data-action="save-new-food"]'))
    expect(panel.locator(".warning")).to_have_text(
        f"Debora already saved this as {s.name('E2 her oat drink')}.", timeout=TIMEOUT
    )
    expect(panel.locator(".picked")).to_contain_text(s.name("E2 her oat drink"))
    assert s.ws({"type": "metron/food/barcode", "barcode": code})["id"] == hers["id"]
    s.tap(panel.locator('.headactions [data-action="close"]'))

    # A meal chosen while someone deletes it.
    salad = s.saved_meal(s.name("E2 chicken salad"), None, [{"name": "Salad", "kcal": 300}])
    panel = open_add(s, card, "lunch")
    s.type(panel.locator('[data-action="query"]'), s.name("E2 chicken salad"))
    s.tap(panel.locator(".mealrow", has_text=s.name("E2 chicken salad")))
    s.ws({"type": "metron/meal/delete", "meal_id": salad["id"], "version": salad["version"]})
    s.tap(panel.locator('[data-action="log-meal"]'))
    expect(panel.locator(".error")).to_have_text(
        f"{s.name('E2 chicken salad')} was changed or deleted meanwhile, so nothing was added. "
        "Choose a meal again.",
        timeout=TIMEOUT,
    )
    expect(panel.locator(".mealrow", has_text=s.name("E2 chicken salad"))).to_have_count(0)
    assert s.entries("Matteo", day) == []


def e3_delete_a_food_in_two_meals(s: Screen) -> None:
    """In German: deleting a food names the meals it is in, and deletes the one it empties."""
    banana = s.food(s.name("E3 Banane"), 89)
    milk = s.food(s.name("E3 Milch"), 50)
    item = {"food_id": banana["id"], "grams": 118}
    s.saved_meal(s.name("E3 Frühstück"), "Debora", [item, {"food_id": milk["id"], "grams": 200}])
    s.saved_meal(s.name("E3 Snack"), None, [item])
    card = s.foods_card(locale="de")
    s.type(card.locator('[data-action="query"]'), s.name("E3 Banane"))
    s.tap(card.locator(".row", has_text=s.name("E3 Banane")))
    panel = card.locator(".panel")
    s.tap(panel.locator('[data-action="delete"]'))
    alert = panel.locator(".alert")
    expect(alert).to_contain_text(
        f"Es ist auch in {s.name('E3 Frühstück')} und {s.name('E3 Snack')} "
        "und wird daraus entfernt.",
        timeout=TIMEOUT,
    )
    expect(alert).to_contain_text(f"{s.name('E3 Snack')} wird ebenfalls gelöscht")
    s.tap(panel.locator('[data-action="really-delete"]'))
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    meals = {m["name"]: m for m in s.ws({"type": "metron/meals"})}
    assert s.name("E3 Snack") not in meals
    assert [i["name"] for i in meals[s.name("E3 Frühstück")]["items"]] == [s.name("E3 Milch")]


def e4_lookups_going_wrong(s: Screen) -> None:
    """Open Food Facts unreachable, a barcode it does not know, Cancel, and a newer lookup."""
    day = s.day(14)
    down, unknown, slow, fast = (s.barcode(14, n) for n in range(4))
    s.off.products[down] = off_product(s.name("E4 back again"), 70)
    s.off.failing.add(down)
    card = s.diary("Debora", day)
    panel = open_add(s, card, "snacks")
    tab(s, card, "new")
    search = panel.locator('[data-action="off-query"]')
    s.type(search, down)
    s.press(search, "Enter")
    expect(panel.locator(".error")).to_contain_text(
        "Could not reach Open Food Facts", timeout=TIMEOUT
    )
    s.off.failing.clear()
    s.tap(panel.locator('[data-action="retry-lookup"]'))
    expect(panel.locator(".review")).to_contain_text(s.name("E4 back again"), timeout=TIMEOUT)
    expect(panel.locator(".error")).to_have_count(0)

    # Not on Open Food Facts: the whole form, with the barcode in it.
    s.type(search, unknown)
    s.press(search, "Enter")
    expect(panel.locator(".error")).to_contain_text(
        f"Open Food Facts does not know barcode {unknown}", timeout=TIMEOUT
    )
    expect(panel.locator('.foodform [data-field="barcode"]')).to_have_value(unknown)
    s.tap(panel.locator('.headactions [data-action="close"]'))

    # Cancel drops a lookup.
    panel = open_add(s, card, "snacks")
    tab(s, card, "new")
    search = panel.locator('[data-action="off-query"]')
    s.off.products[slow] = off_product(s.name("E4 slow"), 80)
    s.off.slow.add(slow)
    s.type(search, slow)
    s.press(search, "Enter")
    expect(panel.locator(".lookup")).to_contain_text(slow, timeout=TIMEOUT)
    s.tap(panel.locator('[data-action="cancel-lookup"]'))
    expect(panel.locator(".lookup")).to_have_count(0)
    s.off.release()
    expect(panel.locator(".review")).to_have_count(0)

    # A newer lookup replaces one still running.
    s.off.products[fast] = off_product(s.name("E4 fast"), 90)
    s.off.slow.add(slow)
    s.type(search, slow)
    s.press(search, "Enter")
    expect(panel.locator(".lookup")).to_contain_text(slow, timeout=TIMEOUT)
    s.type(search, fast)
    s.press(search, "Enter")
    expect(panel.locator(".review")).to_contain_text(s.name("E4 fast"), timeout=TIMEOUT)
    s.off.release()
    s.page.wait_for_timeout(500)
    expect(panel.locator(".review")).to_contain_text(s.name("E4 fast"))


def e5_scanner_interruptions(s: Screen) -> None:
    """Backing out of a scan changes nothing; a blocked camera says so; leaving stops it."""
    day = s.day(15)
    card = s.diary("Debora", day)
    panel = open_add(s, card, "breakfast")
    query = panel.locator('[data-action="query"]')
    s.type(query, "kept")
    scan = panel.locator('.headactions [data-action="scan"]')
    s.tap(scan)
    s.scanner_open(card)
    s.leave_scanner(card)
    expect(scan).to_be_focused(timeout=TIMEOUT)
    expect(query).to_have_value("kept")
    expect(panel.locator(".error")).to_have_count(0)
    if s.app:
        return
    # Switching tab stops the camera.
    s.tap(scan)
    s.scanner_open(card)
    tab(s, card, "quick")
    expect(card.locator(".scanner video")).to_have_count(0)
    s.camera_off()
    # A blocked camera.
    s.page.evaluate("() => { window.refuseCamera = true; }")
    s.tap(scan)
    expect(panel.locator(".error")).to_contain_text("Could not use the camera", timeout=TIMEOUT)
    s.page.evaluate("() => { window.refuseCamera = false; }")


def e6_scanning_with_something_half_typed(s: Screen) -> None:
    """What was typed in Quick add survives a scan."""
    day = s.day(16)
    code = s.barcode(16)
    s.food(s.name("E6 yogurt"), 73, barcode=code)
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "lunch")
    tab(s, card, "quick")
    s.type(panel.locator('[data-field="name"]'), "Half-typed pizza")
    s.type(panel.locator('[data-field="kcal"]'), "300")
    scan_from_head(s, card, code)
    expect(panel.locator(".picked")).to_contain_text(s.name("E6 yogurt"), timeout=TIMEOUT)
    tab(s, card, "quick")
    expect(panel.locator('[data-field="name"]')).to_have_value("Half-typed pizza")
    expect(panel.locator('[data-field="kcal"]')).to_have_value("300")
    # And New food's form survives a trip to another tab.
    tab(s, card, "new")
    s.type(panel.locator('.foodform [data-field="name"]'), "Half a food")
    tab(s, card, "search")
    tab(s, card, "new")
    expect(panel.locator('.foodform [data-field="name"]')).to_have_value("Half a food")
    s.camera_off()


def e7_phone_space(s: Screen) -> None:
    """A long day's meal: the button and its message stay in view; German's long head wraps."""
    day = s.day(17)
    s.saved_meal(s.name("E7 taken"), None, [{"name": "x", "kcal": 1}])
    for n in range(12):
        s.entry("Matteo", day, "breakfast", name=f"MyFitnessPal {n}", kcal=100 + n)
    card = s.diary("Matteo", day)
    s.tap(meal_section(card, "breakfast").locator('[data-action="save-as-meal"]'))
    panel = card.locator(".panel")
    expect(panel.locator(".item")).to_have_count(12)
    name = panel.locator('[data-field="meal-name"]')
    s.type(name, s.name("E7 taken"))
    s.press(name, "Enter")
    error = panel.locator(".error")
    expect(error).to_be_visible(timeout=TIMEOUT)
    save = panel.locator('[data-action="save-meal"]')
    expect(save).to_be_in_viewport()
    expect(error).to_be_in_viewport()
    s.tap(panel.locator('[data-action="close"]'))

    german = s.diary("Matteo", day, locale="de")
    panel = open_add(s, german, "breakfast")
    head = panel.locator(".mealhead")
    expect(head).to_contain_text("Zu Frühstück hinzufügen")
    actions = head.locator(".headactions")
    close = actions.locator('[data-action="close"]')
    expect(close).to_have_text("Abbrechen")
    # Scan and Cancel keep to the right, inside the card, wrapped or not.
    head_box, actions_box = head.bounding_box(), actions.bounding_box()
    assert abs(head_box["x"] + head_box["width"] - (actions_box["x"] + actions_box["width"])) < 2


def e8_keyboard_only(s: Screen) -> None:
    """Saving and adding a meal with keys alone."""
    day = s.day(18)
    s.entry("Debora", day, "dinner", name="Rice", kcal=200)
    s.entry("Debora", day, "dinner", name="Beans", kcal=150)
    s.saved_meal(s.name("E8 only match"), None, [{"name": "Toast", "kcal": 150}])
    card = s.diary("Debora", day)
    s.tap(meal_section(card, "dinner").locator('[data-action="save-as-meal"]'))
    panel = card.locator(".panel")
    name = panel.locator('[data-field="meal-name"]')
    expect(name).to_be_focused()
    name.press_sequentially(s.name("E8 rice and beans"))
    s.page.keyboard.press("Tab")
    first = tick(card, 0)
    expect(first).to_be_focused()
    s.page.keyboard.press("Space")
    # Ticking redraws only the totals, so focus stays.
    expect(first).not_to_be_checked()
    expect(first).to_be_focused()
    expect(panel.locator(".preview")).to_contain_text("150")
    s.page.keyboard.press("Space")
    name.focus()
    s.page.keyboard.press("Enter")
    expect(panel).to_be_hidden(timeout=TIMEOUT)
    saved = [m for m in s.ws({"type": "metron/meals"}) if m["name"] == s.name("E8 rice and beans")]
    assert [i["name"] for i in saved[0]["items"]] == ["Rice", "Beans"]

    # One match in the Saved search: Enter chooses it.
    panel = open_add(s, card, "lunch")
    query = panel.locator('[data-action="query"]')
    query.press_sequentially(s.name("E8 only match"))
    s.page.keyboard.press("Enter")
    expect(panel.locator('[data-action="log-meal"]')).to_be_visible(timeout=TIMEOUT)
    expect(panel.locator(".picked")).to_contain_text(s.name("E8 only match"))


def e9_a_removed_person_s_meals(s: Screen) -> None:
    """Ana's meals become everyone's when she is removed, one renamed."""
    ana = s.name("Ana")
    with person_named(s.home, ana) as remove:
        s.saved_meal(s.name("E9 usual breakfast"), "Debora", [{"name": "Oats", "kcal": 300}])
        key = s.person(ana)
        for meal_name in ("E9 usual breakfast", "E9 berries bowl"):
            s.ws(
                {
                    "type": "metron/meal/add",
                    "name": s.name(meal_name),
                    "owner": key,
                    "items": [{"name": "x", "kcal": 1}],
                }
            )
        food = s.food(s.name("E9 berries"), 45, person=key)
        assert food["saved_by"] == key
        remove()
        wait_for(lambda: ana not in {p["name"] for p in people(s.home)} and people(s.home))
    card = s.meals_card()
    s.type(card.locator('[data-action="query"]'), "E9")
    renamed = card.locator(".mealrow", has_text=f"{s.name('E9 usual breakfast')} ({ana})")
    expect(renamed).to_contain_text("Everyone", timeout=TIMEOUT)
    expect(card.locator(".mealrow", has_text=s.name("E9 berries bowl"))).to_contain_text("Everyone")
    both = card.locator(".mealrow", has_text=s.name("E9 usual breakfast"))
    expect(both).to_have_count(2)
    expect(both.filter(has_text="Debora")).to_have_count(1)
    berries = s.ws({"type": "metron/food/search", "query": s.name("E9 berries")})[0]
    assert berries["saved_by"] is None


def e10_save_a_food_again(s: Screen) -> None:
    """Matteo saves a Banana Debora saved: the warning offers Choose it."""
    day = s.day(20)
    hers = s.food(s.name("E10 Banana"), 89, person=s.person("Debora"))
    card = s.diary("Matteo", day)
    panel = open_add(s, card, "snacks")
    tab(s, card, "new")
    form = panel.locator(".foodform")
    s.type(form.locator('[data-field="name"]'), s.name("E10 banana"))
    for key, value in {"kcal": "90", "protein": "1", "carbs": "23", "fat": "0.3"}.items():
        s.type(form.locator(f'[data-field="{key}"]'), value)
    s.tap(panel.locator('[data-action="save-new-food"]'))
    warning = panel.locator(".warning")
    expect(warning).to_have_text(
        f"{s.name('E10 Banana')} is already saved by Debora.", timeout=TIMEOUT
    )
    expect(panel.locator('[data-action="save-anyway"]')).to_be_visible()
    s.tap(panel.locator('[data-action="choose-taken"]'))
    expect(panel.locator(".picked")).to_contain_text(s.name("E10 Banana"), timeout=TIMEOUT)
    found = s.ws({"type": "metron/food/search", "query": s.name("E10 Banana")})
    assert [f["id"] for f in found] == [hers["id"]]
    # Save anyway saves a second one.
    tab(s, card, "new")
    s.type(panel.locator('.foodform [data-field="name"]'), s.name("E10 banana"))
    for key, value in {"kcal": "90", "protein": "1", "carbs": "23", "fat": "0.3"}.items():
        s.type(panel.locator(f'.foodform [data-field="{key}"]'), value)
    s.tap(panel.locator('[data-action="save-new-food"]'))
    s.tap(panel.locator('[data-action="save-anyway"]'))
    expect(panel.locator(".picked")).to_contain_text(s.name("E10 banana"), timeout=TIMEOUT)
    found = s.ws({"type": "metron/food/search", "query": s.name("E10 Banana")})
    assert len(found) == 2
    assert {f["saved_by"] for f in found} == {s.person("Debora"), s.person("Matteo")}


FLOWS = [
    h1_save_breakfast_as_meal,
    h2_add_everyone_s_meal,
    h3_scan_a_saved_product_from_quick_add,
    h4_scan_a_new_product,
    h5_build_a_meal_in_the_card,
    h6_values_follow_the_food,
    h7_type_a_barcode,
    h8_pick_from_a_name_search,
    h9_scan_in_the_saved_foods_card,
    h10_delete_a_meal,
    e1_name_clashes,
    e2_two_people_at_once,
    e3_delete_a_food_in_two_meals,
    e4_lookups_going_wrong,
    e5_scanner_interruptions,
    e6_scanning_with_something_half_typed,
    e7_phone_space,
    e8_keyboard_only,
    e9_a_removed_person_s_meals,
    e10_save_a_food_again,
]


def install(page: Page, off: OpenFoodFacts) -> None:
    """Give `page` the fake camera and Open Food Facts the flows need."""
    page.add_init_script(FAKE_CAMERA)
    page.route("https://world.openfoodfacts.org/**", off.answer)


def flow_id(flow: Callable) -> str:
    return flow.__name__.split("_", 1)[0].upper()
