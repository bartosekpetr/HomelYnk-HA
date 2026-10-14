"""Sensor platform for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import WiserKnxBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX sensors."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxSensor] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            # Exclude functions handled by other domains (light, switch, cover, climate)
            cat = coordinator.classify_function(func)
            if cat in ("light", "switch", "cover", "climate"):
                continue

            dps = func.get("datapoints", {})
            for dp_id, dp in dps.items():
                entities.append(WiserKnxSensor(coordinator, entry.entry_id, func_id, dp_id))

    async_add_entities(entities)


class WiserKnxSensor(WiserKnxBaseEntity, SensorEntity):
    """Representation of a Wiser for KNX Sensor Datapoint."""

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        function_id: str,
        datapoint_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, function_id)
        self.datapoint_id = datapoint_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{datapoint_id}"
        self._init_sensor_properties()

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
        return dp_title or func_title or f"Sensor {self.datapoint_id}"

    def _init_sensor_properties(self) -> None:
        """Configure device class and unit based on DPT and metadata."""
        dp = self.datapoint_data
        types = dp.get("types", [])
        title = (dp.get("title") or "").lower()
        unit = (dp.get("unit") or "").strip().lower()

        # Temperature
        if any("valuetemp" in t or "temperature" in t for t in types) or "temp" in title or unit in ("°c", "c"):
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_state_class = SensorStateClass.MEASUREMENT
            return

        # Humidity
        if any("humidity" in t for t in types) or "hum" in title:
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            return

        # Battery
        if "battery" in title:
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            return

        # Power
        if any("dpt.power" in t for t in types) or "power" in title or unit in ("w", "kw", "watt"):
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = (
                UnitOfPower.KILO_WATT if "k" in unit else UnitOfPower.WATT
            )
            self._attr_state_class = SensorStateClass.MEASUREMENT
            return

        # Energy
        if "energy" in title or unit in ("wh", "kwh"):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = (
                UnitOfEnergy.KILO_WATT_HOUR if "k" in unit else UnitOfEnergy.WATT_HOUR
            )
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            return

        # Illuminance
        if any("lux" in t for t in types) or "lux" in title or unit in ("lux", "lx"):
            self._attr_device_class = SensorDeviceClass.ILLUMINANCE
            self._attr_native_unit_of_measurement = LIGHT_LUX
            self._attr_state_class = SensorStateClass.MEASUREMENT
            return

        # Fallback unit
        if dp.get("unit"):
            self._attr_native_unit_of_measurement = dp.get("unit")

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        val = self.datapoint_data.get("value")
        if val is None:
            return None

        # Convert numeric strings
        try:
            num = float(val)
            return round(num, 2)
        except (ValueError, TypeError):
            return str(val)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs = super().extra_state_attributes
        attrs["datapoint_id"] = self.datapoint_id
        attrs["datapoint_types"] = self.datapoint_data.get("types", [])
        return attrs
