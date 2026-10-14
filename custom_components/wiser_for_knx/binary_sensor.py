"""Binary sensor platform for Wiser for KNX (alarms, door/window and motion sensors)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import WiserKnxBaseEntity
from .widgets import CAT_BINARY_SENSOR, binary_device_class, is_binary_datapoint

_LOGGER = logging.getLogger(__name__)

_ON_VALUES = ("on", "true", "1", "active", "alarm", "open", "opened", "detected")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX binary sensors."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxBinarySensor] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            if coordinator.classify_function(func) != CAT_BINARY_SENSOR:
                continue
            for dp_id, dp in func.get("datapoints", {}).items():
                if is_binary_datapoint(func, dp):
                    entities.append(
                        WiserKnxBinarySensor(coordinator, entry.entry_id, func_id, dp_id)
                    )

    async_add_entities(entities)


class WiserKnxBinarySensor(WiserKnxBaseEntity, BinarySensorEntity):
    """On/off state of an alarm, door, window or motion widget."""

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        function_id: str,
        datapoint_id: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry_id, function_id)
        self.datapoint_id = datapoint_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{datapoint_id}"

        title = (self.datapoint_data.get("title") or "").lower()
        if "battery" in title:
            self._attr_device_class = BinarySensorDeviceClass.BATTERY
        else:
            name = binary_device_class(self.function_data)
            if name:
                self._attr_device_class = getattr(BinarySensorDeviceClass, name, None)

    @property
    def datapoint_data(self) -> dict[str, Any]:
        """Return the datapoint dict."""
        if self.coordinator.data and "datapoints" in self.coordinator.data:
            return self.coordinator.data["datapoints"].get(self.datapoint_id, {})
        return {}

    @property
    def name(self) -> str | None:
        """Return entity name."""
        dp_title = self.datapoint_data.get("title")
        func_title = self.function_data.get("title")
        if dp_title and func_title:
            if dp_title.lower() in func_title.lower():
                return func_title
            return f"{func_title} {dp_title}"
        return dp_title or func_title or f"Binary sensor {self.datapoint_id}"

    @property
    def is_on(self) -> bool | None:
        """Return True if the datapoint is active."""
        value = self.datapoint_data.get("value")
        if value is None:
            return None
        return str(value).strip().lower() in _ON_VALUES

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = super().extra_state_attributes
        attrs["datapoint_id"] = self.datapoint_id
        return attrs
