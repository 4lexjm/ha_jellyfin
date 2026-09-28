"""Unit tests for Jellyfin Config Flow and Options Flow."""
import pytest
from unittest.mock import MagicMock, patch

from custom_components.jellyfin_custom.config_flow import (
    JellyfinFlowHandler,
    JellyfinOptionsFlowHandler,
    CannotConnect,
    InvalidAuth,
    RESULT_CONN_ERROR,
    RESULT_AUTH_ERROR,
)
from homeassistant.const import (
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_VERIFY_SSL,
)
from homeassistant.config_entries import ConfigEntry


@pytest.mark.asyncio
async def test_config_flow_user_success():
    """Test successful config flow creating a valid entry."""
    flow = JellyfinFlowHandler()
    flow.hass = MagicMock()

    user_input = {
        CONF_URL: "http://192.168.1.100:8096",
        CONF_USERNAME: "alice",
        CONF_PASSWORD: "secretpassword",
        CONF_VERIFY_SSL: True,
        "generate_upcoming": False,
        "generate_yamc": False,
    }

    with patch("custom_components.jellyfin_custom.config_flow._validate_input") as mock_validate:
        mock_validate.return_value = {"AccessToken": "mock-token-xyz"}
        result = await flow.async_step_user(user_input)

    assert result["type"] == "create_entry"
    assert result["title"] == "Jellyfin"
    assert result["data"][CONF_URL] == "http://192.168.1.100:8096"
    assert result["data"][CONF_USERNAME] == "alice"


@pytest.mark.asyncio
async def test_config_flow_cannot_connect():
    """Test config flow error handling when server is unreachable."""
    flow = JellyfinFlowHandler()
    flow.hass = MagicMock()

    user_input = {
        CONF_URL: "http://192.168.1.254:8096",
        CONF_USERNAME: "alice",
        CONF_PASSWORD: "secretpassword",
        CONF_VERIFY_SSL: True,
        "generate_upcoming": False,
        "generate_yamc": False,
    }

    with patch("custom_components.jellyfin_custom.config_flow._validate_input", side_effect=CannotConnect):
        result = await flow.async_step_user(user_input)

    assert result["type"] == "form"
    assert result["errors"]["base"] == RESULT_CONN_ERROR


@pytest.mark.asyncio
async def test_config_flow_invalid_auth():
    """Test config flow error handling when credentials are wrong."""
    flow = JellyfinFlowHandler()
    flow.hass = MagicMock()

    user_input = {
        CONF_URL: "http://192.168.1.100:8096",
        CONF_USERNAME: "alice",
        CONF_PASSWORD: "wrongpassword",
        CONF_VERIFY_SSL: True,
        "generate_upcoming": False,
        "generate_yamc": False,
    }

    with patch("custom_components.jellyfin_custom.config_flow._validate_input", side_effect=InvalidAuth):
        result = await flow.async_step_user(user_input)

    assert result["type"] == "form"
    assert result["errors"]["base"] == RESULT_AUTH_ERROR


@pytest.mark.asyncio
async def test_options_flow():
    """Test options flow handling."""
    config_entry = ConfigEntry(
        data={
            CONF_URL: "http://192.168.1.100:8096",
            CONF_USERNAME: "alice",
            CONF_PASSWORD: "pw",
            CONF_VERIFY_SSL: True,
        }
    )
    flow = JellyfinOptionsFlowHandler(config_entry)
    flow.hass = MagicMock()

    # Initial form
    form_result = await flow.async_step_init()
    assert form_result["type"] == "form"

    # Submission with validation
    updated_input = {
        CONF_URL: "http://192.168.1.100:8096",
        CONF_USERNAME: "alice",
        CONF_PASSWORD: "newpw",
        CONF_VERIFY_SSL: False,
        "generate_upcoming": True,
        "generate_yamc": True,
    }

    with patch("custom_components.jellyfin_custom.config_flow._validate_input"):
        res = await flow.async_step_user(updated_input)

    assert res["type"] == "create_entry"
    assert res["data"]["generate_upcoming"] is True
