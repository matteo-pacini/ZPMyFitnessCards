"""Cards in states a person rarely sees: loading, failing, unlinked, removed.

These mount a card straight into the running Home Assistant page, with its
real connection, or with one that fails on purpose, and read what it shows.
The card sits outside the dashboard, under its launch screen, so clicks go
straight to the button as events.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import Home
from .flows import person_named, today

TIMEOUT = 15_000

# Mount a card at #mounted. `fail` maps a command type (or "*") to the error
# code its calls reject with; `once` fails only the first call of each. `slow`
# maps a command type to how many ms its replies take.
MOUNT = """
async ({ tag, config, fail, once, subscribeFails, slow }) => {
  const base = document.querySelector("home-assistant").hass;
  const failed = new Set();
  const callWS = (message) => {
    const code = fail[message.type] ?? fail["*"];
    if (code && !(once && failed.has(message.type))) {
      failed.add(message.type);
      return Promise.reject({ code, message: `${code} on purpose` });
    }
    const reply = base.callWS(message);
    const ms = slow[message.type];
    return ms ? reply.then((r) => new Promise((done) => setTimeout(() => done(r), ms))) : reply;
  };
  const connection = subscribeFails
    ? { ...base.connection, subscribeMessage: () => Promise.reject(new Error("no")) }
    : base.connection;
  document.getElementById("mounted")?.remove();
  const el = document.createElement(tag);
  el.id = "mounted";
  el.setConfig(config);
  el.hass = { ...base, callWS, connection };
  document.body.appendChild(el);
}
"""


def open_home(home: Home, page: Page) -> None:
    home.dashboard([{"type": "markdown", "content": "Test"}])
    page.goto(home.url + "/" + home.DASHBOARD + "/0")
    page.wait_for_function("document.querySelector('home-assistant')?.hass?.connected")


def mount(
    page: Page, tag: str, config: dict, fail=None, once=False, subscribe_fails=False, slow=None
):
    page.evaluate(
        MOUNT,
        {
            "tag": tag,
            "config": config,
            "fail": fail or {},
            "once": once,
            "subscribeFails": subscribe_fails,
            "slow": slow or {},
        },
    )
    return page.locator("#mounted")


def test_load_errors_are_shown(home: Home, page: Page) -> None:
    open_home(home, page)
    for tag, config in (
        ("metron-food-diary-card", {"person": "Debora"}),
        ("metron-weight-card", {"person": "Debora"}),
        ("metron-streak-card", {"person": "Debora"}),
        ("metron-foods-card", {}),
    ):
        card = mount(page, tag, config, fail={"*": "boom"})
        expect(card.locator(".error")).to_have_text(
            "Something went wrong: boom on purpose", timeout=TIMEOUT
        )


def test_cards_wait_and_retry_while_the_integration_reloads(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(
        page,
        "metron-food-diary-card",
        {"person": "Debora"},
        fail={"*": "not_loaded"},
        once=True,
    )
    expect(card.locator(".muted")).to_have_text("Loading…")
    # The card tries again after two seconds, and then the calls work.
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)

    card = mount(
        page, "metron-streak-card", {"person": "Debora"}, fail={"*": "not_loaded"}, once=True
    )
    expect(card.locator(".muted")).to_have_text("Loading…")
    expect(card.locator(".cal")).to_be_visible(timeout=TIMEOUT)

    # The person loads, and only then does the integration start reloading.
    card = mount(
        page,
        "metron-streak-card",
        {"person": "Debora"},
        fail={"metron/days": "not_loaded"},
        once=True,
    )
    expect(card.locator(".title")).to_have_text("Streak")
    expect(card.locator(".muted")).to_have_text("Loading…")
    expect(card.locator(".cal")).to_be_visible(timeout=TIMEOUT)


# Every call failing once, so metron/people first; or only the person's days.
@pytest.mark.parametrize(
    "failing",
    [
        "*",
        "metron/days",
    ],
)
def test_the_streak_card_shows_a_failed_load_then_tries_again(
    home: Home, page: Page, failing: str
) -> None:
    open_home(home, page)
    card = mount(
        page, "metron-streak-card", {"person": "Debora"}, fail={failing: "boom"}, once=True
    )
    expect(card.locator(".error")).to_have_text("Something went wrong: boom on purpose")
    # The card tries again after two seconds, and then the calls work.
    expect(card.locator(".cal")).to_be_visible(timeout=TIMEOUT)
    expect(card.locator(".error")).to_have_count(0)


def test_a_card_moved_while_it_waits_to_retry_tries_again(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(
        page,
        "metron-food-diary-card",
        {"person": "Debora"},
        fail={"*": "not_loaded"},
        once=True,
    )
    expect(card.locator(".muted")).to_have_text("Loading…")
    # Removing the card cancels its retry; putting it back must not leave it loading.
    page.evaluate(
        """() => {
          const el = document.getElementById("mounted");
          el.remove();
          document.body.appendChild(el);
        }"""
    )
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)


def test_a_failed_subscription_still_shows_the_card(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(page, "metron-foods-card", {}, subscribe_fails=True)
    expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)


def test_says_who_the_card_cannot_find(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(page, "metron-weight-card", {"person": "Nora"})
    expect(card.locator(".error")).to_contain_text("No person named Nora", timeout=TIMEOUT)
    card = mount(page, "metron-food-diary-card", {"person": "Nora"})
    expect(card.locator(".error")).to_contain_text("No person named Nora", timeout=TIMEOUT)
    card = mount(page, "metron-streak-card", {"person": "Nora"})
    expect(card.locator(".error")).to_contain_text("No person named Nora", timeout=TIMEOUT)
    # Nobody is linked to the test owner, so a card without a person has no one.
    card = mount(page, "metron-summary-card", {})
    expect(card.locator(".error")).to_contain_text("No person to show", timeout=TIMEOUT)
    card = mount(page, "metron-streak-card", {})
    expect(card.locator(".error")).to_contain_text("No person to show", timeout=TIMEOUT)


def test_a_failed_refresh_keeps_the_card_and_retries(home: Home, page: Page) -> None:
    matteo = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == "Matteo")
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)
    card = mount(page, "metron-weight-card", {"person": "Matteo"})
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
    # From now on its calls fail, so the refresh a change causes fails too.
    page.evaluate(
        """() => {
          const el = document.getElementById("mounted");
          el._working = el._hass;
          const fail = () => Promise.reject({ code: "boom", message: "boom on purpose" });
          el._hass = { ...el._hass, callWS: fail };
        }"""
    )
    home.ws({"type": "metron/weight/set", "person": matteo, "day": today, "kg": 77.7})
    page.wait_for_timeout(500)
    # It keeps what it showed, and keeps trying.
    expect(card.locator(".chart")).to_be_visible()
    expect(card.locator(".body")).not_to_contain_text("77.7 kg")
    page.evaluate(
        "() => { const el = document.getElementById('mounted'); el._hass = el._working; }"
    )
    expect(card.locator(".body")).to_contain_text("77.7 kg", timeout=TIMEOUT)


def test_weight_card_shows_save_and_delete_errors(home: Home, page: Page) -> None:
    debora = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == "Debora")
    home.ws({"type": "metron/weight/set", "person": debora, "day": "2026-01-02", "kg": 70})
    open_home(home, page)
    card = mount(
        page,
        "metron-weight-card",
        {"person": "Debora"},
        fail={"metron/weight/set": "boom", "metron/weight/delete": "boom"},
    )
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
    card.locator('[data-field="weight"]').fill("68")
    card.locator('[data-action="log"]').dispatch_event("click")
    expect(card.locator(".error")).to_have_text("Something went wrong: boom on purpose")
    card.locator('[data-action="delete-weight"]').first.dispatch_event("click")
    expect(card.locator(".error")).to_have_text("Something went wrong: boom on purpose")


def test_removed_cards_stop_listening(home: Home, page: Page) -> None:
    matteo = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == "Matteo")
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)
    card = mount(page, "metron-food-diary-card", {"person": "Matteo"})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    # The commands the card sends from here on.
    page.evaluate(
        """() => {
          const el = document.getElementById("mounted");
          const callWS = el._hass.callWS;
          window.sent = [];
          el._hass = { ...el._hass, callWS: (m) => (window.sent.push(m.type), callWS(m)) };
        }"""
    )

    def change() -> None:
        home.ws(
            {
                "type": "metron/weight/set",
                "person": matteo,
                "day": today,
                "kg": 81 + len(page.evaluate("window.sent")) / 10,
            }
        )

    # While on the page, a change to Matteo, or a day opened for him, makes it fetch.
    change()
    page.wait_for_function("window.sent.includes('metron/day')", timeout=TIMEOUT)
    page.evaluate(
        """person => {
          window.sent = [];
          const detail = { person, day: "2026-01-01" };
          window.dispatchEvent(new CustomEvent("metron-open-day", { detail }));
        }""",
        matteo,
    )
    page.wait_for_function("window.sent.includes('metron/day')", timeout=TIMEOUT)

    # Removed, it hears neither, and fails on nothing.
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.evaluate(
        """person => {
          document.getElementById("mounted").remove();
          window.sent = [];
          const detail = { person, day: "2026-01-02" };
          window.dispatchEvent(new CustomEvent("metron-open-day", { detail }));
        }""",
        matteo,
    )
    change()
    page.wait_for_timeout(1000)
    assert page.evaluate("window.sent") == []
    assert errors == []
    home.ws({"type": "metron/weight/delete", "person": matteo, "day": today})


def test_the_summary_card_gives_its_hass_back(home: Home, page: Page) -> None:
    open_home(home, page)
    mount(page, "metron-summary-card", {"person": "Debora"})
    same = page.evaluate("() => document.getElementById('mounted').hass.callWS !== undefined")
    assert same


BREAK = """() => {
  const el = document.getElementById("mounted");
  el._working = el._hass;
  const fail = () => Promise.reject({ code: "boom", message: "boom on purpose" });
  el._hass = { ...el._hass, callWS: fail };
}"""
MEND = "() => { const el = document.getElementById('mounted'); el._hass = el._working; }"


def test_the_diary_and_saved_foods_recover_from_a_failed_refresh(home: Home, page: Page) -> None:
    matteo = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == "Matteo")
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)

    card = mount(page, "metron-food-diary-card", {"person": "Matteo"})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    page.evaluate(BREAK)
    home.ws(
        {
            "type": "metron/entry/add",
            "person": matteo,
            "day": today,
            "meal": "snacks",
            "name": "Recovered apple",
            "kcal": 52,
        }
    )
    page.wait_for_timeout(500)
    expect(card.locator(".meal")).to_have_count(4)
    page.evaluate(MEND)
    expect(card.locator(".row", has_text="Recovered apple")).to_have_count(1, timeout=TIMEOUT)

    card = mount(page, "metron-foods-card", {})
    expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)
    page.evaluate(BREAK)
    home.ws(
        {
            "type": "metron/food/add",
            "name": "Recovered pear",
            "kcal": 57,
            "protein": 0.4,
            "carbs": 15,
            "fat": 0.1,
        }
    )
    page.wait_for_timeout(500)
    page.evaluate(MEND)
    expect(card.locator(".row", has_text="Recovered pear")).to_have_count(1, timeout=TIMEOUT)


def test_the_streak_card_keeps_its_calendar_through_a_failed_refresh(
    home: Home, page: Page
) -> None:
    name = "Streak refresh e2e"
    with person_named(home, name):
        person = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == name)
        open_home(home, page)
        card = mount(page, "metron-streak-card", {"person": name})
        expect(card.locator(".today-line")).to_have_text("Nothing logged today", timeout=TIMEOUT)
        page.evaluate(BREAK)
        home.ws(
            {
                "type": "metron/entry/add",
                "person": person,
                "day": today(),
                "meal": "lunch",
                "name": "Refreshed soup e2e",
                "kcal": 300,
            }
        )
        # The change's refresh failed, and so did the reload it falls back to.
        page.wait_for_function("document.getElementById('mounted')._failure", timeout=TIMEOUT)
        # It keeps what it showed, and keeps trying.
        expect(card.locator(".cal")).to_be_visible()
        expect(card.locator(".error")).to_have_count(0)
        expect(card.locator(".today-line")).to_have_text("Nothing logged today")
        page.evaluate(MEND)
        expect(card.locator(".today-line")).to_have_text(
            re.compile(r" kcal left today$"), timeout=TIMEOUT
        )
        expect(card.locator(".error")).to_have_count(0)


def test_a_failed_food_search_is_shown_in_the_panel(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(
        page,
        "metron-food-diary-card",
        {"person": "Debora"},
        fail={"metron/food/recent": "boom"},
    )
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    card.locator('.meal[data-meal="lunch"] [data-action="add"]').dispatch_event("click")
    expect(card.locator(".panel .error")).to_have_text("Something went wrong: boom on purpose")


def test_a_double_tap_sends_once_and_a_late_reply_keeps_to_its_panel(
    home: Home, page: Page
) -> None:
    debora = next(p["id"] for p in home.ws({"type": "metron/people"}) if p["name"] == "Debora")
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)
    card = mount(
        page, "metron-food-diary-card", {"person": "Debora"}, slow={"metron/entry/add": 1500}
    )
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)

    def quick_add(name: str) -> None:
        card.locator('.meal[data-meal="snacks"] [data-action="add"]').dispatch_event("click")
        card.locator('[data-action="tab"][data-tab="quick"]').dispatch_event("click")
        card.locator('.panel [data-field="name"]').fill(name)
        card.locator('.panel [data-field="kcal"]').fill("120")

    def logged(name: str) -> int:
        day = home.ws({"type": "metron/day", "person": debora, "day": today})
        return sum(e["name"] == name for e in day["entries"])

    # Tapped twice while the first is on its way: logged once.
    quick_add("Double tap e2e")
    card.locator('[data-action="quick-add"]').dispatch_event("click")
    card.locator('[data-action="quick-add"]').dispatch_event("click")
    expect(card.locator(".row", has_text="Double tap e2e")).to_have_count(1, timeout=TIMEOUT)
    expect(card.locator(".panel")).to_be_hidden()
    page.wait_for_timeout(2000)
    assert logged("Double tap e2e") == 1

    # Cancelled, then another panel opened: the late reply leaves it open.
    quick_add("Late reply e2e")
    card.locator('[data-action="quick-add"]').dispatch_event("click")
    card.locator('[data-action="close"]').first.dispatch_event("click")
    card.locator('.meal[data-meal="dinner"] [data-action="copy"]').dispatch_event("click")
    expect(card.locator(".row", has_text="Late reply e2e")).to_have_count(1, timeout=TIMEOUT)
    # The change shows at once; the slowed reply comes after it.
    page.wait_for_timeout(2000)
    expect(card.locator('.panel [data-field="from_day"]')).to_be_visible()
