"""Cover platform for Wiser for KNX integration.

`fct.blindsVertical`, `fct.blindsHorizontal`, `fct.shadingRotary` and
`fct.blinds` (the SOMFY widgets). Measured datapoints, with the Touch slot each
one comes from:

| role | slot | datapoint | note |
|---|---|---|---|
| position | `height-position-status` | `dpt.scaling`, writable | 0 % = open |
| tilt | `slat-position-status` | `dpt.scaling`, writable | |
| move | `movement-object` | `dpt.upDown`, enum `down,up` | `up` = raw 0 |
| stop | `stop-object` | `dpt.step`, enum `increase,decrease` | `decrease` = raw 0 |
| moving | `moving` | `dpt.startStop`, read-only | diagnostic |
| direction | `last-direction` | `dpt.upDown`, read-only | diagnostic |

**Stop writes the member that puts a 0 on the bus**, which the enum above makes
`decrease`. Measured on a live `fct.blindsVertical` on 2026-11-22: writing
`increase` through the API put raw `01` on the stop group object and `decrease`
put raw `00`, and Schneider's own Touch widgets — `se-shutter-vertical`,
`se-shutter-horizontal` and `se-shutter-rotary` — all write literal `0` to that
slot from their stop button. So raw 0 is what the vendor's stop does, and
`decrease` is how this API spells raw 0. The member is looked up through
`enum_member_for_bit` rather than hard-coded, because a member encodes to its
DPT's bit and not to its position in the published list, and `STOP` is only
advertised when that lookup succeeds.

The write still goes to a datapoint whose value comes from the *status* object:
control and status collapse into one datapoint, measured here too — writing the
position datapoint drove the `height-position` group object while the value kept
coming from `height-position-status`.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import (
    ROLE_DIRECTION,
    ROLE_MOVE,
    ROLE_MOVING,
    ROLE_POSITION,
    ROLE_STOP,
    ROLE_TILT,
    enum_member_for_bit,
    to_float,
)
from .entity import WiserKnxBaseEntity, async_setup_plan_entities
from .plan import PLATFORM_COVER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX covers."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_COVER,
        lambda spec: WiserKnxCover(coordinator, entry.entry_id, spec["function_id"]),
        async_add_entities,
    )


def _ha_position(knx_percent: float | None) -> int | None:
    """Return a KNX height position as a Home Assistant cover position.

    KNX DPT 5.001 height position counts how far the shutter has travelled
    *down*: 0 % is fully up. Home Assistant counts how far it is *open*, so the
    two are inverses of each other.
    """
    if knx_percent is None:
        return None
    return int(min(100, max(0, 100 - knx_percent)))


class WiserKnxCover(WiserKnxBaseEntity, CoverEntity):
    """Representation of a Wiser for KNX shutter, blind or shade."""

    @property
    def _position_dp(self) -> dict[str, Any] | None:
        return self.role_datapoint(ROLE_POSITION)

    @property
    def _tilt_dp(self) -> dict[str, Any] | None:
        return self.role_datapoint(ROLE_TILT)

    def _stop_write(self) -> tuple[dict[str, Any], str] | None:
        """Return the stop datapoint and the member that stops it, or None.

        None means this cover must not advertise `STOP`: either it has no
        writable stop slot, or its enum holds no member whose bus value has been
        measured. Writing a guess would move the shutter instead of stopping it.
        """
        dp = self.role_datapoint(ROLE_STOP, writable=True)
        if dp is None:
            return None
        member = enum_member_for_bit(dp, 0)
        if member is None:
            return None
        return dp, member

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Return the features this cover's datapoints actually support."""
        features = CoverEntityFeature(0)
        if self.role_datapoint(ROLE_MOVE, writable=True):
            features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self._stop_write() is not None:
            features |= CoverEntityFeature.STOP
        position = self._position_dp
        if position and position.get("writable"):
            features |= CoverEntityFeature.SET_POSITION
            if not self.role_datapoint(ROLE_MOVE, writable=True):
                # Without a movement object, fully open and fully closed are
                # written as positions.
                features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        tilt = self._tilt_dp
        if tilt and tilt.get("writable"):
            features |= CoverEntityFeature.SET_TILT_POSITION
        return features

    @property
    def current_cover_position(self) -> int | None:
        """Return how far the cover is open, 0-100."""
        dp = self._position_dp
        if dp is None:
            return None
        return _ha_position(to_float(dp.get("value")))

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the slat position, 0-100."""
        dp = self._tilt_dp
        if dp is None:
            return None
        return _ha_position(to_float(dp.get("value")))

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is fully closed, or None if unknown.

        A cover with no position datapoint (a movement object only) cannot know:
        the controller publishes no state for it, and reporting "open" would be a
        guess that shows up as a wrong icon and a wrong automation condition.
        """
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool | None:
        """Return True while the cover reports movement upwards."""
        return self._moving_direction("up")

    @property
    def is_closing(self) -> bool | None:
        """Return True while the cover reports movement downwards."""
        return self._moving_direction("down")

    def _moving_direction(self, wanted: str) -> bool | None:
        """Return whether the cover is moving in `wanted`, if it reports both.

        `moving` says only that it is moving; `last-direction` says which way it
        went last. Both are needed, and both are optional slots.
        """
        moving = self.role_datapoint(ROLE_MOVING)
        if moving is None:
            return None
        if str(moving.get("value") or "").strip().casefold() != "start":
            return False
        direction = self.role_datapoint(ROLE_DIRECTION)
        if direction is None:
            return None
        return str(direction.get("value") or "").strip().casefold() == wanted

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if await self.async_write_role(ROLE_MOVE, "up"):
            return
        await self._write_position(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        if await self.async_write_role(ROLE_MOVE, "down"):
            return
        await self._write_position(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover, the way the controller's own stop button does."""
        stop = self._stop_write()
        if stop is None:
            return
        dp, member = stop
        await self.coordinator.async_write_datapoint(dp["id"], member)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a position."""
        position = kwargs.get("position")
        if position is not None:
            await self._write_position(int(position))

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the slats to a position."""
        position = kwargs.get("tilt_position")
        dp = self._tilt_dp
        if position is None or dp is None or not dp.get("writable"):
            return
        await self.coordinator.async_write_datapoint(dp["id"], 100 - int(position))

    async def _write_position(self, ha_position: int) -> None:
        dp = self._position_dp
        if dp is None or not dp.get("writable"):
            return
        await self.coordinator.async_write_datapoint(dp["id"], 100 - ha_position)
