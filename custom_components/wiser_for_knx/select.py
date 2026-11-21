"""Select platform for Wiser for KNX integration.

Every writable datapoint that publishes an `enum` and is not already part of a
richer entity: a thermostat's heating/cooling changeover, an SE8000 or Airzone
system mode, an occupancy mode, a shutter's stop object, a fan mode on a
function that is not a thermostat.

The options are the controller's own enum members, **verbatim**. That is not
cosmetic: a value that is not a member exactly as published is accepted with
HTTP 202 and then silently discarded, so `on` writes a telegram where `1` and
`true` write nothing at all.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import WiserKnxDatapointEntity, async_setup_plan_entities
from .plan import PLATFORM_SELECT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX selects."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_SELECT,
        lambda spec: WiserKnxSelect(coordinator, entry.entry_id, spec),
        async_add_entities,
    )


class WiserKnxSelect(WiserKnxDatapointEntity, SelectEntity):
    """A writable enum datapoint of a Wiser for KNX function."""

    @property
    def options(self) -> list[str]:
        """Return the datapoint's published enum members."""
        return [str(member) for member in (self.datapoint.get("enum") or [])]

    @property
    def current_option(self) -> str | None:
        """Return the current value, if it is one of the published members."""
        value = self.datapoint.get("value")
        if value is None:
            return None
        value = str(value)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Write the selected member."""
        await self.coordinator.async_write_datapoint(self.datapoint_id, option)
