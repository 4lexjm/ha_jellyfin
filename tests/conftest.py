"""Mock Home Assistant modules and fixtures for testing."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from enum import Enum, IntFlag
from types import ModuleType
from unittest.mock import MagicMock


def _setup_homeassistant_mock():
    """Install lightweight mock homeassistant packages into sys.modules."""
    if "homeassistant" in sys.modules:
        return

    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_const = ModuleType("homeassistant.const")
    ha_exceptions = ModuleType("homeassistant.exceptions")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_cv = ModuleType("homeassistant.helpers.config_validation")
    ha_helpers_aiohttp = ModuleType("homeassistant.helpers.aiohttp_client")
    ha_helpers_device = ModuleType("homeassistant.helpers.device_registry")
    ha_helpers_dispatcher = ModuleType("homeassistant.helpers.dispatcher")
    ha_helpers_entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    ha_components = ModuleType("homeassistant.components")
    ha_comp_media_player = ModuleType("homeassistant.components.media_player")
    ha_comp_media_player_const = ModuleType("homeassistant.components.media_player.const")
    ha_comp_sensor = ModuleType("homeassistant.components.sensor")
    ha_comp_media_source = ModuleType("homeassistant.components.media_source")
    ha_comp_media_source_models = ModuleType("homeassistant.components.media_source.models")
    ha_comp_media_source_error = ModuleType("homeassistant.components.media_source.error")
    ha_comp_media_source_const = ModuleType("homeassistant.components.media_source.const")
    ha_util = ModuleType("homeassistant.util")
    ha_util_dt = ModuleType("homeassistant.util.dt")

    # core
    def callback(fn):
        return fn

    class HomeAssistant:
        def __init__(self):
            self.data = {}
            self.loop = asyncio.get_event_loop()
            self.services = MagicMock()
            self.config_entries = MagicMock()
            self.bus = MagicMock()

        async def async_add_executor_job(self, target, *args, **kwargs):
            return target(*args, **kwargs)

        def async_create_task(self, coro):
            return asyncio.create_task(coro)

    ha_core.HomeAssistant = HomeAssistant
    ha_core.callback = callback

    # const
    class Platform(str, Enum):
        SENSOR = "sensor"
        MEDIA_PLAYER = "media_player"

    ha_const.Platform = Platform
    ha_const.CONF_URL = "url"
    ha_const.CONF_USERNAME = "username"
    ha_const.CONF_PASSWORD = "password"
    ha_const.CONF_CLIENT_ID = "client_id"
    ha_const.CONF_VERIFY_SSL = "verify_ssl"
    ha_const.ATTR_ENTITY_ID = "entity_id"
    ha_const.ATTR_ID = "id"
    ha_const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    ha_const.STATE_ON = "on"
    ha_const.STATE_OFF = "off"
    ha_const.STATE_PLAYING = "playing"
    ha_const.STATE_PAUSED = "paused"
    ha_const.STATE_IDLE = "idle"
    ha_const.DEVICE_DEFAULT_NAME = "Jellyfin"

    # exceptions
    class HomeAssistantError(Exception):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    ha_exceptions.HomeAssistantError = HomeAssistantError
    ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    ha_exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed

    # config_entries
    class ConfigEntry:
        def __init__(self, entry_id="test_entry", data=None, options=None, title="Jellyfin"):
            self.entry_id = entry_id
            self.data = data or {}
            self.options = options or {}
            self.title = title
            self.unique_id = None
            self.runtime_data = None
            self._unloaders = []

        def async_on_unload(self, unloader):
            self._unloaders.append(unloader)

        def add_update_listener(self, listener):
            return lambda: None

    class ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)

        async def async_set_unique_id(self, uid):
            pass

        def _abort_if_unique_id_configured(self):
            pass

        def async_create_entry(self, title, data):
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, step_id, data_schema, errors=None):
            return {"type": "form", "step_id": step_id, "errors": errors or {}}

        def async_abort(self, reason):
            return {"type": "abort", "reason": reason}

    class OptionsFlow:
        def async_create_entry(self, title="", data=None):
            return {"type": "create_entry", "data": data}

        def async_show_form(self, step_id, data_schema, errors=None):
            return {"type": "form", "step_id": step_id, "errors": errors or {}}

    class HandlersDict(dict):
        def register(self, domain):
            def decorator(cls):
                self[domain] = cls
                return cls

            return decorator

    ha_config_entries.ConfigEntry = ConfigEntry
    ha_config_entries.ConfigFlow = ConfigFlow
    ha_config_entries.OptionsFlow = OptionsFlow
    ha_config_entries.CONN_CLASS_LOCAL_PUSH = "local_push"
    ha_config_entries.HANDLERS = HandlersDict()

    # config_validation
    def entity_id(val):
        return str(val)

    def string(val):
        return str(val)

    ha_helpers_cv.entity_id = entity_id
    ha_helpers_cv.string = string

    # aiohttp_client
    def async_get_clientsession(hass, verify_ssl=True):
        session = MagicMock()
        return session

    ha_helpers_aiohttp.async_get_clientsession = async_get_clientsession

    # device_registry
    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__dict__.update(kwargs)

    class DeviceEntry:
        def __init__(self, id):
            self.id = id

    ha_helpers_device.DeviceInfo = DeviceInfo
    ha_helpers_device.DeviceEntry = DeviceEntry

    # dispatcher
    def async_dispatcher_send(hass, signal, *args):
        pass

    ha_helpers_dispatcher.async_dispatcher_send = async_dispatcher_send

    # entity_registry
    def async_get(hass):
        return MagicMock()

    def async_entries_for_device(ent_reg, dev_id):
        return []

    ha_helpers_entity_registry.async_get = async_get
    ha_helpers_entity_registry.async_entries_for_device = async_entries_for_device

    # media_player
    class MediaPlayerState(str, Enum):
        OFF = "off"
        ON = "on"
        PLAYING = "playing"
        PAUSED = "paused"
        IDLE = "idle"

    class MediaPlayerEntityFeature(IntFlag):
        PAUSE = 1
        SEEK = 2
        VOLUME_SET = 4
        VOLUME_MUTE = 8
        PREVIOUS_TRACK = 16
        NEXT_TRACK = 32
        TURN_ON = 128
        TURN_OFF = 256
        PLAY_MEDIA = 512
        VOLUME_STEP = 1024
        SELECT_SOURCE = 2048
        STOP = 4096
        CLEAR_PLAYLIST = 8192
        PLAY = 16384
        SHUFFLE_SET = 32768
        SELECT_SOUND_MODE = 65536
        BROWSE_MEDIA = 131072
        REPEAT_SET = 262144
        GROUPING = 524288

    class MediaType(str, Enum):
        MUSIC = "music"
        TVSHOW = "tvshow"
        MOVIE = "movie"
        VIDEO = "video"
        EPISODE = "episode"
        CHANNEL = "channel"
        PLAYLIST = "playlist"
        ALBUM = "album"
        ARTIST = "artist"
        TRACK = "track"
        SEASON = "season"

    class MediaClass(str, Enum):
        ALBUM = "album"
        ARTIST = "artist"
        CHANNEL = "channel"
        COMPOSER = "composer"
        CONTRIBUTING_ARTIST = "contributing_artist"
        DIRECTORY = "directory"
        EPISODE = "episode"
        GENRE = "genre"
        IMAGE = "image"
        MOVIE = "movie"
        MUSIC = "music"
        PLAYLIST = "playlist"
        PODCAST = "podcast"
        PODCAST_EPISODE = "podcast_episode"
        SEASON = "season"
        TRACK = "track"
        TV_SHOW = "tv_show"
        URL = "url"
        VIDEO = "video"

    class MediaPlayerEnqueue(str, Enum):
        ADD = "add"
        NEXT = "next"
        PLAY = "play"
        REPLACE = "replace"

    class BrowseError(Exception):
        pass

    class BrowseMedia:
        pass

    class MediaPlayerEntity:
        hass = None
        entity_id = "media_player.test"

        def async_write_ha_state(self):
            pass

    ha_comp_media_player.MediaPlayerEntity = MediaPlayerEntity
    ha_comp_media_player.MediaPlayerEnqueue = MediaPlayerEnqueue
    ha_comp_media_player.MediaPlayerEntityFeature = MediaPlayerEntityFeature
    ha_comp_media_player.MediaPlayerState = MediaPlayerState
    ha_comp_media_player.MediaType = MediaType
    ha_comp_media_player.MediaClass = MediaClass
    ha_comp_media_player.BrowseError = BrowseError
    ha_comp_media_player.BrowseMedia = BrowseMedia

    ha_comp_media_player_const.MediaClass = MediaClass
    ha_comp_media_player_const.MediaType = MediaType
    ha_comp_media_player_const.MediaPlayerEntityFeature = MediaPlayerEntityFeature
    ha_comp_media_player_const.MediaPlayerState = MediaPlayerState

    # sensor
    class SensorEntity:
        hass = None
        entity_id = "sensor.test"

        def async_write_ha_state(self):
            pass

        def async_schedule_update_ha_state(self, force_refresh=False):
            pass

    ha_comp_sensor.SensorEntity = SensorEntity

    # media_source
    class BrowseMediaSource:
        def __init__(self, **kwargs):
            self.children = []
            for k, v in kwargs.items():
                setattr(self, k, v)

    class MediaSource:
        def __init__(self, domain):
            self.domain = domain

    class MediaSourceItem:
        def __init__(self, identifier):
            self.identifier = identifier

    class PlayMedia:
        def __init__(self, url, mime_type):
            self.url = url
            self.mime_type = mime_type

    class Unresolvable(Exception):
        pass

    class MediaSourceError(Exception):
        pass

    def is_media_source_id(id_str):
        return str(id_str).startswith("media-source://")

    ha_comp_media_source.is_media_source_id = is_media_source_id
    ha_comp_media_source.BrowseMediaSource = BrowseMediaSource
    ha_comp_media_source.MediaSource = MediaSource
    ha_comp_media_source.MediaSourceItem = MediaSourceItem
    ha_comp_media_source.PlayMedia = PlayMedia
    ha_comp_media_source.Unresolvable = Unresolvable
    ha_comp_media_source.MediaSourceError = MediaSourceError

    ha_comp_media_source_models.BrowseMediaSource = BrowseMediaSource
    ha_comp_media_source_models.MediaSource = MediaSource
    ha_comp_media_source_models.MediaSourceItem = MediaSourceItem
    ha_comp_media_source_models.PlayMedia = PlayMedia

    ha_comp_media_source_error.Unresolvable = Unresolvable
    ha_comp_media_source_error.MediaSourceError = MediaSourceError

    ha_comp_media_source_const.MEDIA_MIME_TYPES = ("audio/*", "video/*")
    ha_comp_media_source_const.URI_SCHEME = "media-source://"

    # dt_util
    def utcnow():
        return datetime.now(timezone.utc)

    ha_util_dt.utcnow = utcnow

    # Populate sys.modules
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.exceptions"] = ha_exceptions
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.config_validation"] = ha_helpers_cv
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_helpers_aiohttp
    sys.modules["homeassistant.helpers.device_registry"] = ha_helpers_device
    sys.modules["homeassistant.helpers.dispatcher"] = ha_helpers_dispatcher
    sys.modules["homeassistant.helpers.entity_registry"] = ha_helpers_entity_registry
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.media_player"] = ha_comp_media_player
    sys.modules["homeassistant.components.media_player.const"] = ha_comp_media_player_const
    sys.modules["homeassistant.components.sensor"] = ha_comp_sensor
    sys.modules["homeassistant.components.media_source"] = ha_comp_media_source
    sys.modules["homeassistant.components.media_source.models"] = ha_comp_media_source_models
    sys.modules["homeassistant.components.media_source.error"] = ha_comp_media_source_error
    sys.modules["homeassistant.components.media_source.const"] = ha_comp_media_source_const
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_util_dt


_setup_homeassistant_mock()
