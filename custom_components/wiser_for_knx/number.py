"""Number platform for Wiser for KNX integration.

Every writable numeric datapoint that is not already part of a richer entity: a
thermostat's fan speed percentage, a VDC thermostat's setpoint shift, the
secondary setpoints of a thermostat with occupied/standby/unoccupied modes, a
floor-heating temperature on a function that did not become a climate entity.

Values are passed through as the controller publishes them - they are already in
engineering units (a `dpt.scaling` raw 128 is published as `50` with `unit:
"%"`), so rescaling from 0-255 would be wrong by a factor of 2.55. The one
exception is `fct.se8000`, whose temperatures go through its F->C conversion.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import (
    ROLE_SETPOINT,
    ROLE_SETPOINT_SHIFT,
    ROLE_TEMPERATURE,
    temperature_in,
    temperature_out,
    to_float,
)
from .entity import WiserKnxDatapointEntity, async_setup_plan_entities
from .plan import PLATFORM_NUMBER

_TEMPERATURE_ROLES = (ROLE_TEMPERATURE, ROLE_SETPOINT, ROLE_SETPOINT_SHIFT)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX numbers."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_NUMBER,
        lambda spec: WiserKnxNumber(coordinator, entry.entry_id, spec),
        async_add_entities,
    )


class WiserKnxNumber(WiserKnxDatapointEntity, NumberEntity):
    """A writable numeric datapoint of a Wiser for KNX function."""

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, translating the controller's `C` to degrees Celsius."""
        if self.role in _TEMPERATURE_ROLES:
            return UnitOfTemperature.CELSIUS
        unit = self.datapoint.get("unit")
        return unit if unit in ("%", "W", "lx", "ppm", "m/s") else None

    @property
    def native_min_value(self) -> float:
        """Return the minimum the controller reports, or a default for the role."""
        value = to_float(self.datapoint.get("minimum"))
        if value is not None:
            return value
        if self.datapoint.get("unit") == "%":
            return 0
        return -50 if self.role in _TEMPERATURE_ROLES else -10000

    @property
    def native_max_value(self) -> float:
        """Return the maximum the controller reports, or a default for the role."""
        value = to_float(self.datapoint.get("maximum"))
        if value is not None:
            return value
        if self.datapoint.get("unit") == "%":
            return 100
        return 100 if self.role in _TEMPERATURE_ROLES else 10000

    @property
    def native_step(self) -> float:
        """Return a step matching what the datapoint carries."""
        return 0.5 if self.role in _TEMPERATURE_ROLES else 1

    @property
    def mode(self) -> NumberMode:
        """Return a box for a datapoint whose range the controller never stated.

        Only a thermostat's setpoints publish `minimum`/`maximum`; without them
        the range is a guess, and a slider over a guessed range is unusable.
        """
        if self.datapoint.get("unit") == "%" or self.role in _TEMPERATURE_ROLES:
            return NumberMode.SLIDER
        has_limits = (
            self.datapoint.get("minimum") is not None
            and self.datapoint.get("maximum") is not None
        )
        return NumberMode.SLIDER if has_limits else NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self.role in _TEMPERATURE_ROLES:
            return temperature_in(
                self.function_data.get("types"), self.role, self.native_value_raw
            )
        return to_float(self.native_value_raw)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value."""
        if self.role in _TEMPERATURE_ROLES:
            value = temperature_out(self.function_data.get("types"), value)
        await self.coordinator.async_write_datapoint(self.datapoint_id, value)
