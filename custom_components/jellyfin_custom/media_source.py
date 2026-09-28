"""Media source platform for Jellyfin integration."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import BrowseError
from homeassistant.components.media_player.const import MediaClass, MediaType
from homeassistant.components.media_source.const import MEDIA_MIME_TYPES, URI_SCHEME
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from . import JellyfinClientManager, autolog
from .const import DOMAIN

PLAYABLE_MEDIA_TYPES = [
    MediaType.ALBUM,
    MediaType.ARTIST,
    MediaType.TRACK,
]

CONTAINER_TYPES_SPECIFIC_MEDIA_CLASS = {
    MediaType.ALBUM: MediaClass.ALBUM,
    MediaType.ARTIST: MediaClass.ARTIST,
    MediaType.PLAYLIST: MediaClass.PLAYLIST,
    MediaType.SEASON: MediaClass.SEASON,
    MediaType.TVSHOW: MediaClass.TV_SHOW,
}

CHILD_TYPE_MEDIA_CLASS = {
    MediaType.SEASON: MediaClass.SEASON,
    MediaType.ALBUM: MediaClass.ALBUM,
    MediaType.ARTIST: MediaClass.ARTIST,
    MediaType.MOVIE: MediaClass.MOVIE,
    MediaType.PLAYLIST: MediaClass.PLAYLIST,
    MediaType.TRACK: MediaClass.TRACK,
    MediaType.TVSHOW: MediaClass.TV_SHOW,
    MediaType.CHANNEL: MediaClass.CHANNEL,
    MediaType.EPISODE: MediaClass.EPISODE,
}

IDENTIFIER_SPLIT = "~~"

_LOGGER = logging.getLogger(__name__)


class UnknownMediaType(BrowseError):
    """Unknown media type."""


async def async_get_media_source(hass: HomeAssistant) -> JellyfinSource:
    """Set up Jellyfin media source."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return JellyfinSource(hass, None)

    entry = entries[0]
    manager = None
    if hasattr(entry, "runtime_data") and entry.runtime_data:
        manager = entry.runtime_data
    else:
        url_key = entry.data.get(CONF_URL)
        if url_key and DOMAIN in hass.data and url_key in hass.data[DOMAIN]:
            manager = hass.data[DOMAIN][url_key].get("manager")

    return JellyfinSource(hass, manager)


class JellyfinSource(MediaSource):
    """Media source for Jellyfin."""

    @staticmethod
    def parse_mediasource_identifier(
        identifier: str,
    ) -> tuple[str | None, str | None]:
        """Parse identifier into media_content_type and media_content_id."""
        if not identifier:
            return None, None

        prefix = f"{URI_SCHEME}{DOMAIN}/"
        text = identifier
        if identifier.startswith(prefix):
            text = identifier[len(prefix) :]

        if IDENTIFIER_SPLIT in text:
            parts = text.split(IDENTIFIER_SPLIT, 1)
            return parts[0], parts[1]

        if text in ("", "library"):
            return None, None

        return None, text

    def __init__(self, hass: HomeAssistant, manager: JellyfinClientManager | None):
        """Initialize Jellyfin media source."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.jelly_cm = manager

    def _ensure_manager(self) -> JellyfinClientManager | None:
        """Ensure manager is available or refresh from config entries."""
        if self.jelly_cm is not None:
            return self.jelly_cm

        entries = self.hass.config_entries.async_entries(DOMAIN)
        if entries:
            entry = entries[0]
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                self.jelly_cm = entry.runtime_data
            else:
                url_key = entry.data.get(CONF_URL)
                if url_key and DOMAIN in self.hass.data and url_key in self.hass.data[DOMAIN]:
                    self.jelly_cm = self.hass.data[DOMAIN][url_key].get("manager")

        return self.jelly_cm

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable item."""
        autolog("<<<")
        manager = self._ensure_manager()
        if not manager or not manager.is_available:
            raise Unresolvable("Jellyfin server is not available.")

        if not item or not item.identifier:
            raise Unresolvable("No media identifier provided.")

        media_content_type, media_content_id = self.parse_mediasource_identifier(item.identifier)
        if not media_content_id:
            raise Unresolvable(f"Could not parse identifier {item.identifier}")

        stream_info = await manager.get_stream_url(media_content_id, media_content_type)
        if not stream_info or not stream_info[0]:
            raise Unresolvable(f"Unable to get playable stream for {media_content_id}")

        return PlayMedia(stream_info[0], stream_info[1])

    async def async_browse_media(
        self, item: MediaSourceItem, media_types: tuple[str] = MEDIA_MIME_TYPES
    ) -> BrowseMediaSource:
        """Browse media library."""
        autolog("<<<")
        manager = self._ensure_manager()
        if not manager:
            raise Unresolvable("Jellyfin integration is not configured.")

        media_content_type, media_content_id = self.parse_mediasource_identifier(item.identifier)
        return await async_library_items(
            manager, media_content_type, media_content_id, canPlayList=False
        )


def Type2Mediatype(jf_type: str) -> MediaType | None:
    """Map Jellyfin item type to Home Assistant MediaType."""
    switcher = {
        "Movie": MediaType.MOVIE,
        "Series": MediaType.TVSHOW,
        "Season": MediaType.SEASON,
        "Episode": MediaType.EPISODE,
        "Music": MediaType.ALBUM,
        "Audio": MediaType.TRACK,
        "MusicArtist": MediaType.ARTIST,
        "MusicAlbum": MediaType.ALBUM,
        "Playlist": MediaType.PLAYLIST,
    }
    return switcher.get(jf_type, MediaType.VIDEO)


def Type2Mediaclass(jf_type: str) -> MediaClass:
    """Map Jellyfin item type to Home Assistant MediaClass."""
    switcher = {
        "Movie": MediaClass.MOVIE,
        "Series": MediaClass.TV_SHOW,
        "Season": MediaClass.SEASON,
        "Episode": MediaClass.EPISODE,
        "Music": MediaClass.DIRECTORY,
        "BoxSet": MediaClass.DIRECTORY,
        "Folder": MediaClass.DIRECTORY,
        "CollectionFolder": MediaClass.DIRECTORY,
        "Playlist": MediaClass.PLAYLIST,
        "PlaylistsFolder": MediaClass.DIRECTORY,
        "ManualPlaylistsFolder": MediaClass.DIRECTORY,
        "MusicArtist": MediaClass.ARTIST,
        "MusicAlbum": MediaClass.ALBUM,
        "Audio": MediaClass.TRACK,
    }
    return switcher.get(jf_type, MediaClass.DIRECTORY)


def IsPlayable(jf_type: str, canPlayList: bool) -> bool:
    """Check if Jellyfin item type is directly playable."""
    switcher = {
        "Movie": True,
        "Series": canPlayList,
        "Season": canPlayList,
        "Episode": True,
        "Music": False,
        "BoxSet": canPlayList,
        "Folder": False,
        "CollectionFolder": False,
        "Playlist": canPlayList,
        "PlaylistsFolder": False,
        "ManualPlaylistsFolder": False,
        "MusicArtist": canPlayList,
        "MusicAlbum": canPlayList,
        "Audio": True,
    }
    return switcher.get(jf_type, False)


async def async_library_items(
    jelly_cm: JellyfinClientManager,
    media_content_type_in=None,
    media_content_id_in=None,
    canPlayList=True,
) -> BrowseMediaSource:
    """Create response payload describing contents of a library or collection."""
    _LOGGER.debug("async_library_items: %s / %s", media_content_type_in, media_content_id_in)

    if media_content_id_in and IDENTIFIER_SPLIT in str(media_content_id_in):
        media_content_type, media_content_id = JellyfinSource.parse_mediasource_identifier(
            media_content_id_in
        )
    else:
        media_content_type = media_content_type_in
        media_content_id = media_content_id_in

    # Root of library
    if media_content_type in (None, "library", "") or not media_content_id:
        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"library{IDENTIFIER_SPLIT}library",
            media_class=MediaClass.DIRECTORY,
            media_content_type="library",
            title="Media Library",
            can_play=False,
            can_expand=True,
            children=[],
        )
        query = {
            "sortBy": "SortName",
            "sortOrder": "Ascending",
        }
    elif media_content_type in [
        MediaClass.DIRECTORY,
        MediaType.ARTIST,
        MediaType.ALBUM,
        MediaType.PLAYLIST,
        MediaType.TVSHOW,
        MediaType.SEASON,
    ]:
        query = {
            "ParentId": media_content_id,
            "sortBy": "SortName",
            "sortOrder": "Ascending",
        }
        parent_item = await jelly_cm.get_item(media_content_id)
        parent_name = (
            parent_item.get("Name", "Library") if isinstance(parent_item, dict) else "Library"
        )
        parent_type = (
            parent_item.get("Type", "Folder") if isinstance(parent_item, dict) else "Folder"
        )

        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{media_content_type}{IDENTIFIER_SPLIT}{media_content_id}",
            media_class=media_content_type
            if isinstance(media_content_type, MediaClass)
            else MediaClass.DIRECTORY,
            media_content_type=media_content_type
            if isinstance(media_content_type, str)
            else "library",
            title=parent_name,
            can_play=IsPlayable(parent_type, canPlayList),
            can_expand=True,
            thumbnail=jelly_cm.get_artwork_url(media_content_id),
            children=[],
        )
    else:
        query = {"Id": media_content_id}
        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{media_content_type}{IDENTIFIER_SPLIT}{media_content_id}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=media_content_type or "library",
            title="",
            can_play=True,
            can_expand=False,
            thumbnail=jelly_cm.get_artwork_url(media_content_id),
            children=[],
        )

    items = await jelly_cm.get_items(query)
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("Id")
        item_type = item.get("Type", "")
        item_name = item.get("Name", "Unknown")
        is_folder = item.get("IsFolder", False)

        m_type = Type2Mediatype(item_type) or MediaType.VIDEO
        m_class = Type2Mediaclass(item_type)

        if media_content_type in (
            None,
            "library",
            "",
            MediaClass.DIRECTORY,
            MediaType.ARTIST,
            MediaType.ALBUM,
            MediaType.PLAYLIST,
            MediaType.TVSHOW,
            MediaType.SEASON,
        ):
            child = BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{m_type}{IDENTIFIER_SPLIT}{item_id}",
                media_class=m_class,
                media_content_type=str(m_type),
                title=item_name,
                can_play=IsPlayable(item_type, canPlayList),
                can_expand=is_folder,
                children=[],
                thumbnail=jelly_cm.get_artwork_url(item_id),
            )
            library_info.children.append(child)
        else:
            library_info.domain = DOMAIN
            library_info.identifier = f"{m_type}{IDENTIFIER_SPLIT}{item_id}"
            library_info.title = item_name
            library_info.media_content_type = str(m_type)
            library_info.media_class = m_class
            library_info.can_expand = is_folder
            # Fix trailing comma bug
            library_info.can_play = IsPlayable(item_type, canPlayList)
            break

    return library_info
