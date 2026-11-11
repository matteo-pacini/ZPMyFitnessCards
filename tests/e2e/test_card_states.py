"""Cards in states a person rarely sees: loading, failing, unlinked, removed.

These mount a card straight into the running Home Assistant page, with its
real connection, or with one that fails on purpose, and read what it shows.
The card sits outside the dashboard, under its launch screen, so clicks go
straight to the button as events.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import Home

TIMEOUT = 15_000

# Mount a card at #mounted. `fail` maps a command type (or "*") to the error
# code its calls reject with; "first" fails only the first call of each.
MOUNT = """
async ({ tag, config, fail, once, subscribeFails }) => {
  const base = document.querySelector("home-assistant").hass;
  const failed = new Set();
  const callWS = (message) => {
    const code = fail[message.type] ?? fail["*"];
    if (code && !(once && failed.has(message.type))) {
      failed.add(message.type);
      return Promise.reject({ code, message: `${code} on purpose` });
    }
    return base.callWS(message);
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


def mount(page: Page, tag: str, config: dict, fail=None, once=False, subscribe_fails=False):
    page.evaluate(
        MOUNT,
        {
            "tag": tag,
            "config": config,
            "fail": fail or {},
            "once": once,
            "subscribeFails": subscribe_fails,
        },
    )
    return page.locator("#mounted")


def test_load_errors_are_shown(home: Home, page: Page) -> None:
    open_home(home, page)
    for tag, config in (
        ("fork-and-scale-food-diary-card", {"person": "Debora"}),
        ("fork-and-scale-weight-card", {"person": "Debora"}),
        ("fork-and-scale-foods-card", {}),
    ):
        card = mount(page, tag, config, fail={"*": "boom"})
        expect(card.locator(".error")).to_have_text(
            "Something went wrong: boom on purpose", timeout=TIMEOUT
        )


def test_cards_wait_and_retry_while_the_integration_reloads(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(
        page,
        "fork-and-scale-food-diary-card",
        {"person": "Debora"},
        fail={"*": "not_loaded"},
        once=True,
    )
    expect(card.locator(".muted")).to_have_text("Loading…")
    # The card tries again after two seconds, and then the calls work.
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)


def test_a_failed_subscription_still_shows_the_card(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(page, "fork-and-scale-foods-card", {}, subscribe_fails=True)
    expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)


def test_says_who_the_card_cannot_find(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(page, "fork-and-scale-weight-card", {"person": "Nora"})
    expect(card.locator(".error")).to_contain_text("No person named Nora", timeout=TIMEOUT)
    card = mount(page, "fork-and-scale-food-diary-card", {"person": "Nora"})
    expect(card.locator(".error")).to_contain_text("No person named Nora", timeout=TIMEOUT)
    # Nobody is linked to the test owner, so a card without a person has no one.
    card = mount(page, "fork-and-scale-summary-card", {})
    expect(card.locator(".error")).to_contain_text("No person to show", timeout=TIMEOUT)


def test_a_failed_refresh_keeps_the_card_and_retries(home: Home, page: Page) -> None:
    matteo = next(
        p["id"] for p in home.ws({"type": "fork_and_scale/people"}) if p["name"] == "Matteo"
    )
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)
    card = mount(page, "fork-and-scale-weight-card", {"person": "Matteo"})
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
    home.ws({"type": "fork_and_scale/weight/set", "person": matteo, "day": today, "kg": 77.7})
    page.wait_for_timeout(500)
    # It keeps what it showed, and keeps trying.
    expect(card.locator(".chart")).to_be_visible()
    expect(card.locator(".body")).not_to_contain_text("77.7 kg")
    page.evaluate(
        "() => { const el = document.getElementById('mounted'); el._hass = el._working; }"
    )
    expect(card.locator(".body")).to_contain_text("77.7 kg", timeout=TIMEOUT)


def test_weight_card_shows_save_and_delete_errors(home: Home, page: Page) -> None:
    debora = next(
        p["id"] for p in home.ws({"type": "fork_and_scale/people"}) if p["name"] == "Debora"
    )
    home.ws({"type": "fork_and_scale/weight/set", "person": debora, "day": "2026-01-02", "kg": 70})
    open_home(home, page)
    card = mount(
        page,
        "fork-and-scale-weight-card",
        {"person": "Debora"},
        fail={"fork_and_scale/weight/set": "boom", "fork_and_scale/weight/delete": "boom"},
    )
    expect(card.locator(".chart")).to_be_visible(timeout=TIMEOUT)
    card.locator('[data-field="weight"]').fill("68")
    card.locator('[data-action="log"]').dispatch_event("click")
    expect(card.locator(".error")).to_have_text("Something went wrong: boom on purpose")
    card.locator('[data-action="delete-weight"]').first.dispatch_event("click")
    expect(card.locator(".error")).to_have_text("Something went wrong: boom on purpose")


def test_removed_cards_stop_listening(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(page, "fork-and-scale-food-diary-card", {"person": "Matteo"})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    # Listen only from here: Home Assistant's own frontend can reject a
    # promise or two while it boots.
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.evaluate(
        """() => {
          const el = document.getElementById("mounted");
          el.remove();
          const detail = { person: "x", day: "2026-01-01" };
          window.dispatchEvent(new CustomEvent("fork-and-scale-open-day", { detail }));
        }"""
    )
    expect(page.locator("#mounted")).to_have_count(0)
    page.wait_for_timeout(300)
    assert errors == []


def test_the_summary_card_gives_its_hass_back(home: Home, page: Page) -> None:
    open_home(home, page)
    mount(page, "fork-and-scale-summary-card", {"person": "Debora"})
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
    matteo = next(
        p["id"] for p in home.ws({"type": "fork_and_scale/people"}) if p["name"] == "Matteo"
    )
    today = page.evaluate(
        "() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(new Date())"
    )
    open_home(home, page)

    card = mount(page, "fork-and-scale-food-diary-card", {"person": "Matteo"})
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    page.evaluate(BREAK)
    home.ws(
        {
            "type": "fork_and_scale/entry/add",
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

    card = mount(page, "fork-and-scale-foods-card", {})
    expect(card.locator(".list")).to_be_visible(timeout=TIMEOUT)
    page.evaluate(BREAK)
    home.ws(
        {
            "type": "fork_and_scale/food/add",
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


def test_a_failed_food_search_is_shown_in_the_panel(home: Home, page: Page) -> None:
    open_home(home, page)
    card = mount(
        page,
        "fork-and-scale-food-diary-card",
        {"person": "Debora"},
        fail={"fork_and_scale/food/recent": "boom"},
    )
    expect(card.locator(".meal")).to_have_count(4, timeout=TIMEOUT)
    card.locator('.meal[data-meal="lunch"] [data-action="add"]').dispatch_event("click")
    expect(card.locator(".panel .error")).to_have_text("Something went wrong: boom on purpose")
