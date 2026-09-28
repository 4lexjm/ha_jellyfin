"""Config flow for Jellyfin Custom integration."""

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback

from . import JellyfinClientManager
from .const import (
    CONF_GENERATE_UPCOMING,
    CONF_GENERATE_YAMC,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

RESULT_CONN_ERROR = "cannot_connect"
RESULT_AUTH_ERROR = "invalid_auth"


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate user credentials by testing connection to the Jellyfin server."""
    url = JellyfinClientManager.normalize_url(data[CONF_URL])
    client = JellyfinClientManager.client_factory(data)

    def _test_connect():
        status = client.auth.connect_to_address(url)
        if not status or status.get("State") == 0:
            raise CannotConnect("Cannot reach Jellyfin server")

        result = client.auth.login(
            url,
            data[CONF_USERNAME],
            data.get(CONF_PASSWORD, ""),
        )
        if not result or "AccessToken" not in result:
            raise InvalidAuth("Invalid credentials")

        return result

    try:
        return await hass.async_add_executor_job(_test_connect)
    except (CannotConnect, InvalidAuth):
        raise
    except Exception as err:
        _LOGGER.error("Connection validation failed: %s", err)
        raise CannotConnect(str(err)) from err


@config_entries.HANDLERS.register(DOMAIN)
class JellyfinFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Jellyfin component."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Jellyfin options callback."""
        return JellyfinOptionsFlowHandler(config_entry)

    def __init__(self):
        """Init JellyfinFlowHandler."""
        self._errors = {}
        self._url = None
        self._ssl = DEFAULT_SSL
        self._verify_ssl = DEFAULT_VERIFY_SSL
        self._is_import = False

    async def async_step_import(self, user_input=None):
        """Handle configuration by yaml file."""
        self._is_import = True
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        data_schema = {
            vol.Required(CONF_URL): str,
            vol.Required(CONF_USERNAME): str,
            vol.Optional(CONF_PASSWORD, default=""): str,
            vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            vol.Optional(CONF_GENERATE_UPCOMING, default=False): bool,
            vol.Optional(CONF_GENERATE_YAMC, default=False): bool,
        }

        if user_input is not None:
            self._url = str(user_input[CONF_URL]).strip()
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            self._verify_ssl = user_input[CONF_VERIFY_SSL]
            self._generate_upcoming = user_input[CONF_GENERATE_UPCOMING]
            self._generate_yamc = user_input[CONF_GENERATE_YAMC]

            try:
                await _validate_input(self.hass, user_input)
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Jellyfin",
                    data={
                        CONF_URL: self._url,
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_VERIFY_SSL: self._verify_ssl,
                        CONF_CLIENT_ID: str(uuid.uuid4()),
                        CONF_GENERATE_UPCOMING: self._generate_upcoming,
                        CONF_GENERATE_YAMC: self._generate_yamc,
                    },
                )
            except CannotConnect:
                self._errors["base"] = RESULT_CONN_ERROR
            except InvalidAuth:
                self._errors["base"] = RESULT_AUTH_ERROR
            except Exception as err:
                _LOGGER.error("Unexpected error in config flow: %s", err)
                self._errors["base"] = "unknown"

            if self._is_import and self._errors:
                return self.async_abort(reason=self._errors.get("base", "unknown"))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=self._errors,
        )


class JellyfinOptionsFlowHandler(config_entries.OptionsFlow):
    """Option flow for Jellyfin component."""

    def __init__(self, config_entry):
        """Init JellyfinOptionsFlowHandler."""
        self._config_entry = config_entry
        self._errors = {}
        data = {**config_entry.data, **config_entry.options}
        self._url = data.get(CONF_URL)
        self._username = data.get(CONF_USERNAME)
        self._password = data.get(CONF_PASSWORD, "")
        self._verify_ssl = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self._generate_upcoming = data.get(CONF_GENERATE_UPCOMING, False)
        self._generate_yamc = data.get(CONF_GENERATE_YAMC, False)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        """Handle options update step."""
        self._errors = {}

        if user_input is not None:
            try:
                # Validate updated connection parameters
                await _validate_input(self.hass, user_input)
                return self.async_create_entry(title="", data=user_input)
            except CannotConnect:
                self._errors["base"] = RESULT_CONN_ERROR
            except InvalidAuth:
                self._errors["base"] = RESULT_AUTH_ERROR
            except Exception as err:
                _LOGGER.error("Unexpected error in options flow: %s", err)
                self._errors["base"] = "unknown"

        data_schema = {
            vol.Required(CONF_URL, default=self._url): str,
            vol.Required(CONF_USERNAME, default=self._username): str,
            vol.Optional(CONF_PASSWORD, default=self._password): str,
            vol.Optional(CONF_VERIFY_SSL, default=self._verify_ssl): bool,
            vol.Optional(CONF_GENERATE_UPCOMING, default=self._generate_upcoming): bool,
            vol.Optional(CONF_GENERATE_YAMC, default=self._generate_yamc): bool,
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=self._errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect to the server."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate authentication failed."""
