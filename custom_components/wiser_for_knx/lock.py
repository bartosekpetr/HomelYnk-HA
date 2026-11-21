"""Lock platform for Wiser for KNX integration.

`fct.smartLock` publishes three datapoints that matter: `dpt.doorControl`
(writable, enum `lock,unlock`), `dpt.lockState` (`ajar,locked,unlocked`) and
`dpt.doorState` (`open,closed,jammed,forced,unspecified`). The lock state is
the one that says whether it is locked; the door state becomes its own sensor.

Control and status collapse into one datapoint on this controller, and a write
drives the control object - so the state follows only when the lock itself
reports back. Nothing here waits for that: the state is taken from the lock
state datapoint whenever it publishes one.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import ROLE_DOOR_STATE, ROLE_LOCK_CONTROL, ROLE_LOCK_STATE
from .entity import WiserKnxBaseEntity, async_setup_plan_entities
from .plan import PLATFORM_LOCK


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX locks."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_LOCK,
        lambda spec: WiserKnxLock(coordinator, entry.entry_id, spec["function_id"]),
        async_add_entities,
    )


class WiserKnxLock(WiserKnxBaseEntity, LockEntity):
    """Representation of a Wiser for KNX smart lock."""

    def _state(self) -> str | None:
        for role in (ROLE_LOCK_STATE, ROLE_LOCK_CONTROL):
            dp = self.role_datapoint(role)
            if dp and dp.get("value") is not None:
                return str(dp["value"]).strip().casefold()
        return None

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock reports itself locked."""
        state = self._state()
        if state is None:
            return None
        if state in ("locked", "lock"):
            return True
        if state in ("unlocked", "unlock"):
            return False
        return None  # `ajar` is neither locked nor unlocked

    @property
    def is_jammed(self) -> bool:
        """Return True if the door reports itself jammed."""
        dp = self.role_datapoint(ROLE_DOOR_STATE)
        return str((dp or {}).get("value") or "").strip().casefold() == "jammed"

    @property
    def is_open(self) -> bool:
        """Return True if the door reports itself ajar or open."""
        if self._state() == "ajar":
            return True
        dp = self.role_datapoint(ROLE_DOOR_STATE)
        return str((dp or {}).get("value") or "").strip().casefold() == "open"

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        await self.async_write_role(ROLE_LOCK_CONTROL, "lock")

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        await self.async_write_role(ROLE_LOCK_CONTROL, "unlock")
