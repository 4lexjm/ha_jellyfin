"""Unit tests for Jellyfin Media Source."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from homeassistant.components.media_player.const import MediaClass, MediaType
from homeassistant.components.media_source.models import MediaSourceItem
from homeassistant.components.media_source.error import Unresolvable
from custom_components.jellyfin_custom.media_source import (
    JellyfinSource,
    Type2Mediatype,
    Type2Mediaclass,
    IsPlayable,
    async_library_items,
)


def test_parse_mediasource_identifier():
    """Test parsing media source identifiers."""
    # Full URI with domain prefix and type
    assert JellyfinSource.parse_mediasource_identifier("media-source://jellyfin_custom/Movie~~item-123") == ("Movie", "item-123")
    
    # Raw with split
    assert JellyfinSource.parse_mediasource_identifier("Episode~~ep-456") == ("Episode", "ep-456")
    
    # Library root
    assert JellyfinSource.parse_mediasource_identifier("media-source://jellyfin_custom/library") == (None, None)
    assert JellyfinSource.parse_mediasource_identifier("") == (None, None)
    assert JellyfinSource.parse_mediasource_identifier(None) == (None, None)
    
    # Single ID without split
    assert JellyfinSource.parse_mediasource_identifier("standalone-id") == (None, "standalone-id")


def test_type_mappings():
    """Test mapping Jellyfin types to HA classes and types."""
    assert Type2Mediatype("Movie") == MediaType.MOVIE
    assert Type2Mediatype("Series") == MediaType.TVSHOW
    assert Type2Mediatype("Episode") == MediaType.EPISODE
    assert Type2Mediatype("Audio") == MediaType.TRACK
    assert Type2Mediatype("MusicAlbum") == MediaType.ALBUM
    assert Type2Mediatype("MusicArtist") == MediaType.ARTIST

    assert Type2Mediaclass("Movie") == MediaClass.MOVIE
    assert Type2Mediaclass("Series") == MediaClass.TV_SHOW
    assert Type2Mediaclass("Folder") == MediaClass.DIRECTORY
    assert Type2Mediaclass("Audio") == MediaClass.TRACK


def test_is_playable():
    """Test playable logic."""
    assert IsPlayable("Movie", canPlayList=False) is True
    assert IsPlayable("Episode", canPlayList=False) is True
    assert IsPlayable("Audio", canPlayList=False) is True
    assert IsPlayable("Folder", canPlayList=False) is False
    assert IsPlayable("Series", canPlayList=False) is False
    assert IsPlayable("Series", canPlayList=True) is True


@pytest.mark.asyncio
async def test_resolve_media():
    """Test resolving media item to playable stream."""
    mock_hass = MagicMock()
    mock_manager = MagicMock()
    mock_manager.is_available = True
    mock_manager.get_stream_url = AsyncMock(return_value=("http://jf.local/stream.mp4", "video/mp4", "1080p"))

    source = JellyfinSource(mock_hass, mock_manager)
    item = MediaSourceItem("media-source://jellyfin_custom/Movie~~item-999")

    play_media = await source.async_resolve_media(item)
    assert play_media.url == "http://jf.local/stream.mp4"
    assert play_media.mime_type == "video/mp4"

    # Server unavailable raises Unresolvable
    mock_manager.is_available = False
    with pytest.raises(Unresolvable):
        await source.async_resolve_media(item)
