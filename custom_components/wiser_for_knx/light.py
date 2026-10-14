"""Light platform for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
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
    """Set up Wiser for KNX lights."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[WiserKnxLight] = []
    if coordinator.data and "functions" in coordinator.data:
        for func_id, func in coordinator.data["functions"].items():
            if coordinator.classify_function(func) == "light":
                entities.append(WiserKnxLight(coordinator, entry.entry_id, func_id))

    async_add_entities(entities)


class WiserKnxLight(WiserKnxBaseEntity, LightEntity):
    """Representation of a Wiser for KNX Light (on/off and dimmable)."""

    def _get_switch_dp(self) -> dict[str, Any] | None:
        """Find the on/off switch datapoint."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            types = dp.get("types", [])
            title = (dp.get("title") or "").lower()
            if any("dpt.switch" in t or "417.70" in t or "418.61" in t for t in types):
                return dp
            if "on off" in title or "on/off" in title:
                return dp
        # Fallback to first writable dp
        for dp in dps.values():
            if dp.get("writable"):
                return dp
        return None

    def _get_brightness_dp(self) -> dict[str, Any] | None:
        """Find the brightness / scaling datapoint."""
        dps = self.function_data.get("datapoints", {})
        for dp in dps.values():
            types = dp.get("types", [])
            title = (dp.get("title") or "").lower()
            if any("scaling" in t or "418.63" in t for t in types) or dp.get("unit") == "%":
                return dp
            if "value 8bit" in title or "calculated level" in title or "dimm value" in title:
                return dp
        return None

    @property
    def is_dimmable(self) -> bool:
        """Return True if brightness datapoint exists."""
        return self._get_brightness_dp() is not None

    @property
    def color_mode(self) -> ColorMode:
        """Return color mode."""
        return ColorMode.BRIGHTNESS if self.is_dimmable else ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes."""
        return {ColorMode.BRIGHTNESS} if self.is_dimmable else {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        """Return True if light is currently on."""
        sw_dp = self._get_switch_dp()
        if sw_dp:
            val = str(sw_dp.get("value") or "").lower()
            return val in ("on", "true", "1")

        br_dp = self._get_brightness_dp()
        if br_dp:
            try:
                return float(br_dp.get("value", 0)) > 0
            except (ValueError, TypeError):
                pass
        return False

    @property
    def brightness(self) -> int | None:
        """Return brightness (0..255)."""
        br_dp = self._get_brightness_dp()
        if not br_dp:
            return None
        val = br_dp.get("value")
        if val is None:
            return None
        try:
            percent = float(val)
            return int(min(255, max(0, (percent / 100.0) * 255)))
        except (ValueError, TypeError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light or adjust brightness."""
        br_dp = self._get_brightness_dp()
        sw_dp = self._get_switch_dp()

        if ATTR_BRIGHTNESS in kwargs and br_dp:
            brightness_255 = kwargs[ATTR_BRIGHTNESS]
            percent = int((brightness_255 / 255.0) * 100)
            await self.coordinator.async_write_datapoint(br_dp["id"], percent)
        else:
            if sw_dp and sw_dp.get("writable"):
                await self.coordinator.async_write_datapoint(sw_dp["id"], "on")
            elif br_dp and br_dp.get("writable"):
                await self.coordinator.async_write_datapoint(br_dp["id"], 100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        sw_dp = self._get_switch_dp()
        br_dp = self._get_brightness_dp()

        if sw_dp and sw_dp.get("writable"):
            await self.coordinator.async_write_datapoint(sw_dp["id"], "off")
        elif br_dp and br_dp.get("writable"):
            await self.coordinator.async_write_datapoint(br_dp["id"], 0)
