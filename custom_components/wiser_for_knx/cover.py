"""Cover (shutter/blind) platform for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
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
    """Set up Wiser for KNX covers."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxCover] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            if coordinator.classify_function(func) == "cover":
                entities.append(WiserKnxCover(coordinator, entry.entry_id, func_id))

    async_add_entities(entities)


class WiserKnxCover(WiserKnxBaseEntity, CoverEntity):
    """Representation of a Wiser for KNX Cover (shutter / blind)."""

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        function_id: str,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator, entry_id, function_id)
        self._attr_device_class = CoverDeviceClass.SHUTTER

    def _get_position_dp(self) -> dict[str, Any] | None:
        """Find the shutter position datapoint (0-100%)."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            types = dp.get("types", [])
            title = (dp.get("title") or "").lower()
            if any("scaling" in t for t in types) or dp.get("unit") == "%" or "position" in title:
                return dp
        return None

    def _get_movement_dp(self) -> dict[str, Any] | None:
        """Find the Up/Down movement datapoint."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            title = (dp.get("title") or "").lower()
            if "down/up" in title or "up/down" in title or "move" in title:
                return dp
        # Fallback to switch-like
        for dp in dps.values():
            types = dp.get("types", [])
            if any("dpt.switch" in t or "openclose" in t.lower() for t in types):
                return dp
        return None

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Return supported features."""
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if self._get_position_dp() is not None:
            features |= CoverEntityFeature.SET_COVER_POSITION
        return features

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0 closed -> 100 open in HA)."""
        pos_dp = self._get_position_dp()
        if not pos_dp:
            return None
        val = pos_dp.get("value")
        if val is None:
            return None
        try:
            # KNX typically treats 100% as fully closed, 0% as open
            knx_pos = float(val)
            return int(100 - min(100, max(0, knx_pos)))
        except (ValueError, TypeError):
            return None

    @property
    def is_closed(self) -> bool | None:
        """Return True if cover is closed."""
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        mov_dp = self._get_movement_dp()
        if mov_dp:
            val = str(mov_dp.get("value") or "").lower()
            return val in ("on", "true", "close", "1")
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        pos_dp = self._get_position_dp()
        mov_dp = self._get_movement_dp()
        if pos_dp and pos_dp.get("writable"):
            await self.coordinator.async_write_datapoint(pos_dp["id"], 0)
        elif mov_dp and mov_dp.get("writable"):
            await self.coordinator.async_write_datapoint(mov_dp["id"], "off")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        pos_dp = self._get_position_dp()
        mov_dp = self._get_movement_dp()
        if pos_dp and pos_dp.get("writable"):
            await self.coordinator.async_write_datapoint(pos_dp["id"], 100)
        elif mov_dp and mov_dp.get("writable"):
            await self.coordinator.async_write_datapoint(mov_dp["id"], "on")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        mov_dp = self._get_movement_dp()
        if mov_dp and mov_dp.get("writable"):
            await self.coordinator.async_write_datapoint(mov_dp["id"], "off")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        pos_dp = self._get_position_dp()
        if pos_dp and pos_dp.get("writable"):
            ha_pos = kwargs.get("position", 100)
            knx_pos = 100 - ha_pos
            await self.coordinator.async_write_datapoint(pos_dp["id"], knx_pos)
