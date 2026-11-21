"""Switch platform for Wiser for KNX integration.

`fct.switching`, `fct.switchingSocket`, `fct.switchingAC` and
`fct.switchingFan`: one writable `dpt.switch` datapoint each. A socket's active
power (`dpt.power`, read-only, in W) is not part of the switch - it becomes its
own sensor.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import ROLE_SWITCH, ROLE_SWITCH_FEEDBACK, binary_state
from .entity import (
    WiserKnxBaseEntity,
    WiserKnxDatapointEntity,
    async_setup_plan_entities,
)
from .plan import PLATFORM_SWITCH

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX switches."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _entity(spec: dict[str, Any]):
        if spec.get("datapoint_id") is None:
            return WiserKnxSwitch(coordinator, entry.entry_id, spec["function_id"])
        return WiserKnxDatapointSwitch(coordinator, entry.entry_id, spec)

    async_setup_plan_entities(
        coordinator, entry, PLATFORM_SWITCH, _entity, async_add_entities
    )


class WiserKnxSwitch(WiserKnxBaseEntity, SwitchEntity):
    """Representation of a Wiser for KNX switch or socket."""

    def _get_switch_dp(self) -> dict[str, Any] | None:
        """Return the on/off datapoint of this function."""
        return self.role_datapoint(ROLE_SWITCH, ROLE_SWITCH_FEEDBACK)

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        dp = self._get_switch_dp()
        if not dp:
            return False
        return bool(binary_state(dp.get("value")))

    async def _write(self, value: str) -> None:
        dp = self._get_switch_dp()
        if dp is not None and dp.get("writable"):
            await self.coordinator.async_write_datapoint(dp["id"], value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self._write("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._write("off")


class WiserKnxDatapointSwitch(WiserKnxDatapointEntity, SwitchEntity):
    """A writable on/off datapoint a richer entity did not take.

    A thermostat's fan manual mode and an RGBW light's white channel are both
    writable `dpt.switch` slots that belong to no composite entity, so they get
    one of their own rather than disappearing.
    """

    @property
    def is_on(self) -> bool | None:
        """Return the state, or None while the controller publishes no value."""
        return binary_state(self.native_value_raw)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the datapoint."""
        await self.coordinator.async_write_datapoint(self.datapoint_id, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the datapoint."""
        await self.coordinator.async_write_datapoint(self.datapoint_id, "off")
