"""Adding the integration, and adding, changing and erasing each person."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_ACTIVITY,
    CONF_BIRTH_DATE,
    CONF_CALORIE_GOAL,
    CONF_CARBS_PCT,
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
    SEXES,
    SUBENTRY_PERSON,
)
from .data import today
from .goals import ACTIVITY, PACES
from .schema import vol

# Defaults for a new person: MyFitnessPal's default macro split.
DEFAULTS = {CONF_PROTEIN_PCT: 20, CONF_CARBS_PCT: 50, CONF_FAT_PCT: 30}

CONFIRM = "confirm"


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


def person_schema() -> vol.Schema:
    """The person form."""
    weight = _number(20, 400, 0.1, "kg")
    percent = _number(0, 100, 1, "%")
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Optional(CONF_PERSON_ENTITY): EntitySelector(EntitySelectorConfig(domain="person")),
            vol.Required(CONF_SEX): _choice(list(SEXES), CONF_SEX),
            vol.Required(CONF_BIRTH_DATE): DateSelector(),
            vol.Required(CONF_HEIGHT): _number(100, 250, 1, "cm"),
            vol.Required(CONF_START_WEIGHT): weight,
            vol.Required(CONF_START_DATE): DateSelector(),
            vol.Required(CONF_GOAL_WEIGHT): weight,
            vol.Required(CONF_ACTIVITY): _choice(list(ACTIVITY), CONF_ACTIVITY),
            vol.Required(CONF_PACE): _choice(list(PACES), CONF_PACE),
            vol.Optional(CONF_CALORIE_GOAL): _number(800, 6000, 10, "kcal"),
            vol.Required(CONF_PROTEIN_PCT): percent,
            vol.Required(CONF_CARBS_PCT): percent,
            vol.Required(CONF_FAT_PCT): percent,
        }
    )


def validate_person(values: dict[str, Any], other_names: set[str]) -> dict[str, str]:
    """Errors in a filled-in person form, by field."""
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
    if values[CONF_PROTEIN_PCT] + values[CONF_CARBS_PCT] + values[CONF_FAT_PCT] != 100:
        errors["base"] = "macros_not_100"
    return errors


class ZPMyFitnessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration. It takes no settings; people are sub-entries."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm, then create the entry."""
        if user_input is not None:
            return self.async_create_entry(title="ZPMyFitnessCards", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """People are the only sub-entries."""
        return {SUBENTRY_PERSON: PersonSubentryFlow}


class PersonSubentryFlow(ConfigSubentryFlow):
    """Add, change or erase a person."""

    def _names(self, exclude: str | None = None) -> set[str]:
        return {
            s.title.casefold()
            for s in self._get_entry().subentries.values()
            if s.subentry_type == SUBENTRY_PERSON and s.subentry_id != exclude
        }

    def _form(
        self, step_id: str, values: dict[str, Any], errors: dict[str, str]
    ) -> SubentryFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(person_schema(), values),
            errors=errors,
        )

    async def _key_for(self, name: str) -> str:
        """The key of someone removed earlier under this name, or a new one.

        Re-adding a person by their old name brings their data back.
        """
        entry = self._get_entry()
        if entry.state is ConfigEntryState.LOADED:
            active = {
                s.data[CONF_KEY]
                for s in entry.subentries.values()
                if s.subentry_type == SUBENTRY_PERSON
            }
            db = entry.runtime_data.data.db
            if key := await self.hass.async_add_executor_job(db.key_for_name, name, active):
                return key
        return uuid.uuid4().hex

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for the person's details."""
        if user_input is None:
            return self._form("user", {**DEFAULTS, CONF_START_DATE: today().isoformat()}, {})
        errors = validate_person(user_input, self._names())
        if errors:
            return self._form("user", user_input, errors)
        name = user_input[CONF_NAME].strip()
        data = {**user_input, CONF_NAME: name, CONF_KEY: await self._key_for(name)}
        return self.async_create_entry(title=name, data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the person, or erase their data."""
        return self.async_show_menu(step_id="reconfigure", menu_options=["edit", "erase"])

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Change the person's details."""
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self._form("edit", dict(subentry.data), {})
        errors = validate_person(user_input, self._names(exclude=subentry.subentry_id))
        if errors:
            return self._form("edit", user_input, errors)
        name = user_input[CONF_NAME].strip()
        # Optional fields left empty are absent, so build the data afresh.
        data = {**user_input, CONF_NAME: name, CONF_KEY: subentry.data[CONF_KEY]}
        return self.async_update_and_abort(self._get_entry(), subentry, title=name, data=data)

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
