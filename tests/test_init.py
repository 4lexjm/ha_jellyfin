"""Unit tests for Jellyfin integration core logic."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)

from custom_components.jellyfin_custom import (
    JellyfinClientManager,
    JellyfinDevice,
)
from custom_components.jellyfin_custom.const import (
    STATE_PLAYING,
)


def test_normalize_url():
    """Test URL normalization logic."""
    # Plain HTTP adds port 8096 if missing
    assert (
        JellyfinClientManager.normalize_url("http://192.168.1.100") == "http://192.168.1.100:8096"
    )
    assert (
        JellyfinClientManager.normalize_url("http://192.168.1.100:8096/")
        == "http://192.168.1.100:8096"
    )
    assert JellyfinClientManager.normalize_url("192.168.1.100") == "http://192.168.1.100:8096"

    # HTTPS preserves portless reverse-proxy
    assert (
        JellyfinClientManager.normalize_url("https://jellyfin.example.com")
        == "https://jellyfin.example.com"
    )
    assert (
        JellyfinClientManager.normalize_url("https://jellyfin.example.com:8920/")
        == "https://jellyfin.example.com:8920"
    )

    # Custom path preserved
    assert (
        JellyfinClientManager.normalize_url("http://localhost:8096/jellyfin/")
        == "http://localhost:8096/jellyfin"
    )


def test_clean_none_dict_values():
    """Test recursive removal of None values in dicts."""
    raw = {
        "Id": "123",
        "NoneField": None,
        "Nested": {
            "Valid": "test",
            "Null": None,
        },
        "List": [{"A": 1, "B": None}, None, "ok"],
    }
    cleaned = JellyfinClientManager.clean_none_dict_values(raw)
    assert "NoneField" not in cleaned
    assert "Null" not in cleaned["Nested"]
    assert cleaned["Nested"]["Valid"] == "test"
    assert "B" not in cleaned["List"][0]


def test_parse_and_format_date():
    """Test safe date parsing without throwing exceptions on None or invalid values."""
    assert JellyfinClientManager._parse_and_format_date(None) is None
    assert JellyfinClientManager._parse_and_format_date("") is None
    assert JellyfinClientManager._parse_and_format_date("not-a-date") is None

    # Standard ISO string from Jellyfin
    iso_date = "2024-05-18T14:30:00.0000000Z"
    formatted = JellyfinClientManager._parse_and_format_date(iso_date, "%d/%m/%Y")
    assert formatted == "18/05/2024"

    year_only = JellyfinClientManager._parse_and_format_date(iso_date, "%Y")
    assert year_only == "2024"


def test_jellyfin_device_controls_and_aliases():
    """Verify that JellyfinDevice provides play/pause/stop/seek methods and backward-compat aliases."""
    mock_manager = MagicMock()
    mock_manager.set_playstate = AsyncMock()

    session = {
        "Id": "session-1",
        "DeviceId": "dev-1",
        "DeviceName": "Living Room TV",
        "Client": "Jellyfin Web",
        "UserName": "Alice",
        "SupportsRemoteControl": True,
        "PlayState": {
            "PositionTicks": 100000000,  # 10s
            "IsPaused": False,
        },
        "NowPlayingItem": {
            "Id": "item-100",
            "Name": "Big Buck Bunny",
            "Type": "Movie",
            "RunTimeTicks": 600000000,  # 60s
        },
    }

    device = JellyfinDevice(session, mock_manager)

    assert device.name == "Living Room TV"
    assert device.username == "Alice"
    assert device.media_title == "Big Buck Bunny"
    assert device.media_id == "item-100"
    assert device.media_position == 10.0
    assert device.media_runtime == 60.0
    assert device.media_percent_played == pytest.approx(16.6666, 0.01)
    assert device.state == STATE_PLAYING
    assert device.is_nowplaying is True
    assert device.supports_remote_control is True

    # Test playback control methods exist and call set_playstate
    assert hasattr(device, "play")
    assert hasattr(device, "pause")
    assert hasattr(device, "stop")
    assert hasattr(device, "next_track")
    assert hasattr(device, "previous_track")
    assert hasattr(device, "seek")

    # Aliases
    assert device.media_play == device.play
    assert device.media_pause == device.pause
    assert device.media_stop == device.stop
    assert device.media_next == device.next_track
    assert device.media_previous == device.previous_track
    assert device.media_seek == device.seek


@pytest.mark.asyncio
async def test_jellyfin_device_actions():
    """Test async execution of playback commands on JellyfinDevice."""
    mock_manager = MagicMock()
    mock_manager.set_playstate = AsyncMock()

    device = JellyfinDevice({"Id": "s-123"}, mock_manager)

    await device.play()
    mock_manager.set_playstate.assert_called_with("s-123", "Unpause", {})

    await device.pause()
    mock_manager.set_playstate.assert_called_with("s-123", "Pause", {})

    await device.stop()
    mock_manager.set_playstate.assert_called_with("s-123", "Stop", {})

    await device.seek(42.5)
    mock_manager.set_playstate.assert_called_with(
        "s-123", "Seek", {"SeekPositionTicks": 425000000, "static": "true"}
    )


@pytest.mark.asyncio
async def test_get_stream_url_jellyfin_12_compatibility():
    """Verify that get_stream_url generates ApiKey query param for Jellyfin 12.1 compatibility."""
    mock_hass = MagicMock()
    config = {
        CONF_URL: "http://192.168.1.50:8096",
        CONF_USERNAME: "test",
        CONF_PASSWORD: "pw",
        CONF_CLIENT_ID: "client-123",
        CONF_VERIFY_SSL: True,
    }
    manager = JellyfinClientManager(mock_hass, config)
    manager.jf_client = MagicMock()
    manager.jf_client.config.data = {
        "auth.server": "http://192.168.1.50:8096",
        "auth.token": "token-xyz-12345",
    }

    # Mock get_play_info returning direct stream support
    playback_info = {
        "MediaSources": [
            {
                "Id": "ms-1",
                "Container": "mp4",
                "SupportsDirectStream": True,
                "SupportsTranscoding": False,
                "Bitrate": 10000000,
                "MediaStreams": [{"Type": "Video", "Width": 1920, "Height": 1080, "Codec": "h264"}],
            }
        ]
    }
    manager.get_play_info = AsyncMock(return_value=playback_info)

    url, mimetype, info = await manager.get_stream_url("video-item-1", "Movie")

    assert "ApiKey=token-xyz-12345" in url
    assert "api_key=token-xyz-12345" in url
    assert mimetype == "video/mp4"
    assert "1920x1080 h264" in info


def test_callback_unlisteners_prevent_memory_leak():
    """Verify callback registrations return unlisteners and properly clean up."""
    mock_hass = MagicMock()
    config = {
        CONF_URL: "http://localhost:8096",
        CONF_USERNAME: "test",
        CONF_PASSWORD: "",
        CONF_CLIENT_ID: "cid",
        CONF_VERIFY_SSL: True,
    }
    manager = JellyfinClientManager(mock_hass, config)

    cb1 = MagicMock()
    unsub1 = manager.add_new_devices_callback(cb1)
    assert cb1 in manager._new_devices_callbacks

    unsub1()
    assert cb1 not in manager._new_devices_callbacks

    cb2 = MagicMock()
    unsub2 = manager.add_stale_devices_callback(cb2)
    assert cb2 in manager._stale_devices_callbacks

    unsub2()
    assert cb2 not in manager._stale_devices_callbacks

    cb3 = MagicMock()
    unsub3 = manager.add_update_callback(cb3, "device-1")
    assert [cb3, "device-1"] in manager._update_callbacks

    unsub3()
    assert [cb3, "device-1"] not in manager._update_callbacks
