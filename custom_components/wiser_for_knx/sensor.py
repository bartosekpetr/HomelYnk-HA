"""Sensor platform for Wiser for KNX integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import controller_device_info


class WiserKnxLastBackupSensor(SensorEntity):
    """Time of the last successful controller backup."""

    _attr_has_entity_name = True
    _attr_name = "Last backup"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        self._manager = coordinator.backup_manager
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_last_backup"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_added_to_hass(self) -> None:
        """Refresh the state whenever a backup finishes."""
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    @property
    def native_value(self):
        """Return the time of the last backup."""
        return self._manager.last_backup

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return backup details."""
        attrs: dict[str, Any] = {
            "scheduled": self._manager.interval_hours > 0 and self._manager.configured,
            "keep": self._manager.keep,
        }
        if self._manager.last_files:
            attrs["files"] = self._manager.last_files
        if self._manager.last_error:
            attrs["last_error"] = self._manager.last_error
        return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Wiser for KNX backup sensor."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WiserKnxLastBackupSensor(coordinator, entry.entry_id)])
