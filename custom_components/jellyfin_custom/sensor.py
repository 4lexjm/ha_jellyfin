"""Support for Jellyfin sensor entity."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    CONF_URL,
    DEVICE_DEFAULT_NAME,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from . import JellyfinClientManager, autolog
from .const import DOMAIN

PLATFORM = "sensor"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Jellyfin sensor from config entry."""
    manager: JellyfinClientManager = None
    if hasattr(config_entry, "runtime_data") and config_entry.runtime_data:
        manager = config_entry.runtime_data
    else:
        url_key = config_entry.data.get(CONF_URL)
        manager = hass.data[DOMAIN][url_key]["manager"]

    async_add_entities([JellyfinSensor(manager)], True)


class JellyfinSensor(SensorEntity):
    """Representation of a Jellyfin Server sensor."""

    def __init__(self, jelly_cm: JellyfinClientManager):
        """Initialize the Jellyfin sensor."""
        _LOGGER.debug("New Jellyfin Sensor initialized")
        self.jelly_cm = jelly_cm
        self._available = True

    async def async_added_to_hass(self):
        """Register entity when added to HA."""
        autolog("<<<")
        server_data = self.hass.data.get(DOMAIN, {}).get(self.jelly_cm.host, {})
        server_data.setdefault(PLATFORM, {}).setdefault("entities", []).append(self)

    async def async_will_remove_from_hass(self):
        """Unregister entity when removed from HA."""
        autolog("<<<")
        server_data = self.hass.data.get(DOMAIN, {}).get(self.jelly_cm.host, {})
        entities = server_data.get(PLATFORM, {}).get("entities", [])
        if self in entities:
            entities.remove(self)

    @property
    def available(self) -> bool:
        """Return True if server is available."""
        return self.jelly_cm.is_available

    @property
    def unique_id(self) -> str | None:
        """Return unique ID of the server entity."""
        info = self.jelly_cm.info or {}
        return info.get("Id") or f"{DOMAIN}_{self.jelly_cm.server_url}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this server."""
        info = self.jelly_cm.info or {}
        version = info.get("Version", "Unknown")
        server_name = info.get("ServerName") or "Server"
        return DeviceInfo(
            identifiers={(DOMAIN, self.jelly_cm.server_url)},
            manufacturer="Jellyfin",
            model=f"Jellyfin {version}".rstrip(),
            name=f"Jellyfin {server_name}",
            configuration_url=self.jelly_cm.server_url,
            sw_version=version,
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        info = self.jelly_cm.info or {}
        server_name = info.get("ServerName")
        if server_name:
            return f"Jellyfin {server_name}"
        return DEVICE_DEFAULT_NAME

    @property
    def should_poll(self) -> bool:
        """No polling needed for push-based status updates."""
        return False

    @property
    def native_value(self) -> str:
        """Return the state of the server sensor."""
        return STATE_ON if self.jelly_cm.is_available else STATE_OFF

    @property
    def state(self) -> str:
        """Return legacy state string."""
        return self.native_value

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        info = self.jelly_cm.info or {}
        extra_attr = {
            "os": info.get("OperatingSystem"),
            "update_available": info.get("HasUpdateAvailable", False),
            "version": info.get("Version"),
        }
        if self.jelly_cm.data:
            extra_attr["data"] = self.jelly_cm.data
        if self.jelly_cm.yamc:
            extra_attr["yamc"] = self.jelly_cm.yamc

        return extra_attr

    async def async_update(self):
        """Synchronise state from the server."""
        autolog("<<<")
        await self.jelly_cm.update_data()

    async def async_trigger_scan(self):
        """Trigger a library refresh scan."""
        _LOGGER.info("Library scan triggered on Jellyfin server")
        await self.jelly_cm.trigger_scan()

    async def async_delete_item(self, id: str):
        """Delete an item from Jellyfin."""
        _LOGGER.debug("async_delete_item triggered for %s", id)
        await self.jelly_cm.delete_item(id)
        self.async_write_ha_state()

    async def async_search_item(self, search_term: str):
        """Search items on Jellyfin."""
        _LOGGER.debug("async_search_item triggered: %s", search_term)
        await self.jelly_cm.search_item(search_term)
        self.async_write_ha_state()

    async def async_yamc_setpage(self, page: int):
        """Set page in YAMC."""
        _LOGGER.debug("YAMC setpage: %d", page)
        await self.jelly_cm.yamc_set_page(page)
        self.async_write_ha_state()

    async def async_yamc_setplaylist(self, playlist: str):
        """Set playlist in YAMC."""
        _LOGGER.debug("YAMC setplaylist: %s", playlist)
        await self.jelly_cm.yamc_set_playlist(playlist)
        self.async_write_ha_state()
