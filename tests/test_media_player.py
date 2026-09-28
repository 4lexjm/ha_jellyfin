"""Unit tests for Jellyfin MediaPlayer entity."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)

from custom_components.jellyfin_custom import JellyfinDevice
from custom_components.jellyfin_custom.media_player import (
    SUPPORT_JELLYFIN,
    JellyfinMediaPlayer,
)


@pytest.fixture
def mock_device_and_manager():
    """Create a mock JellyfinDevice and manager."""
    mock_manager = MagicMock()
    mock_manager.host = "http://192.168.1.50:8096"
    mock_manager.server_url = "http://192.168.1.50:8096"
    mock_manager.is_available = True
    mock_manager.devices = {}
    mock_manager.add_update_callback = MagicMock(return_value=lambda: None)

    session = {
        "Id": "sess-42",
        "DeviceId": "dev-tv-1",
        "DeviceName": "Living Room Kodi",
        "Client": "Kodi",
        "UserName": "Bob",
        "SupportsRemoteControl": True,
        "PlayState": {
            "PositionTicks": 50000000,
            "IsPaused": False,
        },
        "NowPlayingItem": {
            "Id": "movie-99",
            "Name": "Interstellar",
            "Type": "Movie",
            "RunTimeTicks": 1000000000,
        },
    }
    device = JellyfinDevice(session, mock_manager)
    mock_manager.devices["dev-tv-1"] = device
    return mock_manager, device


def test_media_player_supported_features(mock_device_and_manager):
    """Test supported features when remote control is supported vs not."""
    manager, device = mock_device_and_manager
    player = JellyfinMediaPlayer(manager, "dev-tv-1")

    # When remote control is supported
    assert player.supported_features == SUPPORT_JELLYFIN
    assert player.supported_features & MediaPlayerEntityFeature.PLAY
    assert player.supported_features & MediaPlayerEntityFeature.PAUSE
    assert player.supported_features & MediaPlayerEntityFeature.STOP
    assert player.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA
    assert player.supported_features & MediaPlayerEntityFeature.BROWSE_MEDIA

    # When remote control is disabled
    device.session["SupportsRemoteControl"] = False
    assert player.supported_features == MediaPlayerEntityFeature.BROWSE_MEDIA


def test_media_player_state_mapping(mock_device_and_manager):
    """Test state property mapping to MediaPlayerState."""
    manager, device = mock_device_and_manager
    player = JellyfinMediaPlayer(manager, "dev-tv-1")

    # Playing
    assert player.state == MediaPlayerState.PLAYING

    # Paused
    device.session["PlayState"]["IsPaused"] = True
    assert player.state == MediaPlayerState.PAUSED

    # Idle (no NowPlayingItem)
    device.session.pop("NowPlayingItem")
    assert player.state == MediaPlayerState.IDLE

    # Inactive / Off
    device.set_active(False)
    assert player.state == MediaPlayerState.OFF


def test_media_player_device_info(mock_device_and_manager):
    """Test Home Assistant device registry integration."""
    manager, _ = mock_device_and_manager
    player = JellyfinMediaPlayer(manager, "dev-tv-1")

    info = player.device_info
    assert ("jellyfin_custom", "dev-tv-1") in info["identifiers"]
    assert info["name"] == "Jellyfin Living Room Kodi"
    assert info["manufacturer"] == "Jellyfin"
    assert info["via_device"] == ("jellyfin_custom", "http://192.168.1.50:8096")


@pytest.mark.asyncio
async def test_media_player_playback_actions(mock_device_and_manager):
    """Test async playback actions work without AttributeError."""
    manager, device = mock_device_and_manager
    device.play = AsyncMock()
    device.pause = AsyncMock()
    device.stop = AsyncMock()
    device.next_track = AsyncMock()
    device.previous_track = AsyncMock()
    device.seek = AsyncMock()

    player = JellyfinMediaPlayer(manager, "dev-tv-1")

    await player.async_media_play()
    device.play.assert_awaited_once()

    await player.async_media_pause()
    device.pause.assert_awaited_once()

    await player.async_media_stop()
    device.stop.assert_awaited_once()

    await player.async_media_next_track()
    device.next_track.assert_awaited_once()

    await player.async_media_previous_track()
    device.previous_track.assert_awaited_once()

    await player.async_media_seek(15.0)
    device.seek.assert_awaited_once_with(15.0)


@pytest.mark.asyncio
async def test_media_player_async_play_media(mock_device_and_manager):
    """Test async_play_media with raw id and media-source URI."""
    manager, device = mock_device_and_manager
    device.play_media = AsyncMock()

    player = JellyfinMediaPlayer(manager, "dev-tv-1")

    # Regular media ID
    await player.async_play_media(MediaType.MOVIE, "item-12345")
    device.play_media.assert_awaited_with("item-12345")

    # Media Source URI
    await player.async_play_media(
        MediaType.MOVIE, "media-source://jellyfin_custom/Movie~~item-67890"
    )
    device.play_media.assert_awaited_with("item-67890")
