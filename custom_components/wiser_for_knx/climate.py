"""Climate (thermostat/HVAC) platform for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    """Set up Wiser for KNX climate entities."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxClimate] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            if coordinator.classify_function(func) == "climate":
                entities.append(WiserKnxClimate(coordinator, entry.entry_id, func_id))

    async_add_entities(entities)


class WiserKnxClimate(WiserKnxBaseEntity, ClimateEntity):
    """Representation of a Wiser for KNX Thermostat / Climate entity."""

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        function_id: str,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, entry_id, function_id)
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_min_temp = 7.0
        self._attr_max_temp = 35.0
        self._attr_target_temperature_step = 0.5

    def _get_current_temp_dp(self) -> dict[str, Any] | None:
        """Find current temperature sensor datapoint."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            title = (dp.get("title") or "").lower()
            if "temperature" in title or "temp" in title:
                if "setpoint" not in title and "target" not in title:
                    return dp
        return None

    def _get_setpoint_dp(self) -> dict[str, Any] | None:
        """Find target temperature setpoint datapoint."""
        dps = self.function_data.get("datapoints", {})
        # Look for writable setpoint
        for dp in dps.values():
            title = (dp.get("title") or "").lower()
            if ("setpoint" in title or "target" in title) and dp.get("writable"):
                return dp
        # Fallback to any writable temperature dp
        for dp in dps.values():
            if dp.get("writable"):
                types = dp.get("types", [])
                if any("valuetemp" in t for t in types):
                    return dp
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        dp = self._get_current_temp_dp()
        if not dp:
            # Fallback to setpoint
            dp = self._get_setpoint_dp()
        if not dp:
            return None
        val = dp.get("value")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target setpoint temperature."""
        dp = self._get_setpoint_dp()
        if not dp:
            return None
        val = dp.get("value")
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        setpoint_dp = self._get_setpoint_dp()
        if setpoint_dp and setpoint_dp.get("writable"):
            await self.coordinator.async_write_datapoint(setpoint_dp["id"], round(float(temp), 1))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
