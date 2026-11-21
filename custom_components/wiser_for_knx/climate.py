"""Climate platform for Wiser for KNX integration.

Thermostats are the one place where the controller's model and Home Assistant's
disagree, so the mapping is spelled out:

* `dpt.valueTemp` read-only (slot `temperature`) is the **current temperature**;
  the writable one (slot `setpoint-status`) is the **target**. They are told
  apart by their archetype and writability, never by their title - the title is
  the installer's own group object name.
* `dpt.hvacOperationMode` (`auto,comfort,standby,economy,buildingProtection`) is
  the KNX *operation mode*. That is a Home Assistant **preset**, not an HVAC
  mode: none of its members says heat or cool.
* `dpt.heatCool` (`heat,cool`) is what selects heating or cooling, and the
  `dpt.switch` at `dic:dpa.417.72` (slot `thermostat-switch-status`) is what
  turns the thermostat off. Together they make up the HVAC mode. A thermostat
  publishes a *second* writable `dpt.switch` at `dic:dpa.417.70` - its fan
  manual mode - which is why the two archetypes carry different roles: writing
  the wrong one would stop the fan when Home Assistant asked for the thermostat.
* `fct.se8000` publishes every temperature through an F->C conversion while
  still labelling it `C`; `datapoints.temperature_in/out` undo it on the way in
  and redo it on the way out. Every other temperature function passes through
  unchanged.

Enum values are written back verbatim as the controller publishes them (a
non-member is accepted with HTTP 202 and then silently discarded), which the
coordinator takes care of.
"""

from __future__ import annotations

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
from .datapoints import (
    ROLE_FAN_MODE,
    ROLE_HEAT_COOL,
    ROLE_HVAC_MODE,
    ROLE_SETPOINT,
    ROLE_SWITCH_FEEDBACK,
    ROLE_TEMPERATURE,
    binary_state,
    temperature_in,
    temperature_out,
    to_float,
)
from .entity import WiserKnxBaseEntity, async_setup_plan_entities
from .plan import PLATFORM_CLIMATE

# KNX operation modes, as Home Assistant preset names
_PRESETS = {
    "auto": "auto",
    "comfort": "comfort",
    "standby": "standby",
    "economy": "eco",
    "buildingprotection": "building protection",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX climate devices."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_CLIMATE,
        lambda spec: WiserKnxClimate(coordinator, entry.entry_id, spec["function_id"]),
        async_add_entities,
    )


class WiserKnxClimate(WiserKnxBaseEntity, ClimateEntity):
    """Representation of a Wiser for KNX thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    # Opt out of the turn_on/turn_off shim rather than inherit its deprecation
    # warning; harmless on the versions that no longer have it (min HA 2024.12).
    _enable_turn_on_off_backwards_compatibility = False

    @property
    def _function_types(self) -> list[str]:
        return self.function_data.get("types") or []

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the features this thermostat's datapoints support."""
        features = ClimateEntityFeature(0)
        if self.role_datapoint(ROLE_SETPOINT, writable=True):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if self.role_datapoint(ROLE_HVAC_MODE, writable=True):
            features |= ClimateEntityFeature.PRESET_MODE
        if self.role_datapoint(ROLE_FAN_MODE, writable=True):
            features |= ClimateEntityFeature.FAN_MODE
        if self.role_datapoint(ROLE_SWITCH_FEEDBACK, writable=True):
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        return features

    @property
    def current_temperature(self) -> float | None:
        """Return the measured temperature."""
        dp = self.role_datapoint(ROLE_TEMPERATURE)
        if dp is None:
            return None
        return temperature_in(self._function_types, ROLE_TEMPERATURE, dp.get("value"))

    @property
    def target_temperature(self) -> float | None:
        """Return the setpoint."""
        dp = self.role_datapoint(ROLE_SETPOINT)
        if dp is None:
            return None
        return temperature_in(self._function_types, ROLE_SETPOINT, dp.get("value"))

    @property
    def min_temp(self) -> float:
        """Return the setpoint minimum the controller reports, or the default."""
        dp = self.role_datapoint(ROLE_SETPOINT) or {}
        value = to_float(dp.get("minimum"))
        return value if value is not None else super().min_temp

    @property
    def max_temp(self) -> float:
        """Return the setpoint maximum the controller reports, or the default."""
        dp = self.role_datapoint(ROLE_SETPOINT) or {}
        value = to_float(dp.get("maximum"))
        return value if value is not None else super().max_temp

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the HVAC modes this thermostat can be put in."""
        modes: list[HVACMode] = []
        heat_cool = self.role_datapoint(ROLE_HEAT_COOL, writable=True)
        if heat_cool:
            members = {str(m).casefold() for m in (heat_cool.get("enum") or [])}
            if "heat" in members:
                modes.append(HVACMode.HEAT)
            if "cool" in members:
                modes.append(HVACMode.COOL)
        if not modes:
            modes.append(HVACMode.HEAT)
        if self.role_datapoint(ROLE_SWITCH_FEEDBACK, writable=True):
            modes.append(HVACMode.OFF)
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        switch = self.role_datapoint(ROLE_SWITCH_FEEDBACK)
        if switch is not None and binary_state(switch.get("value")) is False:
            return HVACMode.OFF
        heat_cool = self.role_datapoint(ROLE_HEAT_COOL)
        if heat_cool is not None:
            value = str(heat_cool.get("value") or "").strip().casefold()
            if value == "cool":
                return HVACMode.COOL
            if value == "heat":
                return HVACMode.HEAT
        # A thermostat with neither a changeover nor an on/off slot has exactly one
        # mode, and `hvac_modes` already says so, so reporting it is not a guess.
        return HVACMode.HEAT

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the KNX operation modes as presets."""
        dp = self.role_datapoint(ROLE_HVAC_MODE)
        if dp is None:
            return None
        return [
            _PRESETS.get(str(member).casefold(), str(member))
            for member in (dp.get("enum") or [])
        ]

    @property
    def preset_mode(self) -> str | None:
        """Return the current operation mode as a preset."""
        dp = self.role_datapoint(ROLE_HVAC_MODE)
        if dp is None:
            return None
        value = dp.get("value")
        if value is None:
            return None
        return _PRESETS.get(str(value).casefold(), str(value))

    @property
    def fan_modes(self) -> list[str] | None:
        """Return the fan modes, where the function has a fan mode datapoint."""
        dp = self.role_datapoint(ROLE_FAN_MODE)
        if dp is None:
            return None
        return [str(member) for member in (dp.get("enum") or [])] or None

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        dp = self.role_datapoint(ROLE_FAN_MODE)
        return None if dp is None else dp.get("value")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new setpoint."""
        wanted = kwargs.get(ATTR_TEMPERATURE)
        if wanted is None:
            return
        await self.async_write_role(
            ROLE_SETPOINT, temperature_out(self._function_types, float(wanted))
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn the thermostat off, or select heating or cooling."""
        if hvac_mode == HVACMode.OFF:
            await self.async_write_role(ROLE_SWITCH_FEEDBACK, "off")
            return
        if self.role_datapoint(ROLE_SWITCH_FEEDBACK, writable=True):
            await self.async_write_role(ROLE_SWITCH_FEEDBACK, "on")
        if hvac_mode in (HVACMode.HEAT, HVACMode.COOL):
            await self.async_write_role(
                ROLE_HEAT_COOL, "heat" if hvac_mode == HVACMode.HEAT else "cool"
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select a KNX operation mode."""
        dp = self.role_datapoint(ROLE_HVAC_MODE, writable=True)
        if dp is None:
            return
        wanted = preset_mode.casefold()
        for member in dp.get("enum") or []:
            if _PRESETS.get(str(member).casefold(), str(member)).casefold() == wanted:
                await self.coordinator.async_write_datapoint(dp["id"], member)
                return

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Select a fan mode."""
        await self.async_write_role(ROLE_FAN_MODE, fan_mode)

    async def async_turn_on(self) -> None:
        """Turn the thermostat on."""
        await self.async_write_role(ROLE_SWITCH_FEEDBACK, "on")

    async def async_turn_off(self) -> None:
        """Turn the thermostat off."""
        await self.async_write_role(ROLE_SWITCH_FEEDBACK, "off")
