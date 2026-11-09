"""Adding the integration, and adding each person to it."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback

from .const import CONF_NAME, DOMAIN, SUBENTRY_PERSON
from .schema import vol

PERSON_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})


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
    """Add a person."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for a name no other person has, ignoring case."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            taken = {
                subentry.title.casefold()
                for subentry in self._get_entry().subentries.values()
                if subentry.subentry_type == SUBENTRY_PERSON
            }
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif name.casefold() in taken:
                errors[CONF_NAME] = "name_taken"
            else:
                return self.async_create_entry(title=name, data={CONF_NAME: name})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(PERSON_SCHEMA, user_input),
            errors=errors,
        )
