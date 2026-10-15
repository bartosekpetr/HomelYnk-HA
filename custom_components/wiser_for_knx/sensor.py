"""Sensor platform for Wiser for KNX integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator, WiserKnxHealthCoordinator
from .entity import controller_device_info

HealthSensorDescription = SensorEntityDescription

HEALTH_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="firmware", name="Firmware version"),
    SensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="load_1m",
        name="CPU load (1 min)",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="memory_used_percent",
        name="Memory used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="storage_used_percent",
        name="Storage used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


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


class WiserKnxHealthSensor(CoordinatorEntity[WiserKnxHealthCoordinator], SensorEntity):
    """A diagnostic value read from the controller's management API."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: WiserKnxHealthCoordinator,
        main: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        description: HealthSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = controller_device_info(main, entry_id)

    @property
    def native_value(self):
        """Return the current value."""
        return (self.coordinator.data or {}).get(self.entity_description.key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Wiser for KNX backup and health sensors."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [WiserKnxLastBackupSensor(coordinator, entry.entry_id)]
    if coordinator.health is not None:
        entities.extend(
            WiserKnxHealthSensor(coordinator.health, coordinator, entry.entry_id, desc)
            for desc in HEALTH_SENSORS
        )
    async_add_entities(entities)
