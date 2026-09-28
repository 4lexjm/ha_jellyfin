"""Support for Jellyfin media player entities."""

import logging

import homeassistant.util.dt as dt_util
from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import (
    CONF_URL,
    DEVICE_DEFAULT_NAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo

from . import JellyfinClientManager, JellyfinDevice
from .const import DOMAIN
from .media_source import IDENTIFIER_SPLIT, JellyfinSource, async_library_items

PLATFORM = "media_player"

_LOGGER = logging.getLogger(__name__)

MEDIA_TYPE_TRAILER = MediaType.VIDEO
MEDIA_TYPE_GENERIC_VIDEO = MediaType.VIDEO

SUPPORT_JELLYFIN = (
    MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.PLAY
)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Jellyfin media players dynamically."""
    active_jellyfin_devices: dict = {}
    inactive_jellyfin_devices: dict = {}

    manager: JellyfinClientManager = None
    if hasattr(config_entry, "runtime_data") and config_entry.runtime_data:
        manager = config_entry.runtime_data
    else:
        url_key = config_entry.data.get(CONF_URL)
        manager = hass.data[DOMAIN][url_key]["manager"]

    hass.data[DOMAIN][manager.host][PLATFORM]["entities"] = []

    @callback
    def device_update_callback(data):
        """Handle devices which are added or updated in Jellyfin."""
        new_devices = []
        for dev_id in manager.devices:
            if (
                dev_id not in active_jellyfin_devices
                and dev_id not in inactive_jellyfin_devices
            ):
                new_player = JellyfinMediaPlayer(manager, dev_id)
                active_jellyfin_devices[dev_id] = new_player
                new_devices.append(new_player)
            elif dev_id in inactive_jellyfin_devices:
                dev = manager.devices.get(dev_id)
                if dev and dev.state != "Off":
                    player = inactive_jellyfin_devices.pop(dev_id)
                    active_jellyfin_devices[dev_id] = player
                    player.set_available(True)

        if new_devices:
            _LOGGER.debug("Adding new Jellyfin media player entities: %s", new_devices)
            async_add_entities(new_devices, True)

    @callback
    def device_removal_callback(data):
        """Handle the removal / deactivation of devices from Jellyfin."""
        if data in active_jellyfin_devices:
            player = active_jellyfin_devices.pop(data)
            inactive_jellyfin_devices[data] = player
            player.set_available(False)

    unsub_new = manager.add_new_devices_callback(device_update_callback)
    unsub_stale = manager.add_stale_devices_callback(device_removal_callback)

    if hasattr(config_entry, "async_on_unload"):
        config_entry.async_on_unload(unsub_new)
        config_entry.async_on_unload(unsub_stale)

    manager.update_device_list()


class JellyfinMediaPlayer(MediaPlayerEntity):
    """Representation of a Jellyfin device as a Home Assistant media player."""

    def __init__(self, jelly_cm: JellyfinClientManager, device_id: str):
        """Initialize the Jellyfin media player."""
        _LOGGER.debug("New Jellyfin MediaPlayer initialized with ID: %s", device_id)
        self.jelly_cm = jelly_cm
        self.device_id = device_id

        # Keep initial reference or dummy
        self._fallback_device = self.jelly_cm.devices.get(device_id) or JellyfinDevice(
            {}, jelly_cm
        )
        self._available = True
        self.media_status_last_position = None
        self.media_status_received = None
        self._attr_entity_registry_enabled_default = False
        self._unsub_update = None

    @property
    def device(self) -> JellyfinDevice:
        """Return the JellyfinDevice instance safely."""
        return self.jelly_cm.devices.get(self.device_id, self._fallback_device)

    async def async_added_to_hass(self):
        """Register entity callbacks when added to Home Assistant."""
        server_data = self.hass.data.get(DOMAIN, {}).get(self.jelly_cm.host, {})
        server_data.setdefault(PLATFORM, {}).setdefault("entities", []).append(self)
        self._unsub_update = self.jelly_cm.add_update_callback(
            self.async_update_callback, self.device_id
        )

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed from Home Assistant."""
        server_data = self.hass.data.get(DOMAIN, {}).get(self.jelly_cm.host, {})
        entities = server_data.get(PLATFORM, {}).get("entities", [])
        if self in entities:
            entities.remove(self)

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    @callback
    def async_update_callback(self, msg):
        """Handle device updates from Jellyfin."""
        current_pos = self.device.media_position
        if current_pos is not None:
            if current_pos != self.media_status_last_position:
                self.media_status_last_position = current_pos
                self.media_status_received = dt_util.utcnow()
        elif not self.device.is_nowplaying:
            self.media_status_last_position = None
            self.media_status_received = None

        self.async_write_ha_state()

    async def async_get_browse_image(
        self,
        media_content_type: str,
        media_content_id: str,
        media_image_id: str | None = None,
    ) -> tuple[bytes | None, str | None]:
        """Fetch internally accessible artwork bytes for media browser."""
        if media_content_id:
            return await self.device.get_artwork(media_content_id)
        return None, None

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        """Implement media browser for this player."""
        _LOGGER.debug(
            "async_browse_media: %s / %s", media_content_type, media_content_id
        )
        return await async_library_items(
            self.jelly_cm, media_content_type, media_content_id
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer="Jellyfin",
            name=f"Jellyfin {self.device.name}",
            model=self.device.client or "Jellyfin Client",
            via_device=(DOMAIN, self.jelly_cm.server_url),
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available and self.jelly_cm.is_available and self.device.is_active

    def set_available(self, value: bool):
        """Set available property."""
        self._available = value

    @property
    def unique_id(self) -> str:
        """Return the unique ID of this client."""
        return self.device_id

    @property
    def supports_remote_control(self) -> bool:
        """Return whether remote playback control is supported."""
        return self.device.supports_remote_control

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        if self.supports_remote_control:
            return SUPPORT_JELLYFIN
        return MediaPlayerEntityFeature.BROWSE_MEDIA

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return (
            f"Jellyfin {self.device.name}" if self.device.name else DEVICE_DEFAULT_NAME
        )

    @property
    def should_poll(self) -> bool:
        """WebSocket pushes state changes, no polling required."""
        return False

    @property
    def state(self) -> MediaPlayerState:
        """Return the current play state of the device."""
        if not self.available:
            return MediaPlayerState.OFF

        dev_state = self.device.state
        if dev_state in ("Paused", "Pause"):
            return MediaPlayerState.PAUSED
        if dev_state == "Playing":
            return MediaPlayerState.PLAYING
        if dev_state == "Idle":
            return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def app_name(self) -> str | None:
        """Return current username as app_name."""
        return self.device.username

    @property
    def media_content_id(self) -> str | None:
        """Content ID of current playing media."""
        return self.device.media_id

    @property
    def media_content_type(self) -> MediaType | None:
        """Content type of current playing media."""
        media_type = self.device.media_type
        if media_type == "Episode":
            return MediaType.TVSHOW
        if media_type == "Movie":
            return MediaType.MOVIE
        if media_type == "Trailer":
            return MEDIA_TYPE_TRAILER
        if media_type in ["Music", "Audio"]:
            return MediaType.MUSIC
        if media_type == "Video":
            return MEDIA_TYPE_GENERIC_VIDEO
        if media_type == "TvChannel":
            return MediaType.CHANNEL
        return None

    @property
    def media_duration(self) -> float | None:
        """Return the duration of current playing media in seconds."""
        return self.device.media_runtime

    @property
    def media_position(self) -> float | None:
        """Return the position of current playing media in seconds."""
        return self.media_status_last_position

    @property
    def media_position_updated_at(self):
        """When was the position of current playing media valid."""
        return self.media_status_received

    @property
    def media_image_url(self) -> str | None:
        """Return artwork image URL of current playing media."""
        return self.device.media_image_url

    @property
    def media_title(self) -> str | None:
        """Return the title of current playing media."""
        return self.device.media_title

    @property
    def media_season(self) -> int | None:
        """Season of current playing media (TV Show only)."""
        return self.device.media_season

    @property
    def media_series_title(self) -> str | None:
        """Return the title of the series of current playing media (TV)."""
        return self.device.media_series_title

    @property
    def media_episode(self) -> int | None:
        """Return the episode number of current playing media (TV only)."""
        return self.device.media_episode

    @property
    def media_album_name(self) -> str | None:
        """Return the album name of current playing media (Music only)."""
        return self.device.media_album_name

    @property
    def media_artist(self) -> str | None:
        """Return the artist of current playing media (Music only)."""
        return self.device.media_artist

    async def async_media_play(self):
        """Send play command."""
        await self.device.play()

    async def async_media_pause(self):
        """Send pause command."""
        await self.device.pause()

    async def async_media_stop(self):
        """Send stop command."""
        await self.device.stop()

    async def async_media_next_track(self):
        """Send next track command."""
        await self.device.next_track()

    async def async_media_previous_track(self):
        """Send previous track command."""
        await self.device.previous_track()

    async def async_media_seek(self, position: float):
        """Send seek command."""
        await self.device.seek(position)

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        announce: bool | None = None,
        **kwargs,
    ) -> None:
        """Play a piece of media on this device."""
        if media_source.is_media_source_id(media_id) or IDENTIFIER_SPLIT in media_id:
            _, item_id = JellyfinSource.parse_mediasource_identifier(media_id)
            target_id = item_id or media_id
        else:
            target_id = media_id

        await self.device.play_media(target_id)
