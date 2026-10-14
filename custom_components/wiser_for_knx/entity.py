"""Base entity class for Wiser for KNX entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator


class WiserKnxBaseEntity(CoordinatorEntity[WiserKnxDataUpdateCoordinator]):
    """Base representation of an entity associated with a Wiser for KNX function."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        function_id: str,
    ) -> None:
        """Initialize base entity."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.function_id = function_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{function_id}"

    @property
    def function_data(self) -> dict[str, Any]:
        """Return the function dictionary from coordinator data."""
        if self.coordinator.data and "functions" in self.coordinator.data:
            return self.coordinator.data["functions"].get(self.function_id, {})
        return {}

    @property
    def name(self) -> str | None:
        """Return name of the entity."""
        return self.function_data.get("title") or f"Function {self.function_id}"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.function_id in self.coordinator.data.get("functions", {})
        )

    @property
    def room_name(self) -> str | None:
        """Return room/location name if available."""
        loc_id = self.function_data.get("location_id")
        if loc_id and self.coordinator.data and "locations" in self.coordinator.data:
            loc = self.coordinator.data["locations"].get(loc_id)
            if loc:
                return loc.get("title")
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information linking to function and room."""
        host = self.coordinator.client.host
        device_name = self.function_data.get("title") or f"Function {self.function_id}"
        room = self.room_name

        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{self.function_id}")},
            name=device_name,
            manufacturer="Schneider Electric",
            model="Wiser for KNX Device",
            via_device=(DOMAIN, self.entry_id),
            configuration_url=self.coordinator.client.base_url,
        )

        if room:
            info["suggested_area"] = room

        return info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return common state attributes."""
        attrs = {
            "function_id": self.function_id,
            "function_types": self.function_data.get("types", []),
        }
        if self.room_name:
            attrs["room"] = self.room_name
        return attrs
