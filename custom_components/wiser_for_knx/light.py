"""Light platform for Wiser for KNX integration.

Covers the four shapes the controller publishes: on/off (`fct.switchingLight`),
dimmable (`fct.dimming`, `fct.dimmingDali`), RGB (`fct.colorRGB`, one
`dpt.R-G-B` datapoint carrying a hex triplet) and RGBW (`fct.colorRGBW`, three
or four `dpt.scaling` datapoints, one per channel).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import (
    ROLE_BRIGHTNESS,
    ROLE_COLOR_BLUE,
    ROLE_COLOR_GREEN,
    ROLE_COLOR_RED,
    ROLE_COLOR_RGB,
    ROLE_COLOR_WHITE,
    ROLE_SWITCH,
    ROLE_SWITCH_FEEDBACK,
    binary_state,
    to_float,
)
from .entity import WiserKnxBaseEntity, async_setup_plan_entities
from .plan import PLATFORM_LIGHT

_LOGGER = logging.getLogger(__name__)

_RGB_ROLES = (ROLE_COLOR_RED, ROLE_COLOR_GREEN, ROLE_COLOR_BLUE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX lights."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_LIGHT,
        lambda spec: WiserKnxLight(coordinator, entry.entry_id, spec["function_id"]),
        async_add_entities,
    )


def _percent_to_255(percent: float | None) -> int | None:
    """Return a controller percentage as Home Assistant's 0-255 scale."""
    if percent is None:
        return None
    return int(min(255, max(0, percent / 100.0 * 255)))


def _255_to_percent(value: int) -> int:
    """Return a Home Assistant 0-255 value as the percentage the controller wants."""
    return int(min(100, max(0, value / 255.0 * 100)))


class WiserKnxLight(WiserKnxBaseEntity, LightEntity):
    """Representation of a Wiser for KNX light."""

    def _get_switch_dp(self) -> dict[str, Any] | None:
        """Return the on/off datapoint, or None for a dimmer without one.

        A `dpt.scaling` brightness slot answers a percentage, never on/off, so a
        dimmer that publishes only its value has no switch datapoint - which is
        the correct answer: `is_on` and the turn on/off calls then drive the
        brightness instead.
        """
        return self.role_datapoint(ROLE_SWITCH, ROLE_SWITCH_FEEDBACK)

    def _get_brightness_dp(self) -> dict[str, Any] | None:
        """Return the brightness datapoint.

        Its value is a percentage: the controller converts per datapoint type,
        publishing a raw 128 as `50` with `unit: "%"`, so it is never rescaled
        from 0-255 (that would be wrong by a factor of 2.55).
        """
        if self._rgbw_channels():
            return None
        return self.role_datapoint(ROLE_BRIGHTNESS)

    def _get_rgb_dp(self) -> dict[str, Any] | None:
        """Return the combined RGB datapoint (`dpt.R-G-B`, a hex triplet)."""
        return self.role_datapoint(ROLE_COLOR_RGB)

    def _rgbw_channels(self) -> dict[str, dict[str, Any]]:
        """Return the per-channel colour datapoints, keyed by role.

        An RGBW light publishes red, green and blue (and optionally white) as
        separate `dpt.scaling` datapoints. Only a complete RGB triplet counts:
        with one channel missing there is no colour to report.
        """
        by_role = self.datapoints_by_role()
        channels = {role: by_role[role] for role in _RGB_ROLES if role in by_role}
        if len(channels) < len(_RGB_ROLES):
            return {}
        if ROLE_COLOR_WHITE in by_role:
            channels[ROLE_COLOR_WHITE] = by_role[ROLE_COLOR_WHITE]
        return channels

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode."""
        channels = self._rgbw_channels()
        if ROLE_COLOR_WHITE in channels:
            return ColorMode.RGBW
        if channels or self._get_rgb_dp():
            return ColorMode.RGB
        if self._get_brightness_dp():
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return the supported color modes."""
        return {self.color_mode}

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        sw_dp = self._get_switch_dp()
        if sw_dp:
            state = binary_state(sw_dp.get("value"))
            if state is not None:
                return state
        for dp in (self._get_brightness_dp(), *self._rgbw_channels().values()):
            value = to_float((dp or {}).get("value"))
            if value:
                return True
        rgb = self.rgb_color
        return bool(rgb and any(rgb))

    @property
    def brightness(self) -> int | None:
        """Return the brightness, 0-255."""
        dp = self._get_brightness_dp()
        if dp is None:
            return None
        return _percent_to_255(to_float(dp.get("value")))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the colour as 0-255 per channel."""
        channels = self._rgbw_channels()
        if channels:
            return tuple(  # type: ignore[return-value]
                _percent_to_255(to_float(channels[role].get("value"))) or 0
                for role in _RGB_ROLES
            )
        dp = self._get_rgb_dp()
        if dp is None:
            return None
        return _parse_hex_triplet(dp.get("value"))

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the colour and the white channel, 0-255 each."""
        channels = self._rgbw_channels()
        if ROLE_COLOR_WHITE not in channels:
            return None
        rgb = self.rgb_color or (0, 0, 0)
        white = _percent_to_255(to_float(channels[ROLE_COLOR_WHITE].get("value"))) or 0
        return (*rgb, white)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light, or set its brightness or colour."""
        if ATTR_RGBW_COLOR in kwargs:
            await self._write_color(kwargs[ATTR_RGBW_COLOR])
            return
        if ATTR_RGB_COLOR in kwargs:
            await self._write_color(kwargs[ATTR_RGB_COLOR])
            return

        br_dp = self._get_brightness_dp()
        if ATTR_BRIGHTNESS in kwargs and br_dp:
            await self.coordinator.async_write_datapoint(
                br_dp["id"], _255_to_percent(kwargs[ATTR_BRIGHTNESS])
            )
            return

        sw_dp = self._get_switch_dp()
        if sw_dp and sw_dp.get("writable"):
            await self.coordinator.async_write_datapoint(sw_dp["id"], "on")
        elif br_dp and br_dp.get("writable"):
            await self.coordinator.async_write_datapoint(br_dp["id"], 100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        sw_dp = self._get_switch_dp()
        if sw_dp and sw_dp.get("writable"):
            await self.coordinator.async_write_datapoint(sw_dp["id"], "off")
            return
        br_dp = self._get_brightness_dp()
        if br_dp and br_dp.get("writable"):
            await self.coordinator.async_write_datapoint(br_dp["id"], 0)
            return
        for dp in self._rgbw_channels().values():
            if dp.get("writable"):
                await self.coordinator.async_write_datapoint(dp["id"], 0)

    async def _write_color(self, color: tuple[int, ...]) -> None:
        """Write a colour to the per-channel datapoints, or to the hex triplet."""
        channels = self._rgbw_channels()
        if channels:
            roles = (*_RGB_ROLES, ROLE_COLOR_WHITE)
            for role, value in zip(roles, color, strict=False):
                dp = channels.get(role)
                if dp and dp.get("writable"):
                    await self.coordinator.async_write_datapoint(
                        dp["id"], _255_to_percent(value)
                    )
            return
        dp = self._get_rgb_dp()
        if dp and dp.get("writable"):
            await self.coordinator.async_write_datapoint(
                dp["id"], "".join(f"{channel:02X}" for channel in color[:3])
            )


def _parse_hex_triplet(value: Any) -> tuple[int, int, int] | None:
    """Return an `rgb-status` value as three 0-255 channels.

    The datapoint's unit is `3BHEX`; the value has only ever been observed as a
    six-digit hex string, so anything else is reported as no colour rather than
    guessed at.
    """
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        _LOGGER.debug("Ignoring unparseable RGB value %r", value)
        return None
