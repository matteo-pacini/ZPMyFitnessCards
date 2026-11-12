"""Active calories, as people use them: the draft's happy paths and edge cases.

Each flow runs on a Screen, a laptop's browser or a phone-sized one with
touch, and test_active_calories.py runs them all on both. They are H1 to H6,
E3 to E9 and E12 to E14 of the active calories draft, the ones with an
end-to-end layer in the spec's "Paths to test".

Activity is today's, so a flow can't keep to a day of its own as flows.py's
do. Each adds people of its own instead, named after the flow and the
screen, and sensors of its own through /api/states, and the Screen removes
them all afterwards. Their figures are the draft's: Anna is female, 35,
165 cm and 70 kg, at Light, so her goal is 1,368 kcal and Light allows for
244 kcal of activity.
"""

from __future__ import annotations

import re
import urllib.error
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, expect
from sqlalchemy import MetaData, Table, update

from custom_components.metron.db import make_engine

from ..schemas import contents
from . import flows
from .conftest import Home
from .flows import TIMEOUT, people, today, wait_for
from .test_actions import act, refused
from .test_card_states import mount, open_home
from .test_person_form import remove_person, type_number


@dataclass
class Screen(flows.Screen):
    """flows.Screen, which also removes what a flow adds, once it ends."""

    cleanup: ExitStack = field(default_factory=ExitStack)


# People


@dataclass(frozen=True)
class Who:
    """Whom a flow adds: the draft's people, losing 0.5 kg a week."""

    name: str
    sex: str
    age: int
    height_cm: float
    weight_kg: float
    activity: str

    def details(self) -> dict[str, Any]:
        """The person form's fields for them, but the name and active calories."""
        now = date.fromisoformat(today())
        return {
            "sex": self.sex,
            # Born on 1 January, so they are the same age all year.
            "birth_date": f"{now.year - self.age}-01-01",
            "height_cm": self.height_cm,
            "start_weight_kg": self.weight_kg,
            # A week ago, so the action can log the days since.
            "start_date": (now - timedelta(days=7)).isoformat(),
            "goal_weight_kg": self.weight_kg - 8,
            "activity": self.activity,
            "pace": "lose_0_5",
            "protein_pct": 25,
            "carbs_pct": 45,
            "fat_pct": 30,
        }


# Goal 1,368 kcal; Light allows for 244 kcal of activity.
ANNA = Who("Anna", "female", 35, 165, 70, "light")
# Goal 1,574 kcal; Sedentary allows for none.
BEN = Who("Ben", "male", 42, 180, 85, "sedentary")
# Goal 1,589 kcal; Moderate allows for 483 kcal.
DEBORA = Who("Debora", "female", 30, 165, 66, "moderate")


def entry_id(home: Home) -> str:
    [entry] = home.api("GET", "/api/config/config_entries/entry?domain=metron")
    return entry["entry_id"]


def add_person(
    s: Screen,
    who: Who,
    flow: str,
    *,
    enabled: bool = False,
    sensor: Sensor | None = None,
) -> str:
    """Add `who` for `flow` through the person form's REST API; return their name.

    Active calories are allowed if `enabled`, from `sensor` if given, at 75%
    and at most 1,500 kcal a day. They are removed when the flow ends.
    """
    name = s.name(f"{who.name} {flow}")
    section: dict[str, Any] = {
        "active_calories_enabled": enabled,
        "active_calories_share": 75,
        "active_calories_cap": 1500,
    }
    if sensor:
        section["active_calories_entity"] = sensor.entity_id
    data = {"name": name, **who.details(), "active_calories": section}
    subentries = "/api/config/config_entries/subentries/flow"
    form = s.home.api("POST", subentries, {"handler": [entry_id(s.home), "person"]})
    done = s.home.api("POST", f"{subentries}/{form['flow_id']}", data)
    assert done["type"] == "create_entry", done
    s.cleanup.callback(remove_person, s.home, name)
    wait_for(lambda: name in {p["name"] for p in people(s.home)})
    return name


def change_person(home: Home, name: str, **section: Any) -> None:
    """Change `name`'s active calories settings in `section` through the person
    form's REST API, as their Change details would, keeping the rest."""
    subentries = home.ws({"type": "config_entries/subentries/list", "entry_id": entry_id(home)})
    subentry = next(x["subentry_id"] for x in subentries if x["title"] == name)
    flow = "/api/config/config_entries/subentries/flow"
    handler = {"handler": [entry_id(home), "person"], "subentry_id": subentry}
    menu = home.api("POST", flow, handler)
    edit = home.api("POST", f"{flow}/{menu['flow_id']}", {"next_step_id": "edit"})
    shown: dict[str, Any] = {}
    for f in edit["data_schema"]:
        if f["name"] == "active_calories":
            shown["active_calories"] = {
                g["name"]: g["description"]["suggested_value"]
                for g in f["schema"]
                if "description" in g
            } | section
        elif "description" in f:
            shown[f["name"]] = f["description"]["suggested_value"]
    done = home.api("POST", f"{flow}/{edit['flow_id']}", shown)
    assert done["reason"] == "reconfigure_successful", done


def person_key(home: Home, name: str) -> str:
    return next(p["id"] for p in people(home) if p["name"] == name)


def the_day(home: Home, name: str, day: str | None = None) -> dict[str, Any]:
    """metron/day for `name` on `day`, today if not given."""
    message = {"type": "metron/day", "person": person_key(home, name), "day": day or today()}
    return home.ws(message)


def settled(home: Home, name: str, check: Callable[[dict[str, Any] | None], bool]) -> None:
    """Wait until today's `activity` for `name` passes `check`, as after a reload."""

    def passes() -> bool:
        try:
            return check(the_day(home, name)["activity"])
        except AssertionError, StopIteration:
            return False  # reloading

    wait_for(passes)


def goals_since(s: Screen, name: str, day: str) -> None:
    """Move `name`'s goals to `day`, as though they had stayed the same since.

    The integration only ever sets today's goals, and a past day needs goals
    in force for its activity to show: those of the day it was set, or an
    earlier one. A person added today has none before today, so the flows
    that log a past day give them some here, in the database itself. Today
    then has no goals of its own, as on most days.
    """
    engine = make_engine(s.home.db_url)
    try:
        goals = Table("goals", MetaData(), autoload_with=engine)
        with engine.begin() as conn:
            moved = conn.execute(
                update(goals).where(goals.c.person == person_key(s.home, name)).values(day=day)
            )
            assert moved.rowcount == 1
    finally:
        engine.dispose()


def goal_days(s: Screen, name: str) -> list[str]:
    """The days on which `name`'s goals were set, oldest first."""
    rows = contents(s.home.db_url, {"goals": ["person", "day"]})["goals"]
    return sorted(day for person, day in rows if person == person_key(s.home, name))


def state(home: Home, entity_id: str) -> str | None:
    """An entity's state, or None if Home Assistant doesn't have it."""
    try:
        return home.api("GET", f"/api/states/{entity_id}")["state"]
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def days_ago(n: int) -> str:
    return (date.fromisoformat(today()) - timedelta(days=n)).isoformat()


# Sensors, posted through /api/states, as the draft draws them

# Garmin Connect's "Active calories" and the iOS app's "Active Energy".
WATCH = {"unit_of_measurement": "kcal", "state_class": "total_increasing"}
# Google Health's "Active calories", and an energy sensor shown in kJ.
ENERGY_KCAL = {"unit_of_measurement": "kcal", "device_class": "energy"} | {
    "state_class": "total_increasing"
}
ENERGY_KJ = ENERGY_KCAL | {"unit_of_measurement": "kJ"}
# Withings' "Active calories burnt today".
WITHINGS = {"unit_of_measurement": "calories", "state_class": "total"}


def midnight(days: int = 0) -> str:
    """Local midnight, `days` from today's, as a sensor's last_reset gives it."""
    day = date.fromisoformat(today()) + timedelta(days=days)
    return datetime.combine(day, time(), ZoneInfo("Europe/London")).isoformat()


@dataclass
class Sensor:
    """A sensor of the flow's own, named after it and the screen."""

    home: Home
    entity_id: str
    name: str
    attributes: dict[str, Any]

    def post(self, state: float | str, **attributes: Any) -> None:
        """Set its state, as its integration would."""
        body = {"friendly_name": self.name, **self.attributes, **attributes}
        self.home.api(
            "POST", f"/api/states/{self.entity_id}", {"state": str(state), "attributes": body}
        )

    def delete(self) -> None:
        """Remove it from Home Assistant, as deleting or renaming it would."""
        try:
            self.home.api("DELETE", f"/api/states/{self.entity_id}")
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise


def sensor(
    s: Screen, name: str, attributes: dict[str, Any], state: float | str, **first: Any
) -> Sensor:
    """A sensor called `name` for this flow and screen, reading `state`; deleted afterwards.

    `first` are attributes of that first state only, such as a last_reset.
    """
    full = s.name(name)
    entity_id = "sensor." + re.sub(r"[^a-z0-9]+", "_", full.lower()).strip("_")
    made = Sensor(s.home, entity_id, full, attributes)
    s.cleanup.callback(made.delete)
    made.post(state, **first)
    return made


# Cards


def open_cards(s: Screen, person: str) -> tuple[Locator, Locator]:
    """`person`'s food diary and summary card, both on today, on one dashboard."""
    diary = {"type": "custom:metron-food-diary-card", "person": person}
    summary = {"type": "custom:metron-summary-card", "person": person}
    s.home.dashboard([diary, summary])
    s.page.goto(s.home.url + "/" + s.home.DASHBOARD + "/0")
    cards = s.page.locator("metron-food-diary-card"), s.page.locator("metron-summary-card")
    expect(cards[0].locator(".meal")).to_have_count(4, timeout=30_000)
    expect(cards[1].locator(".rings")).to_be_visible(timeout=30_000)
    return cards


def eat(s: Screen, person: str, kcal: float, day: str | None = None) -> None:
    """A quick add of `kcal` at breakfast."""
    s.entry(person, day or today(), "breakfast", name=s.name("Porridge"), kcal=kcal)


def expect_sum(diary: Locator, goal: str, activity: str, food: str, left: str) -> None:
    """The diary's sum: Goal + Activity - Food = Remaining."""
    figures = diary.locator(".summary.withactivity > div > b")
    expect(figures).to_have_text([goal, activity, food, left], timeout=TIMEOUT)


def expect_plain_sum(diary: Locator, goal: str, food: str, left: str) -> None:
    """The diary's sum on a day without activity, Goal - Food = Remaining, and no line."""
    figures = diary.locator(".summary:not(.withactivity) > div > b")
    expect(figures).to_have_text([goal, food, left], timeout=TIMEOUT)
    expect(diary.locator(".activity")).to_have_count(0)


def expect_line(diary: Locator, text: str) -> None:
    """The line under the diary's sum, which explains its Activity."""
    expect(diary.locator(".body > .activity")).to_have_text(text, timeout=TIMEOUT)


def expect_summary(summary: Locator, food: str, total: str, activity: str, left: str) -> None:
    """The summary card's line under its rings, and the kcal left in its ring."""
    line = f"{food} of {total} kcal, {activity} from activity"
    expect(summary.locator(".rings + .sub")).to_have_text(line, timeout=TIMEOUT)
    expect(summary.locator(".big .centre b")).to_have_text(left)


def step(s: Screen, diary: Locator, direction: str) -> None:
    """Move the diary a day back ("prev") or on ("next")."""
    s.tap(diary.locator(f'[data-action="{direction}"]'))


# The person form, in the browser


def change_details(s: Screen, name: str) -> Locator:
    """Open `name`'s Change person, then Change details; return the dialog."""
    s.page.goto(s.home.url + "/config/integrations/integration/metron")
    row = s.page.locator("ha-config-sub-entry-row", has_text=name)
    s.tap(row.get_by_role("button", name="Change person"))
    dialog = s.page.locator("dialog-data-entry-flow")
    s.tap(dialog.get_by_text("Change details"))
    expect(dialog.get_by_role("spinbutton", name="Height*")).to_be_visible(timeout=TIMEOUT)
    return dialog


def open_section(s: Screen, dialog: Locator) -> None:
    """Open the Active calories section, which starts closed while the box is unticked."""
    s.tap(dialog.get_by_text("Active calories", exact=True))
    expect(dialog.get_by_label("Allow active calories")).to_be_visible()


def tick(s: Screen, dialog: Locator) -> None:
    s.tap(dialog.get_by_label("Allow active calories"))


def pick(s: Screen, dialog: Locator, chosen: Sensor) -> None:
    """Choose `chosen` in the Sensor field, searching for it by name."""
    s.tap(dialog.locator('ha-picker-field[aria-label="Sensor (optional)"]'))
    s.type(dialog.locator("ha-picker-combo-box ha-input-search input"), chosen.name)
    s.tap(dialog.locator("ha-picker-combo-box ha-combo-box-item", has_text=chosen.name))


def submit(s: Screen, dialog: Locator) -> None:
    s.tap(dialog.get_by_role("button", name="Submit"))


def expect_saved(dialog: Locator) -> None:
    expect(dialog.get_by_text("Reconfiguration was successful")).to_be_visible(timeout=TIMEOUT)


def expect_refused(dialog: Locator, error: str) -> None:
    """The form's error, which shows just above the Active calories section."""
    alert = dialog.locator("ha-alert")
    expect(alert).to_have_text(error, timeout=TIMEOUT)
    section = dialog.locator("ha-form-expandable")
    assert alert.bounding_box()["y"] < section.bounding_box()["y"]


# Errors, as the person form and the action word them

UNIT = (
    "This sensor reports {}, not kcal or kJ. Convert it with a template sensor, or log it "
    "from an automation with the Log active calories action. The README shows both."
)
NO_UNIT = (
    "This sensor has no unit, so it can't be read as kcal or kJ. Choose one in kcal or kJ, "
    "give it a unit with a template sensor, or log it from an automation with the Log "
    "active calories action."
)
RUNNING_TOTAL = (
    "This sensor reads {} kcal, more than a day's activity: it looks like a total that "
    "never resets. Make a utility meter from it with a daily cycle, or log each day's "
    "total from an automation with the Log active calories action. The README shows both."
)
UNIT_SETTING = (
    "This sensor is shown in {}. Set its unit to kcal or kJ in its settings, then submit again."
)
MISSING = "This sensor doesn't exist in Home Assistant. Choose another, or clear the field."
SENSOR_DISABLED = (
    "A sensor is read only while active calories are allowed. Tick Allow active calories, "
    "or clear the sensor."
)
ACTION_DISABLED = (
    "Active calories are not allowed for {0}. Tick Allow active calories in {0}'s details, "
    "under Settings, Devices & services, Metron."
)

# The diary line's last sentence for Anna, at Light.
ANNA_ALLOWS = "The activity level already allows for 244 kcal of it."
ANNA_LEVEL = "The activity level already allows for 244 kcal, so none of it is added."


# Happy paths


def h1_allow_and_pick_a_sensor(s: Screen) -> None:
    """Anna allows active calories and picks her Garmin sensor."""
    active = sensor(s, "Garmin Active calories H1", WATCH, 80)
    sensor(s, "Garmin Calories H1", WATCH, 560)
    anna = add_person(s, ANNA, "H1")
    eat(s, anna, 325)
    dialog = change_details(s, anna)
    open_section(s, dialog)
    tick(s, dialog)
    # Share and cap keep their defaults.
    expect(dialog.get_by_role("spinbutton", name="Share counted*")).to_have_value("75")
    expect(dialog.get_by_role("spinbutton", name="Most counted a day*")).to_have_value("1500")
    pick(s, dialog, active)
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda a: a is not None and a["source"] == active.entity_id)

    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,368", "0", "325", "1,043")
    expect_line(
        diary,
        f"{active.name} measured 80 kcal. At 75%, that counts as 60 kcal. {ANNA_LEVEL}",
    )
    expect_summary(summary, "325", "1,368", "0", "1,043")
    active.post(500)
    expect_sum(diary, "1,368", "136", "325", "1,179")
    expect_summary(summary, "325", "1,504", "136", "1,179")


def h2_readings_rise_through_the_day(s: Screen) -> None:
    """Anna's day as the watch syncs: the cards follow each reading, with no reload."""
    watch = sensor(s, "Garmin Active calories H2", WATCH, 120)
    anna = add_person(s, ANNA, "H2", enabled=True, sensor=watch)
    eat(s, anna, 325)
    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,368", "0", "325", "1,043")
    expect_line(
        diary, f"{watch.name} measured 120 kcal. At 75%, that counts as 90 kcal. {ANNA_LEVEL}"
    )
    expect_summary(summary, "325", "1,368", "0", "1,043")

    watch.post(500)
    expect_sum(diary, "1,368", "136", "325", "1,179")
    expect_line(
        diary, f"{watch.name} measured 500 kcal. At 75%, that counts as 380 kcal. {ANNA_ALLOWS}"
    )
    expect_summary(summary, "325", "1,504", "136", "1,179")

    watch.post(906)
    expect_sum(diary, "1,368", "436", "325", "1,479")
    expect_line(
        diary, f"{watch.name} measured 906 kcal. At 75%, that counts as 680 kcal. {ANNA_ALLOWS}"
    )
    expect_summary(summary, "325", "1,804", "436", "1,479")
    # The sensors split the goal as the diary does.
    slug = anna.lower().replace(" ", "_")
    assert float(wait_for(lambda: state(s.home, f"sensor.{slug}_calorie_goal"))) == 1368
    wait_for(lambda: state(s.home, f"sensor.{slug}_activity") == "435.83")
    attributes = s.home.api("GET", f"/api/states/sensor.{slug}_activity")["attributes"]
    shown = [attributes[k] for k in ("measured", "counted", "share", "cap", "source", "status")]
    assert shown == [906, 680, 75, 1500, watch.entity_id, "counting"]


def h3_sedentary(s: Screen) -> None:
    """Ben, Sedentary: every counted kcal adds."""
    phone = sensor(s, "iPhone Active Energy H3", WATCH, 30)
    ben = add_person(s, BEN, "H3", enabled=True, sensor=phone)
    eat(s, ben, 410)
    diary, summary = open_cards(s, ben)
    none = "The activity level allows for none of it."
    expect_sum(diary, "1,574", "20", "410", "1,184")
    expect_line(diary, f"{phone.name} measured 30 kcal. At 75%, that counts as 20 kcal. {none}")
    expect_summary(summary, "410", "1,594", "20", "1,184")

    phone.post(240)
    expect_sum(diary, "1,574", "180", "410", "1,344")
    expect_summary(summary, "410", "1,754", "180", "1,344")

    phone.post(610)
    expect_sum(diary, "1,574", "460", "410", "1,624")
    expect_line(diary, f"{phone.name} measured 610 kcal. At 75%, that counts as 460 kcal. {none}")
    expect_summary(summary, "410", "2,034", "460", "1,624")


def h4_a_past_day(s: Screen) -> None:
    """Anna looks back: a past day keeps its sum and line; a day without activity has neither."""
    anna = add_person(s, ANNA, "H4", enabled=True)
    goals_since(s, anna, days_ago(3))
    eat(s, anna, 1050, days_ago(2))
    diary, summary = open_cards(s, anna)
    step(s, diary, "prev")
    # Yesterday has no activity, and the line is for days with some.
    expect_plain_sum(diary, "1,368", "0", "1,368")
    step(s, diary, "prev")
    expect_plain_sum(diary, "1,368", "1,050", "318")

    # Logged while it is open, the past day's sum and line change in place.
    act(s.home, "log_active_calories", anna, kcal=1240, day=days_ago(2))
    expect_sum(diary, "1,368", "686", "1,050", "1,004")
    expect_line(
        diary,
        f"Active calories logged: 1,240 kcal. At 75%, that counts as 930 kcal. {ANNA_ALLOWS}",
    )
    # Today's summary is unchanged.
    expect_summary(summary, "0", "1,368", "0", "1,368")

    step(s, diary, "prev")
    expect_plain_sum(diary, "1,368", "0", "1,368")
    step(s, diary, "next")
    expect_sum(diary, "1,368", "686", "1,050", "1,004")


def h5_the_action_with_no_sensor(s: Screen) -> None:
    """Debora's ring, through an automation: the action logs, and the line says so."""
    debora = add_person(s, DEBORA, "H5", enabled=True)
    eat(s, debora, 324)
    diary, summary = open_cards(s, debora)
    expect_sum(diary, "1,589", "0", "324", "1,265")
    expect_line(diary, "No active calories logged for today yet.")
    expect_summary(summary, "324", "1,589", "0", "1,265")

    act(s.home, "log_active_calories", debora, kcal=380)
    expect_line(
        diary,
        "Active calories logged: 380 kcal. At 75%, that counts as 280 kcal. "
        "The activity level already allows for 483 kcal, so none of it is added.",
    )
    expect_sum(diary, "1,589", "0", "324", "1,265")

    act(s.home, "log_active_calories", debora, kcal=900)
    expect_line(
        diary,
        "Active calories logged: 900 kcal. At 75%, that counts as 680 kcal. "
        "The activity level already allows for 483 kcal of it.",
    )
    expect_sum(diary, "1,589", "197", "324", "1,462")
    expect_summary(summary, "324", "1,786", "197", "1,462")


def h6_the_action_on_yesterday(s: Screen) -> None:
    """A late sync raises yesterday; today, with no goals of its own, is unchanged."""
    debora = add_person(s, DEBORA, "H6", enabled=True)
    goals_since(s, debora, days_ago(3))
    eat(s, debora, 1200, days_ago(1))
    assert goal_days(s, debora) == [days_ago(3)]
    diary, summary = open_cards(s, debora)
    step(s, diary, "prev")
    expect_plain_sum(diary, "1,589", "1,200", "389")

    act(s.home, "log_active_calories", debora, kcal=900, day=days_ago(1))
    expect_sum(diary, "1,589", "197", "1,200", "586")
    act(s.home, "log_active_calories", debora, kcal=1150, day=days_ago(1))
    expect_sum(diary, "1,589", "377", "1,200", "766")
    expect_line(
        diary,
        "Active calories logged: 1,150 kcal. At 75%, that counts as 860 kcal. "
        "The activity level already allows for 483 kcal of it.",
    )
    assert the_day(s.home, debora, days_ago(1))["goals"]["kcal"] == 1966

    step(s, diary, "next")
    expect_sum(diary, "1,589", "0", "0", "1,589")
    expect_line(diary, "No active calories logged for today yet.")
    expect_summary(summary, "0", "1,589", "0", "1,589")
    # Today first got goals of its own, a copy of those in force before.
    assert goal_days(s, debora) == [days_ago(3), days_ago(1), today()]
    assert the_day(s.home, debora)["goals"]["kcal"] == 1589
    assert the_day(s.home, debora, days_ago(2))["goals"]["kcal"] == 1589


# Edge cases


def e3_unavailable(s: Screen) -> None:
    """Garmin's service can't be reached: the reading from today holds."""
    watch = sensor(s, "Garmin Active calories E3", WATCH, 500)
    anna = add_person(s, ANNA, "E3", enabled=True, sensor=watch)
    eat(s, anna, 745)
    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,368", "136", "745", "759")

    watch.post("unavailable")
    expect_line(
        diary,
        f"{watch.name} is unavailable, so this uses its last reading from today, 500 kcal. "
        f"At 75%, that counts as 380 kcal. {ANNA_ALLOWS}",
    )
    expect_sum(diary, "1,368", "136", "745", "759")
    expect_summary(summary, "745", "1,504", "136", "759")

    watch.post(906)
    expect_line(
        diary, f"{watch.name} measured 906 kcal. At 75%, that counts as 680 kcal. {ANNA_ALLOWS}"
    )
    expect_sum(diary, "1,368", "436", "745", "1,059")
    expect_summary(summary, "745", "1,804", "436", "1,059")


def e4_over_the_cap(s: Screen) -> None:
    """A marathon day: over the daily limit, the limit counts."""
    watch = sensor(s, "Garmin Active calories E4", WATCH, 1850)
    anna = add_person(s, ANNA, "E4", enabled=True, sensor=watch)
    eat(s, anna, 845)
    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,368", "1,146", "845", "1,669")

    watch.post(2950)
    expect_line(
        diary,
        f"{watch.name} measured 2,950 kcal. At 75%, that is over the daily limit, "
        f"so 1,500 kcal counts. {ANNA_ALLOWS}",
    )
    expect_sum(diary, "1,368", "1,256", "845", "1,779")
    expect_summary(summary, "845", "2,624", "1,256", "1,779")


def e5_a_sensor_in_kj(s: Screen) -> None:
    """A sensor in kJ: the form takes it, and the diary shows kcal."""
    watch = sensor(s, "Watch Active energy E5", ENERGY_KJ, 3790)
    anna = add_person(s, ANNA, "E5")
    eat(s, anna, 745)
    dialog = change_details(s, anna)
    open_section(s, dialog)
    tick(s, dialog)
    pick(s, dialog, watch)
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda a: a is not None and a["source"] == watch.entity_id)

    diary, summary = open_cards(s, anna)
    # 3,790 kJ is 906 kcal.
    expect_line(
        diary, f"{watch.name} measured 906 kcal. At 75%, that counts as 680 kcal. {ANNA_ALLOWS}"
    )
    expect_sum(diary, "1,368", "436", "745", "1,059")
    watch.post(4184)
    expect_line(
        diary, f"{watch.name} measured 1,000 kcal. At 75%, that counts as 750 kcal. {ANNA_ALLOWS}"
    )
    expect_sum(diary, "1,368", "506", "745", "1,129")
    expect_summary(summary, "745", "1,874", "506", "1,129")


def e6_a_running_total(s: Screen) -> None:
    """A running total that never resets is refused, in kcal or kJ; a kJ day's total is not."""
    forever = sensor(s, "Watch Active calories total E6", WATCH, 48210)
    in_kj = sensor(s, "Watch Active energy total E6", ENERGY_KJ, 45000)
    today_kj = sensor(s, "Watch Active energy E6", ENERGY_KJ, 40000)
    anna = add_person(s, ANNA, "E6")
    dialog = change_details(s, anna)
    open_section(s, dialog)
    tick(s, dialog)
    pick(s, dialog, forever)
    submit(s, dialog)
    expect_refused(dialog, RUNNING_TOTAL.format(48210))
    # 45,000 kJ is 10,755 kcal.
    pick(s, dialog, in_kj)
    submit(s, dialog)
    expect_refused(dialog, RUNNING_TOTAL.format(10755))
    # 40,000 kJ is 9,560 kcal, under the limit.
    pick(s, dialog, today_kj)
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda a: a is not None and a["source"] == today_kj.entity_id)

    diary, summary = open_cards(s, anna)
    expect_line(
        diary,
        f"{today_kj.name} measured 9,560 kcal. At 75%, that is over the daily limit, "
        f"so 1,500 kcal counts. {ANNA_ALLOWS}",
    )
    expect_sum(diary, "1,368", "1,256", "0", "2,624")
    expect_summary(summary, "0", "2,624", "1,256", "2,624")
    today_kj.post(41000)
    expect_line(
        diary,
        f"{today_kj.name} measured 9,799 kcal. At 75%, that is over the daily limit, "
        f"so 1,500 kcal counts. {ANNA_ALLOWS}",
    )


def e7_a_typed_goal(s: Screen) -> None:
    """A typed calorie goal gets the activity on top, as the worked-out one does."""
    watch = sensor(s, "Garmin Active calories E7", WATCH, 120)
    anna = add_person(s, ANNA, "E7", enabled=True, sensor=watch)
    eat(s, anna, 325)
    dialog = change_details(s, anna)
    type_number(dialog, "Calorie goal", "1600")
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda _a: the_day(s.home, anna)["goals"]["kcal"] == 1600)

    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,600", "0", "325", "1,275")
    watch.post(906)
    expect_sum(diary, "1,600", "436", "325", "1,711")
    expect_line(
        diary, f"{watch.name} measured 906 kcal. At 75%, that counts as 680 kcal. {ANNA_ALLOWS}"
    )
    expect_summary(summary, "325", "2,036", "436", "1,711")


# What must stay on one line and inside a 300 px card, in German.
FITS = """
(sum) => {
  const card = sum.closest("ha-card");
  const line = card.querySelector(".body > .activity");
  const lines = (el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const tops = [...range.getClientRects()].filter((r) => r.width).map((r) => Math.round(r.top));
    return new Set(tops).size;
  };
  const problems = [];
  if (Math.round(card.getBoundingClientRect().width) !== 300) problems.push("card width");
  for (const el of [card, sum, line]) {
    if (el.scrollWidth > el.clientWidth) problems.push(`${el.className} overflows`);
  }
  const right = sum.getBoundingClientRect().right;
  for (const el of sum.querySelectorAll(":scope > div > b, :scope > div > small, :scope > .op")) {
    if (lines(el) > 1) problems.push(`${el.textContent} wraps`);
    if (el.getBoundingClientRect().right > right) problems.push(`${el.textContent} sticks out`);
  }
  return problems;
}
"""


def e8_german_on_a_narrow_card(s: Screen) -> None:
    """German on a 300 px card: the sum and the line fit, whatever the status.

    The figures are four digits wherever the status allows: the goal, the
    food, and, but for waiting, level and a missing sensor with nothing
    held, the activity and what remains.
    """
    old = sensor(s, "Garmin Active calories E8", WATCH, 1850)
    # Reset yesterday: this reading doesn't count today.
    new = sensor(s, "Garmin Active calories 2 E8", WATCH, 300, last_reset=midnight(-1))
    anna = add_person(s, ANNA, "E8", enabled=True, sensor=old)
    eat(s, anna, 1234)
    open_home(s.home, s.page)

    def fits(line: str, *figures: str) -> None:
        card = mount(s.page, "metron-food-diary-card", {"person": anna, "locale": "de"})
        card.evaluate("el => { el.style.display = 'block'; el.style.width = '300px'; }")
        expect_line(card, line)
        expect_sum(card, *figures)
        assert card.locator(".summary").evaluate(FITS) == []

    def measured(name: str, kcal: str) -> str:
        return f"{name} hat {kcal} kcal gemessen."

    # German puts a no-break space before %, which Playwright reads as a space.
    counts = "Davon zählen 75 %: 1.390 kcal."
    capped = "75 % davon liegen über dem Tageslimit, daher zählen 1.500 kcal."
    allows = "Das Aktivitätsniveau berücksichtigt davon bereits 244 kcal."
    gone = "Home Assistant hat {} nicht mehr. Wähle unter Einstellungen, Geräte & Dienste, Metron "
    gone += f"einen anderen Sensor für {anna}."

    fits(f"{measured(old.name, '1.850')} {counts} {allows}", "1.368", "1.146", "1.234", "1.280")
    old.post("unavailable")
    fits(
        f"{old.name} ist nicht verfügbar. Verwendet wird der letzte Wert von heute: 1.850 kcal. "
        f"{counts} {allows}",
        *("1.368", "1.146", "1.234", "1.280"),
    )
    old.post(2950)
    fits(f"{measured(old.name, '2.950')} {capped} {allows}", "1.368", "1.256", "1.234", "1.390")
    old.delete()
    fits(
        f"{gone.format(old.entity_id)} Bis dahin wird der letzte Wert von heute verwendet: "
        f"2.950 kcal. {capped} {allows}",
        *("1.368", "1.256", "1.234", "1.390"),
    )
    # A new sensor starts the day again, from nothing.
    change_person(s.home, anna, active_calories_entity=new.entity_id)
    settled(s.home, anna, lambda a: a is not None and a["source"] == new.entity_id)
    fits(f"{new.name} hat für heute noch keinen Wert.", "1.368", "0", "1.234", "134")
    new.delete()
    fits(gone.format(new.entity_id), "1.368", "0", "1.234", "134")
    new.post(120)
    fits(
        f"{measured(new.name, '120')} Davon zählen 75 %: 90 kcal. Das Aktivitätsniveau "
        "berücksichtigt bereits 244 kcal, daher kommt nichts hinzu.",
        *("1.368", "0", "1.234", "134"),
    )


def e9_the_sensor_is_removed(s: Screen) -> None:
    """The sensor is removed or renamed: the line says so, and a new one starts the day again.

    A Withings-style sensor, whose last_reset can say its reading is
    yesterday's, stands in for the next day: missing, with nothing held.
    """
    old = sensor(s, "Withings Active calories E9", WITHINGS, 500, last_reset=midnight(-1))
    new = sensor(s, "Withings Active calories 2 E9", WITHINGS, 400, last_reset=midnight())
    anna = add_person(s, ANNA, "E9", enabled=True, sensor=old)
    eat(s, anna, 325)
    diary, summary = open_cards(s, anna)
    expect_line(diary, f"{old.name} has no reading for today yet.")
    gone = (
        f"Home Assistant no longer has {old.entity_id}. Choose another sensor for {anna} in "
        "Settings, Devices & services, Metron."
    )

    old.delete()
    expect_line(diary, gone)
    expect_sum(diary, "1,368", "0", "325", "1,043")

    old.post(500, last_reset=midnight())
    expect_sum(diary, "1,368", "136", "325", "1,179")
    old.delete()
    expect_line(
        diary,
        f"{gone} Until then, this uses its last reading from today, 500 kcal. "
        f"At 75%, that counts as 380 kcal. {ANNA_ALLOWS}",
    )
    expect_sum(diary, "1,368", "136", "325", "1,179")
    expect_summary(summary, "325", "1,504", "136", "1,179")

    dialog = change_details(s, anna)
    submit(s, dialog)
    expect_refused(dialog, MISSING)
    pick(s, dialog, new)
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda a: a is not None and a["source"] == new.entity_id)
    diary, summary = open_cards(s, anna)
    # 400 from the new sensor, though 500 was held from the old one.
    expect_line(
        diary, f"{new.name} measured 400 kcal. At 75%, that counts as 300 kcal. {ANNA_ALLOWS}"
    )
    expect_sum(diary, "1,368", "56", "325", "1,099")
    expect_summary(summary, "325", "1,424", "56", "1,099")


def e12_the_action_refused(s: Screen) -> None:
    """The action for someone who hasn't allowed active calories is refused, and logs nothing."""
    debora = add_person(s, DEBORA, "E12")
    message = refused(s.home, "log_active_calories", debora, kcal=300)
    # Home Assistant drops an error's full stop when it answers an API call.
    assert message == ACTION_DISABLED.format(debora).removesuffix(".")

    s.page.goto(s.home.url + "/config/tools/action")
    s.tap(s.page.get_by_text("Action", exact=True).first)
    s.type(s.page.get_by_placeholder("Search"), "Log active calories")
    s.tap(s.page.get_by_text("Log active calories", exact=True))
    expect(s.page.get_by_text("metron.log_active_calories", exact=True)).to_be_visible()
    s.tap(s.page.get_by_text("Select a device"))
    s.tap(s.page.get_by_text(debora, exact=True))
    kcal = s.page.locator("ha-settings-row").filter(has=s.page.get_by_text("kcal", exact=True))
    s.tap(kcal.locator("#input"))
    s.page.keyboard.type("300")
    s.tap(s.page.get_by_role("button", name="Perform action"))
    expect(s.page.locator("ha-alert")).to_have_text(ACTION_DISABLED.format(debora), timeout=TIMEOUT)

    assert the_day(s.home, debora)["activity"] is None
    diary, _summary = open_cards(s, debora)
    expect_plain_sum(diary, "1,589", "0", "1,589")


def e13_a_sensor_with_the_box_unticked(s: Screen) -> None:
    """A sensor while the box is unticked is refused; ticking it saves."""
    watch = sensor(s, "Garmin Active calories E13", WATCH, 80)
    anna = add_person(s, ANNA, "E13")
    dialog = change_details(s, anna)
    open_section(s, dialog)
    pick(s, dialog, watch)
    submit(s, dialog)
    expect_refused(dialog, SENSOR_DISABLED)
    # The section stays open, with the error above it.
    tick(s, dialog)
    submit(s, dialog)
    expect_saved(dialog)
    settled(s.home, anna, lambda a: a is not None and a["source"] == watch.entity_id)
    diary, summary = open_cards(s, anna)
    expect_sum(diary, "1,368", "0", "0", "1,368")
    watch.post(500)
    expect_sum(diary, "1,368", "136", "0", "1,504")
    expect_summary(summary, "0", "1,504", "136", "1,504")


def e14_a_sensor_in_cal(s: Screen) -> None:
    """A sensor in cal, the small calorie, is refused, and nothing is saved."""
    small = sensor(s, "Watch Activity calories E14", {"unit_of_measurement": "cal"}, 412)
    anna = add_person(s, ANNA, "E14")
    dialog = change_details(s, anna)
    open_section(s, dialog)
    tick(s, dialog)
    pick(s, dialog, small)
    submit(s, dialog)
    expect_refused(dialog, UNIT.format("cal"))
    assert the_day(s.home, anna)["activity"] is None


FLOWS = [
    h1_allow_and_pick_a_sensor,
    h2_readings_rise_through_the_day,
    h3_sedentary,
    h4_a_past_day,
    h5_the_action_with_no_sensor,
    h6_the_action_on_yesterday,
    e3_unavailable,
    e4_over_the_cap,
    e5_a_sensor_in_kj,
    e6_a_running_total,
    e7_a_typed_goal,
    e8_german_on_a_narrow_card,
    e9_the_sensor_is_removed,
    e12_the_action_refused,
    e13_a_sensor_with_the_box_unticked,
    e14_a_sensor_in_cal,
]
