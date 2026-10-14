"""Switch platform for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up Wiser for KNX switches."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxSwitch] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            if coordinator.classify_function(func) == "switch":
                entities.append(WiserKnxSwitch(coordinator, entry.entry_id, func_id))

    async_add_entities(entities)


class WiserKnxSwitch(WiserKnxBaseEntity, SwitchEntity):
    """Representation of a Wiser for KNX Switch or Socket."""

    def _get_switch_dp(self) -> dict[str, Any] | None:
        """Find the on/off switch datapoint."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            types = dp.get("types", [])
            title = (dp.get("title") or "").lower()
            if any("dpt.switch" in t or "dpt.bool" in t for t in types):
                return dp
            if "on/off" in title or "on off" in title or "status" in title:
                return dp
        # Fallback to first writable
        for dp in dps.values():
            if dp.get("writable"):
                return dp
        return None

    @property
    def is_on(self) -> bool:
        """Return True if switch is on."""
        dp = self._get_switch_dp()
        if not dp:
            return False
        val = str(dp.get("value") or "").lower()
        return val in ("on", "true", "1")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        dp = self._get_switch_dp()
        if dp and dp.get("writable"):
            await self.coordinator.async_write_datapoint(dp["id"], "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        dp = self._get_switch_dp()
        if dp and dp.get("writable"):
            await self.coordinator.async_write_datapoint(dp["id"], "off")
