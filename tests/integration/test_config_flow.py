"""Adding the integration, and adding, changing and erasing people."""

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.metron.const import ACTIVE_CALORIES_DEFAULTS, DOMAIN, SUBENTRY_PERSON

from ..schemas import LATEST, set_version
from .conftest import mock_entry, person
from .test_translations import ENGLISH

FORM = {k: v for k, v in person().items() if k != "key"}


async def test_adds_the_integration_once_on_sqlite_by_default(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"engine": "sqlite"}

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def _add(
    hass: HomeAssistant, entry: MockConfigEntry, form: dict[str, Any] = FORM, **fields: Any
) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**form, **fields}
    )


def _people(entry: MockConfigEntry) -> dict[str, dict]:
    return {s.title: dict(s.data) for s in entry.subentries.values()}


async def test_adds_a_person_with_a_new_key(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add(hass, entry, name="  Nora ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    nora = _people(entry)["Nora"]
    assert nora["name"] == "Nora"
    assert len(nora["key"]) == 32
    assert nora["key"] not in {"debora", "matteo"}


async def test_rejects_bad_details(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _add(
        hass,
        entry,
        name="DEBORA",
        birth_date="2026-11-09",
        start_date="2026-11-10",
        protein_pct=30,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "name": "name_taken",
        "birth_date": "birth_date_future",
        "start_date": "start_date_future",
        "base": "macros_not_100",
    }
    result = await _add(hass, entry, name="   ")
    assert result["errors"] == {"name": "name_empty"}


async def test_the_birth_date_is_typed_and_checked(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    # A field the date can be typed into, which starts empty, not on today.
    config, suggested = _fields(result)["birth_date"]
    assert config["type"] == "date"
    assert suggested is None
    for typed, error in (
        ("", "birth_date_invalid"),
        ("15/03/1996", "birth_date_invalid"),
        ("1996-02-30", "birth_date_invalid"),
        ("1905-12-31", "birth_date_too_early"),
        ("2026-11-09", "birth_date_future"),
    ):
        result = await _add(hass, entry, name="Nora", birth_date=typed)
        assert result["errors"] == {"birth_date": error}, typed
    # The oldest a birth date can be: 120 years before this year began.
    result = await _add(hass, entry, name="Nora", birth_date="1906-01-01")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _people(entry)["Nora"]["birth_date"] == "1906-01-01"


async def test_re_adding_a_removed_person_brings_their_data_back(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await ws("weight/set", person="debora", day="2026-11-09", kg=67.5)
    await ws("entry/add", person="debora", day="2026-11-09", meal="lunch", name="Soup", kcal=300)
    await ws("meal/add", name="Her tea", owner="debora", items=[{"name": "Tea", "kcal": 2}])
    debora = next(s for s in entry.subentries.values() if s.title == "Debora")
    assert hass.config_entries.async_remove_subentry(entry, debora.subentry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.debora_weight") is None

    result = await _add(hass, entry, name="debora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _people(entry)["debora"]["key"] == "debora"
    # The same sensors, with her data.
    assert float(hass.states.get("sensor.debora_weight").state) == 67.5
    assert float(hass.states.get("sensor.debora_calories_today").state) == 300
    day = (await ws("day", person="debora", day="2026-11-09"))["result"]
    assert [e["name"] for e in day["entries"]] == ["Soup"]
    # Her meals became everyone's when she was removed, and stay so.
    meals = (await ws("meals"))["result"]
    assert [(m["name"], m["owner"]) for m in meals] == [("Her tea", None)]


@pytest.mark.parametrize("state", ["unloaded", "failed"])
async def test_re_adding_a_person_while_the_entry_is_not_loaded_brings_their_data_back(
    hass: HomeAssistant, entry: MockConfigEntry, state: str
) -> None:
    url = entry.runtime_data.data.db.url
    debora = next(s for s in entry.subentries.values() if s.title == "Debora")
    assert hass.config_entries.async_remove_subentry(entry, debora.subentry_id)
    await hass.async_block_till_done()
    if state == "unloaded":
        # As while it reloads, after another person was added.
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ConfigEntryState.NOT_LOADED
    else:
        set_version(url, LATEST + 1)
        assert not await hass.config_entries.async_reload(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_ERROR
    result = await _add(hass, entry, name="Debora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _people(entry)["Debora"]["key"] == "debora"


async def test_adding_a_person_says_when_the_database_cannot_be_read(
    hass: HomeAssistant,
) -> None:
    entry = mock_entry(
        person(),
        data={"engine": "postgresql", "db_url": "postgresql://postgres@/none?host=/nonexistent"},
    )
    entry.add_to_hass(hass)
    result = await _add(hass, entry, name="Nora")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "database_unavailable"}
    assert "Nora" not in _people(entry)


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, name: str) -> dict:
    subentry = next(s for s in entry.subentries.values() if s.title == name)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    return result


async def test_changes_a_person_keeping_their_key(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )
    assert result["step_id"] == "edit"
    # Keeping her own name is fine; another person's is not.
    taken = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**FORM, "name": "Matteo"}
    )
    assert taken["errors"] == {"name": "name_taken"}
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**FORM, "name": "Deb", "height_cm": 166}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert _people(entry)["Deb"] | {"key": "debora"} == _people(entry)["Deb"]
    assert _people(entry)["Deb"]["height_cm"] == 166


async def test_erases_a_person_s_data_after_confirming(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await ws("weight/set", person="debora", day="2026-11-09", kg=69.5)
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "erase"}
    )
    unconfirmed = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert unconfirmed["errors"] == {"confirm": "not_confirmed"}
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert done["reason"] == "erased"
    await hass.async_block_till_done()
    assert (await ws("weights", person="debora"))["result"] == []
    # The person stays.
    assert "Debora" in _people(entry)


async def _postgres_flow(hass: HomeAssistant, url: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"engine": "postgresql"}
    )
    assert result["step_id"] == "postgresql"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"db_url": url})


async def test_adds_the_integration_on_postgres(
    hass: HomeAssistant, postgres_database: str
) -> None:
    result = await _postgres_flow(hass, f" {postgres_database} ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"engine": "postgresql", "db_url": postgres_database}
    await hass.async_block_till_done()
    assert result["result"].runtime_data.data.db.url == postgres_database


async def test_rejects_postgres_urls_that_do_not_work(
    hass: HomeAssistant, postgres_server: str
) -> None:
    result = await _postgres_flow(hass, "mysql://user@host/db")
    assert result["errors"] == {"db_url": "invalid_url"}
    result = await _postgres_flow(hass, "postgresql://postgres@/nothing?host=/nonexistent")
    assert result["errors"] == {"db_url": "cannot_connect"}
    result = await _postgres_flow(hass, postgres_server.format(database="no_such_database"))
    assert result["errors"] == {"db_url": "cannot_connect"}


async def test_says_when_the_postgres_driver_is_missing(hass: HomeAssistant) -> None:
    with patch("custom_components.metron.config_flow.make_engine", side_effect=ImportError):
        result = await _postgres_flow(hass, "postgresql://user@host/db")
    assert result["errors"] == {"db_url": "no_driver"}


async def test_rejects_a_postgres_url_naming_an_unknown_driver(hass: HomeAssistant) -> None:
    result = await _postgres_flow(hass, "postgresql+nosuchdriver://user@host/db")
    assert result["errors"] == {"db_url": "invalid_url"}


async def test_a_person_added_while_unloaded_gets_a_new_key(hass: HomeAssistant) -> None:
    entry = mock_entry()
    entry.add_to_hass(hass)
    result = await _add(hass, entry, name="Nora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(_people(entry)["Nora"]["key"]) == 32


@pytest.mark.parametrize("step", ["import_history", "import_mfp", "export", "erase"])
async def test_steps_that_need_the_database_wait_for_it_to_load(
    hass: HomeAssistant, step: str
) -> None:
    entry = mock_entry(person())
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_importing_history_needs_the_recorder(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _reconfigure(hass, entry, "Debora")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "import_history"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_recorder"


# Units


WEIGHTS = ("start_weight_kg", "goal_weight_kg")
FORM_LB = {k: v for k, v in FORM.items() if k not in ("height_cm", *WEIGHTS)} | {
    "height_ft": 5,
    "height_in": 9,
    "start_weight_lb": 150,
    "goal_weight_lb": 135.5,
    "pace": "lose_1_lb",
}


def _fields(result: dict) -> dict[str, Any]:
    """The form's fields by name, as (selector config, suggested value).

    A section is (its options, its own fields) instead.
    """
    return _fields_of(result["data_schema"])


def _fields_of(schema: Any) -> dict[str, Any]:
    return {
        str(key): (
            (value.options, _fields_of(value.schema))
            if isinstance(value, section)
            else (value.config, (key.description or {}).get("suggested_value"))
        )
        for key, value in schema.schema.items()
    }


def _shown(result: dict) -> dict[str, Any]:
    """The values the form shows, as it would send them back."""
    return _shown_of(_fields(result))


def _shown_of(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        k: _shown_of(v) if isinstance(v, dict) else v
        for k, (_config, v) in fields.items()
        if v is not None
    }


async def _edit(hass: HomeAssistant, entry: MockConfigEntry, name: str) -> dict:
    result = await _reconfigure(hass, entry, name)
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit"}
    )


async def test_the_form_follows_the_unit_system(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    fields = _fields(result)
    assert fields["height_cm"][0]["unit_of_measurement"] == "cm"
    assert fields["start_weight_kg"][0]["unit_of_measurement"] == "kg"
    assert fields["pace"][0]["options"] == ["lose_0_75", "lose_0_5", "lose_0_25", "maintain"]

    hass.config.units = US_CUSTOMARY_SYSTEM
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    fields = _fields(result)
    assert "height_cm" not in fields
    assert "start_weight_kg" not in fields
    assert (fields["height_ft"][0]["unit_of_measurement"], fields["height_in"][0]["max"]) == (
        "ft",
        11,
    )
    assert fields["start_weight_lb"][0] | fields["goal_weight_lb"][0] == {
        "min": 44.1,
        "max": 881.8,
        "step": 0.1,
        "unit_of_measurement": "lb",
        "mode": "box",
    }
    assert fields["pace"][0]["options"] == ["lose_1_5_lb", "lose_1_lb", "lose_0_5_lb", "maintain"]
    # Every translated form names its new fields.
    for step in ("user", "edit"):
        for field in ("height_ft", "height_in", "start_weight_lb", "goal_weight_lb"):
            assert ENGLISH[f"config_subentries.person.step.{step}.data.{field}"]


@pytest.mark.usefixtures("us_customary")
async def test_adds_a_person_in_lb_feet_and_inches_stored_in_kg_and_cm(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _add(hass, entry, FORM_LB, name="Nora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    nora = _people(entry)["Nora"]
    assert (nora["start_weight_kg"], nora["goal_weight_kg"], nora["height_cm"]) == (
        68.04,
        61.46,
        175.26,
    )
    assert nora["pace"] == "lose_1_lb"
    assert not {"start_weight_lb", "goal_weight_lb", "height_ft", "height_in"} & nora.keys()


@pytest.mark.usefixtures("us_customary")
@pytest.mark.parametrize(("feet", "inches"), [(3, 3), (8, 3)])
async def test_refuses_a_height_out_of_range_in_feet_and_inches(
    hass: HomeAssistant, entry: MockConfigEntry, feet: int, inches: int
) -> None:
    result = await _add(hass, entry, FORM_LB, name="Nora", height_ft=feet, height_in=inches)
    assert result["errors"] == {"height_ft": "height_out_of_range"}
    assert "Nora" not in _people(entry)


async def test_changing_units_shows_the_stored_values_and_keeps_them(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    before = _people(entry)["Debora"]
    hass.config.units = US_CUSTOMARY_SYSTEM
    result = await _edit(hass, entry, "Debora")
    shown = _shown(result)
    # 165 cm, 70 kg and 62 kg.
    assert (shown["height_ft"], shown["height_in"]) == (5, 5)
    assert (shown["start_weight_lb"], shown["goal_weight_lb"]) == (154.3, 136.7)
    # Her pace in kg stays on offer, among the paces in lb.
    assert shown["pace"] == "lose_0_5"
    assert _fields(result)["pace"][0]["options"] == [
        "lose_1_5_lb",
        "lose_0_5",
        "lose_1_lb",
        "lose_0_5_lb",
        "maintain",
    ]

    # Saved as shown, nothing moves, though 154.3 lb is 69.99 kg. Active
    # calories, which she was saved without, are saved as their defaults.
    done = await hass.config_entries.subentries.async_configure(result["flow_id"], shown)
    assert done["reason"] == "reconfigure_successful"
    assert _people(entry)["Debora"] == before | ACTIVE_CALORIES_DEFAULTS

    result = await _edit(hass, entry, "Debora")
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], shown | {"goal_weight_lb": 130, "height_in": 6}
    )
    debora = _people(entry)["Debora"]
    assert (debora["goal_weight_kg"], debora["height_cm"]) == (58.97, 167.64)
    assert debora["start_weight_kg"] == before["start_weight_kg"]


@pytest.mark.usefixtures("us_customary")
async def test_a_person_added_in_lb_keeps_their_values_on_a_metric_install(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _add(hass, entry, FORM_LB, name="Nora")
    await hass.async_block_till_done()
    added = _people(entry)["Nora"]

    hass.config.units = METRIC_SYSTEM
    result = await _edit(hass, entry, "Nora")
    shown = _shown(result)
    assert (shown["height_cm"], shown["start_weight_kg"], shown["goal_weight_kg"]) == (
        175,
        68.0,
        61.5,
    )
    assert _fields(result)["pace"][0]["options"] == [
        "lose_0_75",
        "lose_0_5",
        "lose_1_lb",
        "lose_0_25",
        "maintain",
    ]
    await hass.config_entries.subentries.async_configure(result["flow_id"], shown)
    await hass.async_block_till_done()
    assert _people(entry)["Nora"] == added

    hass.config.units = US_CUSTOMARY_SYSTEM
    result = await _edit(hass, entry, "Nora")
    shown = _shown(result)
    assert (shown["start_weight_lb"], shown["goal_weight_lb"]) == (150, 135.5)
    assert (shown["height_ft"], shown["height_in"]) == (5, 9)


# Active calories


SECTION = "active_calories"
GARMIN = "sensor.garmin_connect_active_calories"
TICKED = {
    "active_calories_enabled": True,
    "active_calories_share": 75,
    "active_calories_cap": 1500,
}
ERRORS = (
    "active_calories_sensor_disabled",
    "active_calories_missing",
    "active_calories_unit",
    "active_calories_unit_setting",
    "active_calories_no_unit",
    "active_calories_running_total",
)


@pytest.fixture
def unloaded(hass: HomeAssistant) -> MockConfigEntry:
    """The integration's entry with no people, not set up: enough to add one."""
    entry = mock_entry()
    entry.add_to_hass(hass)
    return entry


def _garmin(hass: HomeAssistant) -> None:
    hass.states.async_set(
        GARMIN, "80", {"unit_of_measurement": "kcal", "state_class": "total_increasing"}
    )


async def _submit(hass: HomeAssistant, result: dict, active_calories: dict[str, Any]) -> dict:
    """Send the form as shown, with these active calories settings."""
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], _shown(result) | {SECTION: active_calories}
    )


async def test_the_section_comes_last_with_its_fields_in_order(
    hass: HomeAssistant, unloaded: MockConfigEntry
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (unloaded.entry_id, SUBENTRY_PERSON), context={"source": SOURCE_USER}
    )
    fields = _fields(result)
    assert list(fields)[-1] == SECTION
    options, inner = fields[SECTION]
    # Closed while the box is unticked.
    assert options == {"collapsed": True}
    assert list(inner) == [
        "active_calories_enabled",
        "active_calories_share",
        "active_calories_cap",
        "active_calories_entity",
    ]
    assert inner["active_calories_share"][0] == {
        "min": 0,
        "max": 100,
        "step": 1,
        "unit_of_measurement": "%",
        "mode": "box",
    }
    assert inner["active_calories_cap"][0] == {
        "min": 100,
        "max": 5000,
        "step": 50,
        "unit_of_measurement": "kcal",
        "mode": "box",
    }
    assert inner["active_calories_entity"][0]["domain"] == ["sensor"]
    # A new person starts unticked, at 75% and 1,500 kcal, with no sensor.
    assert _shown(result)[SECTION] == ACTIVE_CALORIES_DEFAULTS
    # Every translated form names and describes the section and its fields,
    # and the activity level and calorie goal say how they work with it.
    for step in ("user", "edit"):
        prefix = f"config_subentries.person.step.{step}."
        assert ENGLISH[f"{prefix}sections.{SECTION}.name"] == "Active calories"
        assert ENGLISH[f"{prefix}sections.{SECTION}.description"]
        for field in inner:
            assert ENGLISH[f"{prefix}sections.{SECTION}.data.{field}"]
            assert ENGLISH[f"{prefix}sections.{SECTION}.data_description.{field}"]
        assert "active calories" in ENGLISH[f"{prefix}data_description.activity"]
        assert "active calories" in ENGLISH[f"{prefix}data_description.calorie_goal"]
    for error in ERRORS:
        assert ENGLISH[f"config_subentries.person.error.{error}"]


async def test_the_frontend_gets_the_section_s_values_from_its_fields(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    # The frontend fills a section from the section's own default or
    # suggested value when it has one, and from its fields' otherwise.
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    reply = await client.post(
        "/api/config/config_entries/subentries/flow",
        json={"handler": [entry.entry_id, SUBENTRY_PERSON]},
    )
    [shown] = [f for f in (await reply.json())["data_schema"] if f["name"] == SECTION]
    assert shown["type"] == "expandable"
    assert shown["expanded"] is False
    assert "default" not in shown
    assert {f["name"]: f["description"]["suggested_value"] for f in shown["schema"][:3]} == (
        ACTIVE_CALORIES_DEFAULTS
    )


async def test_h1_ticking_the_box_with_a_kcal_sensor_saves_it_flat(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    _garmin(hass)
    result = await _edit(hass, entry, "Debora")
    done = await _submit(hass, result, TICKED | {"active_calories_entity": GARMIN})
    assert done["reason"] == "reconfigure_successful"
    debora = _people(entry)["Debora"]
    assert SECTION not in debora
    assert {k: v for k, v in debora.items() if k.startswith("active_calories")} == TICKED | {
        "active_calories_entity": GARMIN
    }
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # Opened again, the section is open and shows what she saved.
    result = await _edit(hass, entry, "Debora")
    options, _inner = _fields(result)[SECTION]
    assert options == {"collapsed": False}
    assert _shown(result)[SECTION] == TICKED | {"active_calories_entity": GARMIN}


async def test_a_person_saved_before_active_calories_opens_with_the_defaults(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    assert not {k for k in _people(entry)["Debora"] if k.startswith("active_calories")}
    result = await _edit(hass, entry, "Debora")
    options, _inner = _fields(result)[SECTION]
    assert options == {"collapsed": True}
    assert _shown(result)[SECTION] == {
        "active_calories_enabled": False,
        "active_calories_share": 75,
        "active_calories_cap": 1500,
    }


async def test_a_form_sent_without_the_section_saves_the_defaults(
    hass: HomeAssistant, unloaded: MockConfigEntry
) -> None:
    result = await _add(hass, unloaded, name="Nora")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _people(unloaded)["Nora"].items() >= ACTIVE_CALORIES_DEFAULTS.items()
    assert "active_calories_entity" not in _people(unloaded)["Nora"]


async def test_share_and_cap_are_saved_as_whole_numbers(
    hass: HomeAssistant, unloaded: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        unloaded,
        name="Nora",
        active_calories=TICKED | {"active_calories_share": 80.0, "active_calories_cap": 2000.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    nora = _people(unloaded)["Nora"]
    assert (nora["active_calories_share"], nora["active_calories_cap"]) == (80, 2000)
    assert type(nora["active_calories_share"]) is type(nora["active_calories_cap"]) is int


async def test_e13_a_sensor_needs_the_box_ticked(
    hass: HomeAssistant, unloaded: MockConfigEntry
) -> None:
    _garmin(hass)
    unticked = TICKED | {"active_calories_enabled": False, "active_calories_entity": GARMIN}
    result = await _add(hass, unloaded, name="Anna", active_calories=unticked)
    assert result["errors"] == {SECTION: "active_calories_sensor_disabled"}
    # Shown open, though the box is unticked, so the sensor can be seen.
    options, _inner = _fields(result)[SECTION]
    assert options == {"collapsed": False}
    assert _shown(result)[SECTION] == unticked
    assert "Anna" not in _people(unloaded)

    done = await _submit(hass, result, unticked | {"active_calories_enabled": True})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert _people(unloaded)["Anna"]["active_calories_entity"] == GARMIN


async def test_the_box_can_be_ticked_with_no_sensor(
    hass: HomeAssistant, unloaded: MockConfigEntry
) -> None:
    result = await _add(hass, unloaded, name="Anna", active_calories=TICKED)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    anna = _people(unloaded)["Anna"]
    assert anna["active_calories_enabled"] is True
    assert "active_calories_entity" not in anna


async def _edit_ticked(hass: HomeAssistant) -> tuple[MockConfigEntry, dict]:
    """Anna, saved with the box ticked and her Garmin, and her Change person form."""
    _garmin(hass)
    entry = mock_entry(person("Anna", **TICKED, active_calories_entity=GARMIN))
    entry.add_to_hass(hass)
    return entry, await _edit(hass, entry, "Anna")


async def test_clearing_the_sensor_removes_it(hass: HomeAssistant) -> None:
    entry, result = await _edit_ticked(hass)
    done = await _submit(hass, result, TICKED)
    assert done["reason"] == "reconfigure_successful"
    anna = _people(entry)["Anna"]
    assert "active_calories_entity" not in anna
    assert anna["active_calories_enabled"] is True


async def test_unticking_the_box_needs_the_sensor_cleared(hass: HomeAssistant) -> None:
    entry, result = await _edit_ticked(hass)
    unticked = TICKED | {"active_calories_enabled": False}
    refused = await _submit(hass, result, unticked | {"active_calories_entity": GARMIN})
    assert refused["errors"] == {SECTION: "active_calories_sensor_disabled"}
    assert _people(entry)["Anna"]["active_calories_enabled"] is True

    done = await _submit(hass, refused, unticked)
    assert done["reason"] == "reconfigure_successful"
    anna = _people(entry)["Anna"]
    assert anna["active_calories_enabled"] is False
    assert "active_calories_entity" not in anna
    # Unticked, the section is closed again.
    options, _inner = _fields(await _edit(hass, entry, "Anna"))[SECTION]
    assert options == {"collapsed": True}


async def test_e9_the_form_refuses_a_sensor_home_assistant_no_longer_has(
    hass: HomeAssistant,
) -> None:
    entry, result = await _edit_ticked(hass)
    hass.states.async_remove(GARMIN)
    # Submitted unchanged, it still names the old sensor.
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _shown(result)
    )
    assert refused["errors"] == {SECTION: "active_calories_missing"}

    garmin2 = f"{GARMIN}_2"
    hass.states.async_set(garmin2, "120", {"unit_of_measurement": "kcal"})
    done = await _submit(hass, refused, TICKED | {"active_calories_entity": garmin2})
    assert done["reason"] == "reconfigure_successful"
    assert _people(entry)["Anna"]["active_calories_entity"] == garmin2


# The units table of the spec, form column: the sensor's state and attributes,
# what the entity registry knows of it, then the form's error, without its
# "active_calories_" prefix, and the error's placeholders. No error: accepted.
UNIT = "unit_of_measurement"
ENERGY = {"device_class": "energy"}
WITHINGS = {UNIT: "calories", "state_class": "total", "last_reset": "2026-11-09T00:00:00+00:00"}
UNITS = {
    "kcal, Garmin": ("906", {UNIT: "kcal", "state_class": "total_increasing"}, None, None, {}),
    "kcal, energy": ("906", {UNIT: "kcal", **ENERGY}, None, None, {}),
    "calories, Withings": ("906", WITHINGS, None, None, {}),
    "E5 kJ": ("3790", {UNIT: "kJ"}, None, None, {}),
    "kJ, energy": ("3790", {UNIT: "kJ", **ENERGY}, None, None, {}),
    "Wh, energy": ("250", {UNIT: "Wh", **ENERGY}, None, "unit_setting", {"unit": "Wh"}),
    "kWh, energy": ("0.25", {UNIT: "kWh", **ENERGY}, None, "unit_setting", {"unit": "kWh"}),
    "cal, energy": ("906000", {UNIT: "cal", **ENERGY}, None, "unit_setting", {"unit": "cal"}),
    "E14 cal": ("906", {UNIT: "cal"}, None, "unit", {"unit": "cal"}),
    "W": ("120", {UNIT: "W"}, None, "unit", {"unit": "W"}),
    "steps": ("8000", {UNIT: "steps"}, None, "unit", {"unit": "steps"}),
    # Not an energy unit, so its settings can't offer kcal or kJ.
    "steps, energy": ("8000", {UNIT: "steps", **ENERGY}, None, "unit", {"unit": "steps"}),
    "%": ("40", {UNIT: "%"}, None, "unit", {"unit": "%"}),
    "no unit": ("906", {}, None, "no_unit", {}),
    "unavailable, registry kcal": ("unavailable", {}, {UNIT: "kcal"}, None, {}),
    "unknown, registry kJ": ("unknown", {}, {UNIT: "kJ"}, None, {}),
    "unavailable, no unit": ("unavailable", {}, {}, "no_unit", {}),
    "unavailable, registry Wh energy": (
        "unavailable",
        {},
        {UNIT: "Wh", "original_device_class": "energy"},
        "unit_setting",
        {"unit": "Wh"},
    ),
    "E9 unknown entity": (None, None, None, "missing", {}),
    "E6 10,000 kcal": ("10000", {UNIT: "kcal"}, None, None, {}),
    "E6 12,000 kcal": ("12000", {UNIT: "kcal"}, None, "running_total", {"reading": "12000"}),
    "E6 41,840 kJ": ("41840", {UNIT: "kJ"}, None, None, {}),
    "E6 41,850 kJ": ("41850", {UNIT: "kJ"}, None, "running_total", {"reading": "10002"}),
    "E6 45,000 kJ": ("45000", {UNIT: "kJ"}, None, "running_total", {"reading": "10755"}),
    "E6 30,000 kJ": ("30000", {UNIT: "kJ"}, None, None, {}),
}


@pytest.mark.parametrize(
    ("state", "attributes", "registered", "error", "placeholders"), UNITS.values(), ids=UNITS
)
async def test_the_form_checks_the_sensor_s_unit_and_reading(
    hass: HomeAssistant,
    unloaded: MockConfigEntry,
    state: str | None,
    attributes: dict[str, Any] | None,
    registered: dict[str, Any] | None,
    error: str | None,
    placeholders: dict[str, str],
) -> None:
    entity_id = "sensor.activity"
    if registered is not None:
        entity = er.async_get(hass).async_get_or_create(
            "sensor", "test", "activity", suggested_object_id="activity", **registered
        )
        assert entity.entity_id == entity_id
    if state is not None:
        hass.states.async_set(entity_id, state, attributes)
    result = await _add(
        hass, unloaded, name="Anna", active_calories=TICKED | {"active_calories_entity": entity_id}
    )
    if error is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert _people(unloaded)["Anna"]["active_calories_entity"] == entity_id
    else:
        assert result["errors"] == {SECTION: f"active_calories_{error}"}
        assert result["description_placeholders"] == placeholders
        assert _fields(result)[SECTION][0] == {"collapsed": False}
        assert "Anna" not in _people(unloaded)
