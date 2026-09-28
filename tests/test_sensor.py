"""Unit tests for Jellyfin Sensor entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON

from custom_components.jellyfin_custom.sensor import JellyfinSensor


def test_sensor_properties_and_safe_fallbacks():
    """Test sensor properties with full server info vs None server info."""
    mock_manager = MagicMock()
    mock_manager.is_available = True
    mock_manager.server_url = "http://192.168.1.50:8096"
    mock_manager.info = {
        "Id": "server-id-abc",
        "ServerName": "MyMediaServer",
        "Version": "12.1.0",
        "OperatingSystem": "Linux",
        "HasUpdateAvailable": False,
    }
    mock_manager.data = [{"title": "Show 1"}]
    mock_manager.yamc = {"total_items": 10}

    sensor = JellyfinSensor(mock_manager)

    assert sensor.unique_id == "server-id-abc"
    assert sensor.name == "Jellyfin MyMediaServer"
    assert sensor.native_value == STATE_ON
    assert sensor.state == STATE_ON

    device_info = sensor.device_info
    assert device_info["name"] == "Jellyfin MyMediaServer"
    assert device_info["model"] == "Jellyfin 12.1.0"
    assert device_info["sw_version"] == "12.1.0"

    attrs = sensor.extra_state_attributes
    assert attrs["version"] == "12.1.0"
    assert attrs["os"] == "Linux"
    assert attrs["data"] == [{"title": "Show 1"}]
    assert attrs["yamc"] == {"total_items": 10}

    # Test safe fallback when info is None (server just started or offline)
    mock_manager.info = None
    mock_manager.data = None
    mock_manager.yamc = None
    mock_manager.is_available = False

    assert sensor.native_value == STATE_OFF
    assert sensor.state == STATE_OFF
    assert sensor.unique_id == "jellyfin_custom_http://192.168.1.50:8096"
    assert sensor.name == "Jellyfin"
    assert sensor.device_info["model"] == "Jellyfin Unknown"

    fallback_attrs = sensor.extra_state_attributes
    assert fallback_attrs["version"] is None
    assert fallback_attrs["update_available"] is False
    assert "data" not in fallback_attrs
    assert "yamc" not in fallback_attrs


@pytest.mark.asyncio
async def test_sensor_service_delegations():
    """Test sensor delegating services to JellyfinClientManager."""
    mock_manager = MagicMock()
    mock_manager.trigger_scan = AsyncMock()
    mock_manager.delete_item = AsyncMock()
    mock_manager.search_item = AsyncMock()
    mock_manager.yamc_set_page = AsyncMock()
    mock_manager.yamc_set_playlist = AsyncMock()

    sensor = JellyfinSensor(mock_manager)

    await sensor.async_trigger_scan()
    mock_manager.trigger_scan.assert_awaited_once()

    await sensor.async_delete_item("item-99")
    mock_manager.delete_item.assert_awaited_once_with("item-99")

    await sensor.async_search_item("matrix")
    mock_manager.search_item.assert_awaited_once_with("matrix")

    await sensor.async_yamc_setpage(3)
    mock_manager.yamc_set_page.assert_awaited_once_with(3)

    await sensor.async_yamc_setplaylist("latest_episodes")
    mock_manager.yamc_set_playlist.assert_awaited_once_with("latest_episodes")
