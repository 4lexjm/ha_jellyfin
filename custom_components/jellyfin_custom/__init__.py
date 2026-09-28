"""The jellyfin component."""

import asyncio
import collections.abc
import inspect
import json
import logging
import traceback
import urllib.parse
from collections.abc import Mapping, MutableMapping
from datetime import datetime, timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from aiohttp import ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_ID,
    CONF_CLIENT_ID,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send
from jellyfin_apiclient_python import JellyfinClient

from .const import (
    ATTR_PAGE,
    ATTR_PLAYLIST,
    ATTR_SEARCH_TERM,
    CLIENT_VERSION,
    CONF_GENERATE_UPCOMING,
    CONF_GENERATE_YAMC,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLAYLISTS,
    SERVICE_BROWSE,
    SERVICE_DELETE,
    SERVICE_SCAN,
    SERVICE_SEARCH,
    SERVICE_YAMC_SETPAGE,
    SERVICE_YAMC_SETPLAYLIST,
    SIGNAL_STATE_UPDATED,
    STATE_IDLE,
    STATE_OFF,
    STATE_PAUSED,
    STATE_PLAYING,
    USER_APP_NAME,
    YAMC_PAGE_SIZE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.MEDIA_PLAYER]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=30)

SERVICE_SCHEMA = vol.Schema({})

SCAN_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    }
)
YAMC_SETPAGE_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_PAGE): vol.All(vol.Coerce(int)),
    }
)
YAMC_SETPLAYLIST_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_PLAYLIST): cv.string,
    }
)
DELETE_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ID): cv.string,
    }
)
SEARCH_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_SEARCH_TERM): cv.string,
        vol.Optional(ATTR_ID): cv.string,
    }
)
BROWSE_SERVICE_SCHEMA = SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ID): cv.string,
    }
)

SERVICE_TO_METHOD = {
    SERVICE_SCAN: {"method": "async_trigger_scan", "schema": SCAN_SERVICE_SCHEMA},
    SERVICE_BROWSE: {"method": "async_browse_item", "schema": BROWSE_SERVICE_SCHEMA},
    SERVICE_DELETE: {"method": "async_delete_item", "schema": DELETE_SERVICE_SCHEMA},
    SERVICE_SEARCH: {"method": "async_search_item", "schema": SEARCH_SERVICE_SCHEMA},
    SERVICE_YAMC_SETPAGE: {
        "method": "async_yamc_setpage",
        "schema": YAMC_SETPAGE_SERVICE_SCHEMA,
    },
    SERVICE_YAMC_SETPLAYLIST: {
        "method": "async_yamc_setplaylist",
        "schema": YAMC_SETPLAYLIST_SERVICE_SCHEMA,
    },
}


def autolog(message: str) -> None:
    """Automatically log the current function details when debug is enabled."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return
    func = inspect.currentframe().f_back.f_code
    _LOGGER.debug(
        "%s: %s in %s:%i",
        message,
        func.co_name,
        func.co_filename,
        func.co_firstlineno,
    )


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Jellyfin integration."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up Jellyfin from a config entry."""
    autolog("<<<")

    if not config_entry.unique_id:
        hass.config_entries.async_update_entry(config_entry, unique_id=config_entry.title)

    # Merge data and options without wiping options
    config = {**config_entry.data, **config_entry.options}

    config_entry.async_on_unload(config_entry.add_update_listener(_update_listener))

    url_key = config.get(CONF_URL)
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    hass.data[DOMAIN][url_key] = {}

    _jelly = JellyfinClientManager(hass, config, config_entry)
    try:
        await _jelly.connect()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        _LOGGER.error("Cannot connect to Jellyfin server: %s", err)
        raise ConfigEntryNotReady(f"Cannot connect to Jellyfin server: {err}") from err

    # Store manager in both runtime_data (modern HA) and hass.data (backwards compatibility)
    try:
        config_entry.runtime_data = _jelly
    except AttributeError:
        pass
    hass.data[DOMAIN][url_key]["manager"] = _jelly

    async def async_service_handler(service):
        """Map services to methods."""
        method = SERVICE_TO_METHOD.get(service.service)
        if not method:
            return

        params = {key: value for key, value in service.data.items() if key != ATTR_ENTITY_ID}

        # Normalize search_term vs id for search service
        if (
            service.service == SERVICE_SEARCH
            and ATTR_ID in params
            and ATTR_SEARCH_TERM not in params
        ):
            params[ATTR_SEARCH_TERM] = params.pop(ATTR_ID)

        entity_id = service.data.get(ATTR_ENTITY_ID)

        server_data = hass.data.get(DOMAIN, {}).get(url_key, {})
        sensor_entities = server_data.get("sensor", {}).get("entities", [])
        for sensor in list(sensor_entities):
            if getattr(sensor, "entity_id", None) == entity_id:
                func = getattr(sensor, method["method"], None)
                if func:
                    await func(**params)

        player_entities = server_data.get("media_player", {}).get("entities", [])
        for media_player in list(player_entities):
            if getattr(media_player, "entity_id", None) == entity_id:
                func = getattr(media_player, method["method"], None)
                if func:
                    await func(**params)

    for my_service, srv_info in SERVICE_TO_METHOD.items():
        schema = srv_info.get("schema", SERVICE_SCHEMA)
        if not hass.services.has_service(DOMAIN, my_service):
            hass.services.async_register(DOMAIN, my_service, async_service_handler, schema=schema)

    await _jelly.start()

    for platform in PLATFORMS:
        plat_str = platform.value if hasattr(platform, "value") else str(platform)
        hass.data[DOMAIN][url_key][plat_str] = {}
        hass.data[DOMAIN][url_key][plat_str]["entities"] = []

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)

    async def stop_jellyfin(event):
        """Stop Jellyfin connection on HA shutdown."""
        await _jelly.stop()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_jellyfin)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a Jellyfin config entry."""
    _LOGGER.info("Unloading jellyfin entry: %s", config_entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    url_key = config_entry.data.get(CONF_URL)
    manager = None
    if hasattr(config_entry, "runtime_data") and config_entry.runtime_data:
        manager = config_entry.runtime_data
    elif url_key and url_key in hass.data.get(DOMAIN, {}):
        manager = hass.data[DOMAIN][url_key].get("manager")

    if manager:
        await manager.stop()

    if url_key and url_key in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(url_key, None)

    # If no more entries configured, unregister domain services
    remaining_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != config_entry.entry_id
    ]
    if not remaining_entries:
        for service in SERVICE_TO_METHOD:
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def _update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Update listener triggered when config options change."""
    _LOGGER.debug("Reload triggered by options update for %s", config_entry.entry_id)
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    entreg = entity_registry.async_get(hass)
    if entity_registry.async_entries_for_device(entreg, device_entry.id):
        return False
    return True


class JellyfinDevice:
    """Represents properties of a Jellyfin client device."""

    def __init__(self, session, jf_manager):
        """Initialize Jellyfin device object."""
        self.jf_manager = jf_manager
        self.is_active = True
        self.session = session or {}

    def update_session(self, session):
        """Update session object."""
        self.session = session or {}

    def set_active(self, active: bool):
        """Mark device as active/inactive."""
        self.is_active = active

    @property
    def session_raw(self):
        """Return raw session data."""
        return self.session

    @property
    def session_id(self):
        """Return current session Id."""
        return self.session.get("Id")

    @property
    def unique_id(self):
        """Return device id."""
        return self.session.get("DeviceId")

    @property
    def name(self):
        """Return device name."""
        return self.session.get("DeviceName") or self.session.get("Client") or "Jellyfin Client"

    @property
    def client(self):
        """Return client name."""
        return self.session.get("Client")

    @property
    def username(self):
        """Return username logged into device."""
        return self.session.get("UserName")

    @property
    def media_title(self):
        """Return title currently playing."""
        return self.session.get("NowPlayingItem", {}).get("Name")

    @property
    def media_season(self):
        """Season of current playing media (TV Show only)."""
        return self.session.get("NowPlayingItem", {}).get("ParentIndexNumber")

    @property
    def media_series_title(self):
        """The title of the series of current playing media (TV Show only)."""
        return self.session.get("NowPlayingItem", {}).get("SeriesName")

    @property
    def media_episode(self):
        """Episode of current playing media (TV Show only)."""
        return self.session.get("NowPlayingItem", {}).get("IndexNumber")

    @property
    def media_album_name(self):
        """Album name of current playing media (Music track only)."""
        return self.session.get("NowPlayingItem", {}).get("Album")

    @property
    def media_artist(self):
        """Artist of current playing media (Music track only)."""
        now_playing = self.session.get("NowPlayingItem") or {}
        artists = now_playing.get("Artists")
        if isinstance(artists, list) and artists:
            return artists[0] if len(artists) == 1 else ", ".join(str(a) for a in artists)
        return artists

    @property
    def media_album_artist(self):
        """Album artist of current playing media (Music track only)."""
        return self.session.get("NowPlayingItem", {}).get("AlbumArtist")

    @property
    def media_id(self):
        """Return item id currently playing."""
        return self.session.get("NowPlayingItem", {}).get("Id")

    @property
    def media_type(self):
        """Return type currently playing."""
        return self.session.get("NowPlayingItem", {}).get("Type")

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        if not self.is_nowplaying or not self.media_id:
            return None
        now_playing = self.session.get("NowPlayingItem") or {}
        image_tags = now_playing.get("ImageTags") or {}
        if "Thumb" in image_tags:
            return self.jf_manager.get_artwork_url(self.media_id, "Thumb")
        if "Primary" in image_tags:
            return self.jf_manager.get_artwork_url(self.media_id, "Primary")
        return None

    @property
    def media_position(self):
        """Return position currently playing in seconds."""
        try:
            ticks = self.session.get("PlayState", {}).get("PositionTicks")
            return int(ticks) / 10000000 if ticks is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def media_runtime(self):
        """Return total runtime length in seconds."""
        try:
            ticks = self.session.get("NowPlayingItem", {}).get("RunTimeTicks")
            return int(ticks) / 10000000 if ticks is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def media_percent_played(self):
        """Return media percent played."""
        try:
            pos = self.media_position
            runtime = self.media_runtime
            if pos is not None and runtime and runtime > 0:
                return (pos / runtime) * 100
            return None
        except (TypeError, ZeroDivisionError):
            return None

    @property
    def state(self):
        """Return current playstate of the device."""
        if not self.is_active:
            return STATE_OFF
        if "NowPlayingItem" in self.session:
            play_state = self.session.get("PlayState") or {}
            if play_state.get("IsPaused"):
                return STATE_PAUSED
            return STATE_PLAYING
        return STATE_IDLE

    @property
    def is_nowplaying(self):
        """Return true if an item is currently playing or paused."""
        return self.state in (STATE_PLAYING, STATE_PAUSED)

    @property
    def supports_remote_control(self):
        """Return remote control status."""
        return self.session.get("SupportsRemoteControl", False)

    async def get_item(self, id):
        return await self.jf_manager.get_item(id)

    async def get_items(self, query=None):
        return await self.jf_manager.get_items(query)

    async def get_artwork(self, media_id, type="Primary") -> tuple[bytes | None, str | None]:
        return await self.jf_manager.get_artwork(media_id, type)

    def get_artwork_url(self, media_id, type="Primary") -> str:
        return self.jf_manager.get_artwork_url(media_id, type)

    async def set_playstate(self, state, pos=0):
        """Send media commands to server."""
        params = {}
        if state == "Seek":
            params["SeekPositionTicks"] = int(pos * 10000000)
            params["static"] = "true"

        await self.jf_manager.set_playstate(self.session_id, state, params)

    async def play(self):
        """Send unpause/play command to device."""
        return await self.set_playstate("Unpause")

    async def pause(self):
        """Send pause command to device."""
        return await self.set_playstate("Pause")

    async def stop(self):
        """Send stop command to device."""
        return await self.set_playstate("Stop")

    async def next_track(self):
        """Send next track command to device."""
        return await self.set_playstate("NextTrack")

    async def previous_track(self):
        """Send previous track command to device."""
        return await self.set_playstate("PreviousTrack")

    async def seek(self, position):
        """Send seek command to device."""
        return await self.set_playstate("Seek", position)

    # Backward compatibility aliases
    media_play = play
    media_pause = pause
    media_stop = stop
    media_next = next_track
    media_previous = previous_track
    media_seek = seek

    async def play_media(self, media_id):
        await self.jf_manager.play_media(self.session_id, media_id)

    async def browse_item(self, media_id):
        await self.jf_manager.view_media(self.session_id, media_id)


class JellyfinClientManager:
    """Manages the connection, data synchronization, and WebSocket with Jellyfin."""

    def __init__(self, hass: HomeAssistant, config: dict, config_entry: ConfigEntry = None):
        self.hass = hass
        self.callback = lambda client, event_name, data: None
        self.jf_client: JellyfinClient = None
        self.is_stopping = True
        self._is_available = False
        self._event_loop = hass.loop

        self.host = config.get(CONF_URL)
        self._info = None
        self._data = None
        self._yamc = None
        self._yamc_cur_page = 1
        self._last_playlist = ""
        self._last_search = ""

        self.config = config
        self.config_entry = config
        self.raw_config_entry = config_entry
        self.server_url = ""

        self._sessions = []
        self._devices: MutableMapping[str, JellyfinDevice] = {}

        # Callbacks
        self._new_devices_callbacks = []
        self._stale_devices_callbacks = []
        self._update_callbacks = []
        self._reconnect_task = None

    @property
    def is_available(self) -> bool:
        return not self.is_stopping and self._is_available

    @is_available.setter
    def is_available(self, value: bool) -> None:
        self._is_available = value

    @staticmethod
    def expo(max_value=None):
        n = 0
        while True:
            a = 2**n
            if max_value is None or a < max_value:
                yield a
                n += 1
            else:
                yield max_value

    @staticmethod
    def clean_none_dict_values(obj):
        """Recursively remove keys with a value of None."""
        if not isinstance(obj, collections.abc.Iterable) or isinstance(obj, str):
            return obj

        if isinstance(obj, collections.abc.Mapping):
            return {
                k: JellyfinClientManager.clean_none_dict_values(v)
                for k, v in obj.items()
                if v is not None
            }
        elif isinstance(obj, list):
            return [
                JellyfinClientManager.clean_none_dict_values(item)
                for item in obj
                if item is not None
            ]
        return obj

    @staticmethod
    def normalize_url(raw_url: str) -> str:
        """Normalize URL ensuring scheme and default port if needed."""
        url = raw_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"

        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc
        path = parsed.path.rstrip("/")

        # Add port 8096 for plain http if no port is specified and no reverse proxy implied
        if scheme == "http" and ":" not in netloc:
            netloc = f"{netloc}:8096"

        return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))

    @staticmethod
    def client_factory(config):
        """Create and configure a JellyfinClient instance."""
        client = JellyfinClient(allow_multiple_clients=True)
        client.config.data["app.default"] = True
        client.config.app(
            USER_APP_NAME,
            CLIENT_VERSION,
            USER_APP_NAME,
            config.get(CONF_CLIENT_ID, "home-assistant-client"),
        )
        client.config.data["auth.ssl"] = config.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        return client

    def login(self) -> tuple[bool, str]:
        """Authenticate synchronously with the Jellyfin server."""
        autolog(">>>")
        try:
            self.server_url = self.normalize_url(self.config[CONF_URL])
            self.jf_client = self.client_factory(self.config)

            status = self.jf_client.auth.connect_to_address(self.server_url)
            if not status or status.get("State") == 0:
                _LOGGER.warning("Jellyfin server at %s is unavailable", self.server_url)
                return False, "unavailable"

            result = self.jf_client.auth.login(
                self.server_url,
                self.config[CONF_USERNAME],
                self.config.get(CONF_PASSWORD, ""),
            )
            if not result or "AccessToken" not in result:
                _LOGGER.warning(
                    "Jellyfin authentication failed for user %s",
                    self.config[CONF_USERNAME],
                )
                return False, "invalid_auth"

            credentials = self.jf_client.auth.credentials.get_credentials()
            self.jf_client.authenticate(credentials)
            return True, "ok"
        except Exception as err:
            _LOGGER.error("Error during Jellyfin login: %s", err)
            return False, str(err)

    async def connect(self):
        """Connect and authenticate asynchronously."""
        autolog(">>>")
        success, reason = await self.hass.async_add_executor_job(self.login)
        if success:
            _LOGGER.info("Successfully connected to Jellyfin server: %s", self.server_url)
            self.is_available = True
        elif reason == "invalid_auth":
            raise ConfigEntryAuthFailed("Invalid username or password for Jellyfin server.")
        else:
            raise ConfigEntryNotReady(f"Cannot connect to Jellyfin server: {reason}")

    async def start(self):
        """Start client background listeners and fetch initial data."""
        autolog(">>>")
        self.is_stopping = False

        def event(event_name, data):
            _LOGGER.debug("Jellyfin Event: %s", event_name)
            if event_name == "WebSocketConnect":
                self.is_available = True
                try:
                    self.jf_client.wsc.send("SessionsStart", "0,1500")
                except Exception as err:
                    _LOGGER.warning("Could not send SessionsStart on WebSocket connect: %s", err)
            elif event_name == "WebSocketDisconnect":
                self.is_available = False
                self._event_loop.call_soon_threadsafe(self.mark_devices_offline)
                if not self.is_stopping:
                    self._event_loop.call_soon_threadsafe(self._schedule_reconnect)
            elif event_name in ("LibraryChanged", "UserDataChanged"):
                self._event_loop.call_soon_threadsafe(self._trigger_sensor_updates)
            elif event_name == "Sessions":
                try:
                    cleaned = self.clean_none_dict_values(data)
                    self._sessions = (
                        cleaned.get("value", []) if isinstance(cleaned, dict) else (cleaned or [])
                    )
                    self.update_device_list()
                except Exception as err:
                    _LOGGER.error("Error handling Sessions event: %s", err)
            else:
                self.callback(self.jf_client, event_name, data)

        self.jf_client.callback = event
        self.jf_client.callback_ws = event

        await self.hass.async_add_executor_job(self.jf_client.start, True)

        try:
            self._info = await self.hass.async_add_executor_job(
                self.jf_client.jellyfin._get, "System/Info"
            )
            raw_sessions = await self.hass.async_add_executor_job(
                self.jf_client.jellyfin.get_sessions
            )
            cleaned_sessions = self.clean_none_dict_values(raw_sessions)
            self._sessions = cleaned_sessions if isinstance(cleaned_sessions, list) else []
            await self.update_data()
        except Exception as err:
            _LOGGER.warning("Error fetching initial server info or sessions: %s", err)

    def _trigger_sensor_updates(self):
        """Trigger update on sensors thread-safely."""
        autolog("LibraryChanged: trigger sensor update")
        server_data = self.hass.data.get(DOMAIN, {}).get(self.host, {})
        sensor_entities = server_data.get("sensor", {}).get("entities", [])
        for sensor in list(sensor_entities):
            if hasattr(sensor, "async_schedule_update_ha_state"):
                sensor.async_schedule_update_ha_state(force_refresh=True)

    def _schedule_reconnect(self):
        """Schedule reconnection coroutine."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_task(self._async_reconnect())

    async def _async_reconnect(self):
        """Asynchronously reconnect to Jellyfin with exponential backoff without blocking."""
        timeout_gen = self.expo(100)
        while not self.is_stopping and not self.is_available:
            timeout = next(timeout_gen)
            _LOGGER.warning("Connection to Jellyfin lost. Retrying in %d seconds...", timeout)
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                break
            if self.is_stopping:
                break

            try:
                await self.hass.async_add_executor_job(self.jf_client.stop)
            except Exception:
                pass

            success, _ = await self.hass.async_add_executor_job(self.login)
            if success:
                _LOGGER.info("Reconnection to Jellyfin server succeeded.")
                self.is_available = True
                await self.hass.async_add_executor_job(self.jf_client.start, True)
                try:
                    self._info = await self.hass.async_add_executor_job(
                        self.jf_client.jellyfin._get, "System/Info"
                    )
                    raw_sessions = await self.hass.async_add_executor_job(
                        self.jf_client.jellyfin.get_sessions
                    )
                    self._sessions = self.clean_none_dict_values(raw_sessions) or []
                    await self.update_data()
                    self.update_device_list()
                except Exception as err:
                    _LOGGER.warning("Error refreshing state after reconnect: %s", err)
                break

    def mark_devices_offline(self):
        """Mark devices as offline upon disconnection."""
        for dev_id, dev in self._devices.items():
            if dev.is_active:
                dev.set_active(False)
                self._do_update_callback(dev_id)
                self._do_stale_devices_callback(dev_id)

    async def stop(self):
        """Stop client and background tasks."""
        autolog("<<<")
        self.is_stopping = True
        self.is_available = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        if self.jf_client:
            try:
                await self.hass.async_add_executor_job(self.jf_client.stop)
            except Exception as err:
                _LOGGER.debug("Error while stopping Jellyfin client: %s", err)

    @staticmethod
    def _parse_and_format_date(date_str: str | None, fmt: str = "%d/%m/%Y") -> str | None:
        """Parse ISO date and format safely without external dependencies."""
        if not date_str:
            return None
        try:
            clean = date_str.replace("Z", "+00:00")
            dt_obj = datetime.fromisoformat(clean)
            return dt_obj.strftime(fmt)
        except Exception:
            return None

    async def update_data(self):
        """Update upcoming and YAMC data."""
        autolog("<<<")
        if self.config.get(CONF_GENERATE_UPCOMING):
            try:
                self._data = await self.hass.async_add_executor_job(
                    self.jf_client.jellyfin.shows,
                    "/NextUp",
                    {
                        "Limit": YAMC_PAGE_SIZE,
                        "UserId": "{UserId}",
                        "fields": "DateCreated,Studios,Genres",
                        "excludeItemTypes": "Folder",
                    },
                )
            except Exception as err:
                _LOGGER.warning("Error updating upcoming data: %s", err)

        if self.config.get(CONF_GENERATE_YAMC):
            query = {
                "startIndex": (self._yamc_cur_page - 1) * YAMC_PAGE_SIZE,
                "limit": YAMC_PAGE_SIZE,
                "userId": "{UserId}",
                "recursive": "true",
                "fields": "DateCreated,Studios,Genres,Taglines,ProviderIds,Ratings,MediaStreams",
                "collapseBoxSetItems": "false",
                "excludeItemTypes": "Folder",
            }

            if not self._last_playlist:
                self._last_playlist = "latest_movies"

            if self._last_search:
                query["searchTerm"] = self._last_search
            elif self._last_playlist:
                for pl in PLAYLISTS:
                    if pl["name"] == self._last_playlist:
                        query.update(pl["query"])

            try:
                if self._last_playlist == "nextup":
                    self._yamc = await self.hass.async_add_executor_job(
                        self.jf_client.jellyfin.shows, "/NextUp", query
                    )
                else:
                    self._yamc = await self.hass.async_add_executor_job(
                        self.jf_client.jellyfin.items, "", "GET", query
                    )
            except Exception as err:
                _LOGGER.error("Cannot update YAMC data: %s", err)
                return

            if self._yamc is None or "Items" not in self._yamc:
                _LOGGER.error("Cannot update YAMC data (empty response)")
                return

            for item in self._yamc.get("Items", []):
                try:
                    stream_info = await self.get_stream_url(item["Id"], item.get("Type"))
                    item["stream_url"] = stream_info[0]
                    item["info"] = stream_info[2]
                except Exception as err:
                    _LOGGER.debug(
                        "Could not resolve stream url for item %s: %s",
                        item.get("Id"),
                        err,
                    )

    def update_device_list(self):
        """Update active/inactive devices from sessions."""
        autolog(">>>")
        if self._sessions is None:
            _LOGGER.error("Error updating Jellyfin devices: sessions is None")
            return

        try:
            new_devices = []
            active_devices = []
            client_id = self.config.get(CONF_CLIENT_ID)

            for device in self._sessions:
                if not isinstance(device, dict):
                    continue
                dev_id = device.get("DeviceId")
                client_name = device.get("Client", "Client")
                if not dev_id:
                    continue

                dev_name = f"{dev_id}.{client_name}"
                active_devices.append(dev_name)

                if dev_id == client_id:
                    continue

                if dev_name not in self._devices:
                    _LOGGER.debug("New Jellyfin Device: %s. Adding to device list.", dev_name)
                    new = JellyfinDevice(device, self)
                    self._devices[dev_name] = new
                    new_devices.append(new)
                else:
                    existing = self._devices[dev_name]
                    dev_update = not existing.is_active
                    do_update = self.update_check(existing, device)

                    existing.update_session(device)
                    existing.set_active(True)

                    if dev_update:
                        self._do_new_devices_callback(0)
                    if do_update:
                        self._do_update_callback(dev_name)

            for dev_id, device_obj in list(self._devices.items()):
                if dev_id not in active_devices:
                    if device_obj.is_active:
                        device_obj.set_active(False)
                        self._do_update_callback(dev_id)
                        self._do_stale_devices_callback(dev_id)

            if new_devices:
                self._do_new_devices_callback(0)
        except Exception:
            _LOGGER.critical("Exception in update_device_list: %s", traceback.format_exc())

    def update_check(self, existing: JellyfinDevice, new: dict) -> bool:
        """Check device state transition to decide if update callback is needed."""
        autolog(">>>")
        old_state = existing.state
        old_theme = existing.session_raw.get("NowPlayingItem", {}).get("IsThemeMedia", False)

        now_playing = new.get("NowPlayingItem")
        if now_playing:
            play_state = new.get("PlayState", {})
            new_state = STATE_PAUSED if play_state.get("IsPaused") else STATE_PLAYING
            new_theme = now_playing.get("IsThemeMedia", False)
        else:
            new_state = STATE_IDLE
            new_theme = False

        if old_theme or new_theme:
            return False
        if old_state == STATE_PLAYING or new_state == STATE_PLAYING:
            return True
        if old_state != new_state:
            return True
        return False

    @property
    def info(self):
        """Return server info dictionary."""
        if self.is_stopping:
            return None
        return self._info

    @property
    def data(self):
        """Upcoming card data."""
        if not self.config.get(CONF_GENERATE_UPCOMING) or self.is_stopping:
            return None

        data = [
            {
                "title_default": "$title",
                "line1_default": "$episode",
                "line2_default": "$release",
                "line3_default": "$rating - $runtime",
                "line4_default": "$number - $studio",
                "icon": "mdi:arrow-down-bold-circle",
            }
        ]

        if not self._data or "Items" not in self._data:
            return data

        for item in self._data.get("Items", []):
            try:
                studios = item.get("Studios") or []
                genres = item.get("Genres") or []
                runtime_ticks = item.get("RunTimeTicks")
                runtime = int(runtime_ticks / 10000000 / 60) if runtime_ticks else None

                data.append(
                    {
                        "title": item.get("SeriesName") or item.get("Name", ""),
                        "episode": item.get("Name", ""),
                        "flag": False,
                        "airdate": item.get("DateCreated"),
                        "number": f"S{item.get('ParentIndexNumber', 0)}E{item.get('IndexNumber', 0)}",
                        "runtime": runtime,
                        "studio": ",".join(
                            o.get("Name", "") for o in studios if isinstance(o, dict)
                        ),
                        "release": self._parse_and_format_date(item.get("PremiereDate")),
                        "poster": self.get_artwork_url(item.get("Id")),
                        "fanart": self.get_artwork_url(item.get("Id"), "Backdrop"),
                        "genres": ",".join(genres),
                        "rating": None,
                        "stream_url": None,
                        "info_url": None,
                    }
                )
            except Exception as err:
                _LOGGER.debug("Error processing upcoming item: %s", err)

        return data

    @property
    def yamc(self):
        """YAMC card data."""
        if not self.config.get(CONF_GENERATE_YAMC) or self.is_stopping:
            return None

        data = [
            {
                "title_default": "$title",
                "line1_default": "$tagline",
                "line2_default": "$empty",
                "line3_default": "$release - $genres",
                "line4_default": "$runtime - $rating - $info",
                "line5_default": "$date",
                "text_link_default": "$info_url",
                "link_default": "$stream_url",
            }
        ]

        if not self._yamc or "Items" not in self._yamc:
            return data

        for item in self._yamc.get("Items", []):
            try:
                provid = None
                user_data = item.get("UserData") or {}
                progress = 0
                if "PlayedPercentage" in user_data:
                    progress = user_data["PlayedPercentage"]
                elif user_data.get("Played"):
                    progress = 100

                rating = None
                if "CommunityRating" in item and item["CommunityRating"] is not None:
                    rating = f"\N{BLACK STAR} {round(item['CommunityRating'], 1)}"
                elif "CriticRating" in item and item["CriticRating"] is not None:
                    rating = f"\N{BLACK STAR} {round(item['CriticRating'] / 10, 1)}"

                studios = item.get("Studios") or []
                genres = item.get("Genres") or []
                taglines = item.get("Taglines") or []
                provider_ids = item.get("ProviderIds") or {}
                runtime_ticks = item.get("RunTimeTicks")
                runtime = int(runtime_ticks / 10000000 / 60) if runtime_ticks else None

                item_type = item.get("Type")
                if item_type == "Movie":
                    provid = provider_ids.get("Imdb")
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("Name"),
                            "tagline": taglines[0] if taglines else "",
                            "flag": user_data.get("Played", False),
                            "airdate": item.get("DateCreated"),
                            "runtime": runtime,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("PremiereDate"), "%Y"),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Backdrop"),
                            "genres": ",".join(genres),
                            "progress": progress,
                            "rating": rating,
                            "info": item.get("info"),
                            "stream_url": item.get("stream_url"),
                            "info_url": f"https://trakt.tv/search/imdb/{provid}?id_type=movie"
                            if provid
                            else "",
                        }
                    )
                elif item_type == "Series":
                    provid = provider_ids.get("Imdb")
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("SeriesName") or item.get("Name"),
                            "episode": item.get("Name"),
                            "tagline": item.get("Name"),
                            "flag": user_data.get("Played", False),
                            "airdate": item.get("DateCreated"),
                            "number": f"S{item.get('ParentIndexNumber', 0)}E{item.get('IndexNumber', 0)}",
                            "runtime": runtime,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("PremiereDate")),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Backdrop"),
                            "genres": ",".join(genres),
                            "progress": progress,
                            "rating": rating,
                            "stream_url": item.get("stream_url"),
                            "info_url": f"https://trakt.tv/search/imdb/{provid}?id_type=series"
                            if provid
                            else "",
                        }
                    )
                elif item_type == "Episode":
                    provid = provider_ids.get("Imdb")
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("SeriesName") or item.get("Name"),
                            "episode": item.get("Name"),
                            "tagline": item.get("Name"),
                            "flag": user_data.get("Played", False),
                            "airdate": item.get("DateCreated"),
                            "number": f"S{item.get('ParentIndexNumber', 0)}E{item.get('IndexNumber', 0)}",
                            "runtime": runtime,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("PremiereDate")),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Primary"),
                            "genres": ",".join(genres),
                            "progress": progress,
                            "rating": rating,
                            "info": item.get("info"),
                            "stream_url": item.get("stream_url"),
                            "info_url": f"https://trakt.tv/search/imdb/{provid}?id_type=episode"
                            if provid
                            else "",
                        }
                    )
                elif item_type == "MusicAlbum":
                    provid = provider_ids.get("MusicBrainzAlbum")
                    artists = item.get("Artists") or []
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("Name"),
                            "tagline": ",".join(artists) if artists else None,
                            "flag": False,
                            "airdate": item.get("DateCreated"),
                            "runtime": runtime,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("PremiereDate"), "%Y"),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Primary"),
                            "genres": ",".join(genres),
                            "progress": 0,
                            "rating": rating,
                            "stream_url": item.get("stream_url"),
                            "info_url": f"https://musicbrainz.org/album/{provid}" if provid else "",
                        }
                    )
                elif item_type == "MusicArtist":
                    provid = provider_ids.get("MusicBrainzArtist")
                    artists = item.get("Artists") or []
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("Name"),
                            "tagline": ",".join(artists) if artists else None,
                            "flag": False,
                            "airdate": item.get("DateCreated"),
                            "runtime": None,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("DateCreated"), "%Y"),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Primary"),
                            "genres": ",".join(genres),
                            "progress": 0,
                            "rating": rating,
                            "stream_url": item.get("stream_url"),
                            "info_url": f"https://musicbrainz.org/artist/{provid}"
                            if provid
                            else "",
                        }
                    )
                else:
                    data.append(
                        {
                            "id": item.get("Id"),
                            "type": item_type,
                            "title": item.get("SeriesName") or item.get("Name"),
                            "episode": item.get("Name"),
                            "tagline": item.get("Name"),
                            "flag": False,
                            "airdate": item.get("DateCreated"),
                            "runtime": runtime,
                            "studio": ",".join(
                                o.get("Name", "") for o in studios if isinstance(o, dict)
                            ),
                            "release": self._parse_and_format_date(item.get("PremiereDate")),
                            "poster": self.get_artwork_url(item.get("Id")),
                            "fanart": self.get_artwork_url(item.get("Id"), "Primary"),
                            "genres": ",".join(genres),
                            "progress": 0,
                            "rating": rating,
                            "info": item.get("info"),
                            "stream_url": item.get("stream_url"),
                            "info_url": None,
                        }
                    )
            except Exception as err:
                _LOGGER.debug("Error processing YAMC item: %s", err)

        attrs = {
            "last_search": self._last_search,
            "last_playlist": self._last_playlist,
            "playlists": json.dumps(PLAYLISTS),
            "total_items": min(50, self._yamc.get("TotalRecordCount", 0)),
            "page": self._yamc_cur_page,
            "page_size": YAMC_PAGE_SIZE,
            "data": json.dumps(data),
        }
        return attrs

    async def trigger_scan(self):
        """Trigger library refresh on Jellyfin."""
        await self.hass.async_add_executor_job(self.jf_client.jellyfin._post, "Library/Refresh")

    async def delete_item(self, id):
        """Delete an item from Jellyfin."""
        await self.hass.async_add_executor_job(self.jf_client.jellyfin.items, f"/{id}", "DELETE")
        await self.update_data()

    async def search_item(self, search_term):
        """Search items on Jellyfin."""
        self._yamc_cur_page = 1
        self._last_search = search_term
        await self.update_data()

    async def yamc_set_page(self, page):
        """Set page for YAMC navigation."""
        self._yamc_cur_page = page
        await self.update_data()

    async def yamc_set_playlist(self, playlist):
        """Set active playlist for YAMC."""
        self._last_search = ""
        self._last_playlist = playlist
        await self.update_data()

    def get_server_url(self) -> str:
        """Return Jellyfin server base URL."""
        return self.jf_client.config.data.get("auth.server", self.server_url)

    def get_auth_token(self) -> str:
        """Return active access token."""
        return self.jf_client.config.data.get("auth.token", "")

    async def get_item(self, id):
        return await self.hass.async_add_executor_job(self.jf_client.jellyfin.get_item, id)

    async def get_items(self, query=None):
        response = await self.hass.async_add_executor_job(
            self.jf_client.jellyfin.users, "/Items", "GET", query
        )
        if isinstance(response, dict) and "Items" in response:
            return response["Items"]
        return response or []

    async def set_playstate(self, session_id, state, params):
        await self.hass.async_add_executor_job(
            self.jf_client.jellyfin.post_session, session_id, f"Playing/{state}", params
        )

    async def play_media(self, session_id, media_id):
        params = {"playCommand": "PlayNow", "itemIds": media_id}
        await self.hass.async_add_executor_job(
            self.jf_client.jellyfin.post_session, session_id, "Playing", params
        )

    async def view_media(self, session_id, media_id):
        item = await self.hass.async_add_executor_job(self.jf_client.jellyfin.get_item, media_id)
        params = {
            "itemId": media_id,
            "itemType": item.get("Type"),
            "itemName": item.get("Name"),
        }
        await self.hass.async_add_executor_job(
            self.jf_client.jellyfin.post_session, session_id, "Viewing", params
        )

    async def get_artwork(self, media_id, type="Primary") -> tuple[bytes | None, str | None]:
        """Retrieve artwork binary image content and its MIME content type asynchronously."""
        url = self.get_artwork_url(media_id, type)
        if not url:
            return None, None

        session = async_get_clientsession(
            self.hass,
            verify_ssl=self.config.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        )
        try:
            timeout = ClientTimeout(total=10)
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.read()
                    content_type = response.headers.get("Content-Type", "image/jpeg")
                    return data, content_type
        except Exception as err:
            _LOGGER.debug("Error fetching artwork from %s: %s", url, err)
        return None, None

    def get_artwork_url(self, media_id, type="Primary") -> str:
        """Return artwork image URL."""
        if not media_id or not self.jf_client:
            return ""
        return self.jf_client.jellyfin.artwork(media_id, type, 500)

    async def get_play_info(self, media_id, profile):
        return await self.hass.async_add_executor_job(
            self.jf_client.jellyfin.get_play_info, media_id, profile
        )

    async def get_stream_url(
        self, media_id, media_content_type
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve playable stream URL, container MIME type and stream info for media item."""
        profile = {
            "Name": USER_APP_NAME,
            "MaxStreamingBitrate": 25000 * 1000,
            "MusicStreamingTranscodingBitrate": 1920000,
            "TimelineOffsetSeconds": 5,
            "TranscodingProfiles": [
                {
                    "Type": "Audio",
                    "Container": "mp3",
                    "Protocol": "http",
                    "AudioCodec": "mp3",
                    "MaxAudioChannels": "2",
                },
                {
                    "Type": "Video",
                    "Container": "mp4",
                    "Protocol": "http",
                    "AudioCodec": "aac,mp3,opus,flac,vorbis",
                    "VideoCodec": "h264,mpeg4,mpeg2video",
                    "MaxAudioChannels": "6",
                },
                {"Container": "jpeg", "Type": "Photo"},
            ],
            "DirectPlayProfiles": [
                {"Type": "Audio", "Container": "mp3", "AudioCodec": "mp3"},
                {"Type": "Audio", "Container": "m4a,m4b", "AudioCodec": "aac"},
                {
                    "Type": "Video",
                    "Container": "mp4,m4v",
                    "AudioCodec": "aac,mp3,opus,flac,vorbis",
                    "VideoCodec": "h264,mpeg4,mpeg2video",
                    "MaxAudioChannels": "6",
                },
            ],
            "ResponseProfiles": [],
            "ContainerProfiles": [],
            "CodecProfiles": [],
            "SubtitleProfiles": [
                {"Format": "srt", "Method": "External"},
                {"Format": "srt", "Method": "Embed"},
                {"Format": "ass", "Method": "External"},
                {"Format": "ass", "Method": "Embed"},
                {"Format": "sub", "Method": "Embed"},
                {"Format": "sub", "Method": "External"},
                {"Format": "ssa", "Method": "Embed"},
                {"Format": "ssa", "Method": "External"},
                {"Format": "smi", "Method": "Embed"},
                {"Format": "smi", "Method": "External"},
                {"Format": "pgssub", "Method": "Embed"},
                {"Format": "dvdsub", "Method": "Embed"},
                {"Format": "pgs", "Method": "Embed"},
            ],
        }

        playback_info = await self.get_play_info(media_id, profile)
        if playback_info is None or "MediaSources" not in playback_info:
            _LOGGER.error("No playback info for item id %s", media_id)
            return None, None, None

        selected = None
        weight_selected = 0
        for media_source in playback_info["MediaSources"]:
            weight = (media_source.get("SupportsDirectStream") or 0) * 50000 + (
                media_source.get("Bitrate") or 0
            ) / 1000
            if weight > weight_selected:
                weight_selected = weight
                selected = media_source

        if selected is None:
            return None, None, None

        url = ""
        mimetype = "none/none"
        info = "Not playable"

        token = self.get_auth_token()
        # Jellyfin 12.0/12.1+ requires 'ApiKey' (legacy 'api_key' is rejected unless legacy auth is turned on).
        # Both are supplied here for universal compatibility across all Jellyfin versions.
        auth_param = f"ApiKey={token}&api_key={token}" if token else ""

        if selected.get("SupportsDirectStream"):
            if media_content_type in ("Audio", "track"):
                mimetype = "audio/" + selected.get("Container", "mp3")
                url = f"{self.get_server_url()}/Audio/{media_id}/stream?static=true&MediaSourceId={selected['Id']}&{auth_param}"
            else:
                mimetype = "video/" + selected.get("Container", "mp4")
                url = f"{self.get_server_url()}/Videos/{media_id}/stream?static=true&MediaSourceId={selected['Id']}&{auth_param}"

        elif selected.get("SupportsTranscoding"):
            transcoding_url = selected.get("TranscodingUrl", "")
            sep = "&" if "?" in transcoding_url else "?"
            url = f"{self.get_server_url()}{transcoding_url}{sep}{auth_param}"
            container = selected.get("TranscodingContainer") or selected.get("Container", "mp4")
            if media_content_type in ("Audio", "track"):
                mimetype = "audio/" + container
            else:
                mimetype = "video/" + container

        if media_content_type in ("Audio", "track"):
            for stream in selected.get("MediaStreams", []):
                if stream.get("Type") == "Audio":
                    info = f"{stream.get('Codec', '')} {stream.get('SampleRate', '')}Hz"
                    break
        else:
            for stream in selected.get("MediaStreams", []):
                if stream.get("Type") == "Video":
                    info = f"{stream.get('Width', '')}x{stream.get('Height', '')} {stream.get('Codec', '')}"
                    break

        _LOGGER.debug("Resolved stream info: %s - url: %s", info, url)
        return url, mimetype, info

    @property
    def api(self):
        """Return the Jellyfin API client."""
        return self.jf_client.jellyfin

    @property
    def devices(self) -> Mapping[str, JellyfinDevice]:
        """Return devices dictionary."""
        return self._devices

    # Callbacks

    def add_new_devices_callback(self, callback):
        """Register callback for when new devices are added and return unlistener."""
        self._new_devices_callbacks.append(callback)
        _LOGGER.debug("Added new devices callback: %s", callback)

        def unsubscribe():
            if callback in self._new_devices_callbacks:
                self._new_devices_callbacks.remove(callback)

        return unsubscribe

    def _do_new_devices_callback(self, msg):
        """Call registered callback functions thread-safely."""
        for callback in list(self._new_devices_callbacks):
            _LOGGER.debug("Devices callback %s", callback)
            self._event_loop.call_soon_threadsafe(callback, msg)

    def add_stale_devices_callback(self, callback):
        """Register callback for when stale devices exist and return unlistener."""
        self._stale_devices_callbacks.append(callback)
        _LOGGER.debug("Added stale devices callback: %s", callback)

        def unsubscribe():
            if callback in self._stale_devices_callbacks:
                self._stale_devices_callbacks.remove(callback)

        return unsubscribe

    def _do_stale_devices_callback(self, msg):
        """Call registered callback functions thread-safely."""
        for callback in list(self._stale_devices_callbacks):
            _LOGGER.debug("Stale Devices callback %s", callback)
            self._event_loop.call_soon_threadsafe(callback, msg)

    def add_update_callback(self, callback, device):
        """Register callback for when a matching device changes and return unlistener."""
        entry = [callback, device]
        self._update_callbacks.append(entry)
        _LOGGER.debug("Added update callback to %s on %s", callback, device)

        def unsubscribe():
            if entry in self._update_callbacks:
                self._update_callbacks.remove(entry)
                _LOGGER.debug("Removed update callback for %s", device)

        return unsubscribe

    def remove_update_callback(self, callback, device):
        """Remove a registered update callback."""
        entry = [callback, device]
        if entry in self._update_callbacks:
            self._update_callbacks.remove(entry)
            _LOGGER.debug("Removed update callback %s for %s", callback, device)

    def _do_update_callback(self, msg):
        """Call registered callback functions thread-safely."""
        for callback, device in list(self._update_callbacks):
            if device == msg:
                _LOGGER.debug("Update callback %s for device %s", callback, device)
                self._event_loop.call_soon_threadsafe(callback, msg)
