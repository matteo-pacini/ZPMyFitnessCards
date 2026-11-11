"""Adding the integration, and adding, changing and erasing each person."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    FileSelector,
    FileSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from . import goals as g
from .const import (
    CONF_ACTIVITY,
    CONF_BIRTH_DATE,
    CONF_CALORIE_GOAL,
    CONF_CARBS_PCT,
    CONF_DB_URL,
    CONF_ENGINE,
    CONF_FAT_PCT,
    CONF_GOAL_WEIGHT,
    CONF_HEIGHT,
    CONF_KEY,
    CONF_NAME,
    CONF_PACE,
    CONF_PERSON_ENTITY,
    CONF_PROTEIN_PCT,
    CONF_SEX,
    CONF_START_DATE,
    CONF_START_WEIGHT,
    DOMAIN,
    ENGINE_POSTGRESQL,
    ENGINE_SQLITE,
    IMPORTED_MEAL,
    MAX_CM,
    MAX_KG,
    MAX_LB,
    MEALS,
    MIN_CM,
    MIN_KG,
    MIN_LB,
    SEXES,
    SOURCE_MYFITNESSPAL,
    SUBENTRY_PERSON,
)
from .data import database_url, today, uses_pounds
from .db import key_for_name, make_engine
from .export import PATH as EXPORT_PATH
from .goals import ACTIVITY, PACES
from .history import async_import_calories, async_import_weights, has_statistics
from .myfitnesspal import Diary, Unreadable, entries, other_meals, read, weights_kg
from .schema import vol

# Defaults for a new person: MyFitnessPal's default macro split.
DEFAULTS = {CONF_PROTEIN_PCT: 20, CONF_CARBS_PCT: 50, CONF_FAT_PCT: 30}

CONFIRM = "confirm"
CONF_WEIGHT_SENSOR = "weight_sensor"
CONF_CALORIES_SENSOR = "calories_sensor"
CONF_FILE = "file"
CONF_WEIGHT_UNIT = "weight_unit"

# The files "Import from MyFitnessPal" takes.
MYFITNESSPAL_FILES = ".zip,.csv,.html"

# How long the link "Export data" shows works.
EXPORT_LINK_MINUTES = 5

TITLE = "Fork & Scale"

# On US customary installs the person form asks for these instead of the
# weights in kg and the height in cm. The sub-entry stores kg and cm either way.
CONF_START_WEIGHT_LB = "start_weight_lb"
CONF_GOAL_WEIGHT_LB = "goal_weight_lb"
CONF_HEIGHT_FT = "height_ft"
CONF_HEIGHT_IN = "height_in"

# Each measurement the sub-entry stores, and the form's fields for it:
# (on metric installs, on US customary ones), so indexed by `pounds`.
MEASUREMENTS = {
    CONF_START_WEIGHT: ((CONF_START_WEIGHT,), (CONF_START_WEIGHT_LB,)),
    CONF_GOAL_WEIGHT: ((CONF_GOAL_WEIGHT,), (CONF_GOAL_WEIGHT_LB,)),
    CONF_HEIGHT: ((CONF_HEIGHT,), (CONF_HEIGHT_FT, CONF_HEIGHT_IN)),
}

# The paces each unit system offers.
PACES_KG = ("lose_0_75", "lose_0_5", "lose_0_25", "maintain")
PACES_LB = ("lose_1_5_lb", "lose_1_lb", "lose_0_5_lb", "maintain")


def _number(low: float, high: float, step: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low, max=high, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX
        )
    )


def _choice(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, translation_key=key, mode=SelectSelectorMode.LIST)
    )


def person_schema(pounds: bool, pace: str | None = None) -> vol.Schema:
    """The person form, in lb, feet and inches if `pounds`, else in kg and cm.

    It offers the unit system's paces, and `pace` as well if it is another's.
    """
    if pounds:
        start, goal, offered = CONF_START_WEIGHT_LB, CONF_GOAL_WEIGHT_LB, PACES_LB
        weight = _number(MIN_LB, MAX_LB, 0.1, "lb")
        height = {
            vol.Required(CONF_HEIGHT_FT): _number(3, 8, 1, "ft"),
            vol.Required(CONF_HEIGHT_IN): _number(0, 11, 1, "in"),
        }
    else:
        start, goal, offered = CONF_START_WEIGHT, CONF_GOAL_WEIGHT, PACES_KG
        weight = _number(MIN_KG, MAX_KG, 0.1, "kg")
        height = {vol.Required(CONF_HEIGHT): _number(MIN_CM, MAX_CM, 1, "cm")}
    percent = _number(0, 100, 1, "%")
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Optional(CONF_PERSON_ENTITY): EntitySelector(EntitySelectorConfig(domain="person")),
            vol.Required(CONF_SEX): _choice(list(SEXES), CONF_SEX),
            vol.Required(CONF_BIRTH_DATE): DateSelector(),
            **height,
            vol.Required(start): weight,
            vol.Required(CONF_START_DATE): DateSelector(),
            vol.Required(goal): weight,
            vol.Required(CONF_ACTIVITY): _choice(list(ACTIVITY), CONF_ACTIVITY),
            vol.Required(CONF_PACE): _choice(
                [p for p in PACES if p in offered or p == pace], CONF_PACE
            ),
            vol.Optional(CONF_CALORIE_GOAL): _number(800, 6000, 10, "kcal"),
            vol.Required(CONF_PROTEIN_PCT): percent,
            vol.Required(CONF_CARBS_PCT): percent,
            vol.Required(CONF_FAT_PCT): percent,
        }
    )


def _in_form(key: str, value: float, pounds: bool) -> tuple[float, ...]:
    """A stored measurement as its fields show it, rounded to their steps."""
    if key == CONF_HEIGHT:
        return g.cm_to_feet_inches(value) if pounds else (round(value),)
    return (round(g.kg_to_lb(value) if pounds else value, 1),)


def _from_form(key: str, fields: tuple[float, ...], pounds: bool) -> float:
    """A measurement's fields in kg or cm."""
    if not pounds:
        return fields[0]
    return g.feet_inches_to_cm(*fields) if key == CONF_HEIGHT else g.lb_to_kg(fields[0])


def shown(data: Mapping[str, Any], pounds: bool) -> dict[str, Any]:
    """A person's stored details as the form shows them."""
    out = {k: v for k, v in data.items() if k not in MEASUREMENTS}
    for key, fields in MEASUREMENTS.items():
        out |= zip(fields[pounds], _in_form(key, data[key], pounds), strict=True)
    return out


def stored(
    values: Mapping[str, Any], pounds: bool, before: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """A filled-in person form as the sub-entry stores it, in kg and cm.

    A measurement the form shows as it was `before` keeps its stored value,
    so saving a person again never moves it by a rounding.
    """
    form_keys = {f for fields in MEASUREMENTS.values() for f in fields[pounds]}
    out = {k: v for k, v in values.items() if k not in form_keys}
    for key, fields in MEASUREMENTS.items():
        typed = tuple(values[f] for f in fields[pounds])
        if before and typed == _in_form(key, before[key], pounds):
            out[key] = before[key]
        else:
            out[key] = _from_form(key, typed, pounds)
    return out


def validate_person(values: dict[str, Any], other_names: set[str]) -> dict[str, str]:
    """Errors in a filled-in person form, by field, from `values` as stored."""
    errors: dict[str, str] = {}
    name = values[CONF_NAME].strip()
    if not name:
        errors[CONF_NAME] = "name_empty"
    elif name.casefold() in other_names:
        errors[CONF_NAME] = "name_taken"
    if date.fromisoformat(values[CONF_BIRTH_DATE]) >= today():
        errors[CONF_BIRTH_DATE] = "birth_date_future"
    if date.fromisoformat(values[CONF_START_DATE]) > today():
        errors[CONF_START_DATE] = "start_date_future"
    if not MIN_CM <= values[CONF_HEIGHT] <= MAX_CM:
        # Only feet and inches can add up to this: the cm field has these limits.
        errors[CONF_HEIGHT_FT] = "height_out_of_range"
    if values[CONF_PROTEIN_PCT] + values[CONF_CARBS_PCT] + values[CONF_FAT_PCT] != 100:
        errors["base"] = "macros_not_100"
    return errors


def read_upload(hass: HomeAssistant, file_id: str) -> Diary:
    """Read an uploaded MyFitnessPal file, which is deleted afterwards. Blocks.

    Raises Unreadable, or ValueError when there is no such upload.
    """
    with process_uploaded_file(hass, file_id) as path:
        return read(path, today())


def check_database(url: str) -> str | None:
    """Try a Postgres URL. Return an error key, or None if it works. Blocks."""
    if not url.startswith(ENGINE_POSTGRESQL):
        return "invalid_url"
    try:
        engine = make_engine(url)
    except ImportError:
        return "no_driver"
    except ArgumentError:
        return "invalid_url"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return "cannot_connect"
    finally:
        engine.dispose()
    return None


class ForkAndScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration: choose where the data lives. People are sub-entries."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose SQLite, the default, or Postgres."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ENGINE, default=ENGINE_SQLITE): _choice(
                            [ENGINE_SQLITE, ENGINE_POSTGRESQL], CONF_ENGINE
                        )
                    }
                ),
            )
        if user_input[CONF_ENGINE] == ENGINE_POSTGRESQL:
            return await self.async_step_postgresql()
        return self.async_create_entry(title=TITLE, data={CONF_ENGINE: ENGINE_SQLITE})

    async def async_step_postgresql(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Postgres database's URL, and check it works."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_DB_URL].strip()
            error = await self.hass.async_add_executor_job(check_database, url)
            if error is None:
                return self.async_create_entry(
                    title=TITLE, data={CONF_ENGINE: ENGINE_POSTGRESQL, CONF_DB_URL: url}
                )
            errors[CONF_DB_URL] = error
        return self.async_show_form(
            step_id="postgresql",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_DB_URL): TextSelector()}), user_input
            ),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """People are the only sub-entries."""
        return {SUBENTRY_PERSON: PersonSubentryFlow}


class PersonSubentryFlow(ConfigSubentryFlow):
    """Add, change or erase a person, or import or export their data."""

    # What the MyFitnessPal file holds, between the import's steps.
    _diary: Diary
    # Where each meal of the file's own goes, by its title.
    _meals: dict[str, str]

    # Whether the person form last shown was in lb, feet and inches.
    _pounds: bool

    def _names(self, exclude: str | None = None) -> set[str]:
        return {
            s.title.casefold()
            for s in self._get_entry().subentries.values()
            if s.subentry_type == SUBENTRY_PERSON and s.subentry_id != exclude
        }

    def _form(
        self, step_id: str, values: Mapping[str, Any], errors: dict[str, str]
    ) -> SubentryFlowResult:
        # The answer comes in this form's units, even if the unit system changes
        # while it is open.
        self._pounds = uses_pounds(self.hass)
        schema = person_schema(self._pounds, values.get(CONF_PACE))
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, values),
            errors=errors,
        )

    async def _key_for(self, name: str) -> str:
        """The key of someone removed earlier under this name, or a new one.

        Re-adding a person by their old name brings their data back. The
        database is read directly, not through the loaded entry: adding a
        person reloads the entry, so the next person added may find it
        reloading, and it may have failed to set up. Raises SQLAlchemyError
        if the database cannot be read.
        """
        entry = self._get_entry()
        active = {
            s.data[CONF_KEY]
            for s in entry.subentries.values()
            if s.subentry_type == SUBENTRY_PERSON
        }
        url = database_url(self.hass, entry.data)
        key = await self.hass.async_add_executor_job(key_for_name, url, name, active)
        return key or uuid.uuid4().hex

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for the person's details."""
        if user_input is None:
            return self._form("user", {**DEFAULTS, CONF_START_DATE: today().isoformat()}, {})
        data = stored(user_input, self._pounds)
        errors = validate_person(data, self._names())
        if errors:
            return self._form("user", user_input, errors)
        name = data[CONF_NAME].strip()
        try:
            key = await self._key_for(name)
        except SQLAlchemyError:
            return self._form("user", user_input, {"base": "database_unavailable"})
        return self.async_create_entry(title=name, data={**data, CONF_NAME: name, CONF_KEY: key})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the person, or erase their data."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["edit", "import_mfp", "import_history", "export", "erase"],
        )

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Change the person's details."""
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self._form("edit", shown(subentry.data, uses_pounds(self.hass)), {})
        data = stored(user_input, self._pounds, subentry.data)
        errors = validate_person(data, self._names(exclude=subentry.subentry_id))
        if errors:
            return self._form("edit", user_input, errors)
        name = data[CONF_NAME].strip()
        # Optional fields left empty are absent, so build the data afresh.
        data = {**data, CONF_NAME: name, CONF_KEY: subentry.data[CONF_KEY]}
        return self.async_update_and_abort(self._get_entry(), subentry, title=name, data=data)

    async def async_step_import_history(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Copy weights and calories from the recorder's history of existing sensors."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if "recorder" not in self.hass.config.components:
            return self.async_abort(reason="no_recorder")
        errors: dict[str, str] = {}
        if user_input is not None:
            weight = user_input.get(CONF_WEIGHT_SENSOR)
            calories = user_input.get(CONF_CALORIES_SENSOR)
            if not weight and not calories:
                errors["base"] = "nothing_selected"
            for key, entity_id in ((CONF_WEIGHT_SENSOR, weight), (CONF_CALORIES_SENSOR, calories)):
                if entity_id and not has_statistics(self.hass, entity_id):
                    errors[key] = "no_statistics"
            if not errors:
                data = entry.runtime_data.data
                key = self._get_reconfigure_subentry().data[CONF_KEY]
                person = data.people[key]
                weights = (
                    await async_import_weights(self.hass, data, person, weight) if weight else 0
                )
                days = (
                    await async_import_calories(self.hass, data, person, calories)
                    if calories
                    else 0
                )
                return self.async_abort(
                    reason="imported",
                    description_placeholders={"weights": str(weights), "days": str(days)},
                )
        schema = vol.Schema(
            {
                vol.Optional(CONF_WEIGHT_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="weight")
                ),
                vol.Optional(CONF_CALORIES_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
            }
        )
        return self.async_show_form(
            step_id="import_history",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={"name": self._get_reconfigure_subentry().title},
        )

    async def async_step_import_mfp(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Read a MyFitnessPal export or saved printable diary."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        placeholders = {"name": self._get_reconfigure_subentry().title}
        if user_input is not None:
            try:
                diary = await self.hass.async_add_executor_job(
                    read_upload, self.hass, user_input[CONF_FILE]
                )
            except Unreadable as err:
                errors["base"] = err.key
                placeholders |= err.placeholders
            except ValueError:
                # No such upload: each is deleted once read, so sending it again fails.
                errors["base"] = "upload_again"
            else:
                if diary.foods or diary.weights:
                    self._diary, self._meals = diary, {}
                    return await self.async_step_import_mfp_meals()
                errors["base"] = "nothing_to_import"
        return self.async_show_form(
            step_id="import_mfp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FILE): FileSelector(
                        FileSelectorConfig(accept=MYFITNESSPAL_FILES)
                    )
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_import_mfp_meals(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask where each of the file's own meals goes, when it has any."""
        titles = other_meals(self._diary)
        if user_input is not None or not titles:
            self._meals = user_input or {}
            return await self.async_step_import_mfp_unit()
        # Each field is named after a meal's title, which the form shows as its label.
        meal = SelectSelector(
            SelectSelectorConfig(
                options=list(MEALS), translation_key="meal", mode=SelectSelectorMode.DROPDOWN
            )
        )
        return self.async_show_form(
            step_id="import_mfp_meals",
            data_schema=vol.Schema(
                {vol.Required(title, default=IMPORTED_MEAL): meal for title in titles}
            ),
        )

    async def async_step_import_mfp_unit(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask the unit of the file's weights, which it does not say, then import."""
        if not self._diary.weights:
            return await self._async_import_mfp([])
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            try:
                weights = weights_kg(self._diary, user_input[CONF_WEIGHT_UNIT])
            except Unreadable as err:
                errors["base"] = err.key
                placeholders = err.placeholders
            else:
                return await self._async_import_mfp(weights)
        unit = self._diary.weight_unit or ("lb" if uses_pounds(self.hass) else "kg")
        schema = vol.Schema(
            {vol.Required(CONF_WEIGHT_UNIT): _choice(["kg", "lb"], CONF_WEIGHT_UNIT)}
        )
        return self.async_show_form(
            step_id="import_mfp_unit",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or {CONF_WEIGHT_UNIT: unit}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _async_import_mfp(self, weights: list[tuple[str, float]]) -> SubentryFlowResult:
        """Replace the person's MyFitnessPal entries on the file's days, add weights, and say so."""
        data = self._get_entry().runtime_data.data
        person = data.people[self._get_reconfigure_subentry().data[CONF_KEY]]
        foods = entries(self._diary, self._meals)
        if foods:
            await data.async_replace_entries(
                person.key, SOURCE_MYFITNESSPAL, foods[0]["day"], foods[-1]["day"], foods
            )
        added = await data.async_add_weights(person, weights)
        return self.async_abort(
            reason="mfp_imported",
            description_placeholders={
                "days": str(len({f["day"] for f in foods})),
                "entries": str(len(foods)),
                "weights": str(added),
                "skipped": str(len(weights) - added),
            },
        )

    async def async_step_export(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show a link to download the person's data, signed for whoever is signed in."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        subentry = self._get_reconfigure_subentry()
        url = async_sign_path(
            self.hass,
            EXPORT_PATH.format(person=subentry.data[CONF_KEY]),
            timedelta(minutes=EXPORT_LINK_MINUTES),
        )
        return self.async_abort(
            reason="exported",
            description_placeholders={
                "name": subentry.title,
                # An HTML link, not markdown: the frontend opens links to its
                # own pages in place, unless they have a target. The tags are
                # placeholders because translations may not hold HTML.
                "link": f'<a href="{url}" target="_blank">',
                "link_end": "</a>",
                "minutes": str(EXPORT_LINK_MINUTES),
            },
        )

    async def async_step_erase(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Delete every entry and weight logged for the person, after a confirmation."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is None or not user_input.get(CONFIRM):
            return self.async_show_form(
                step_id="erase",
                data_schema=vol.Schema({vol.Required(CONFIRM, default=False): BooleanSelector()}),
                errors={} if user_input is None else {CONFIRM: "not_confirmed"},
                description_placeholders={"name": self._get_reconfigure_subentry().title},
            )
        key = self._get_reconfigure_subentry().data[CONF_KEY]
        await entry.runtime_data.data.async_delete_person_data(key)
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="erased")
