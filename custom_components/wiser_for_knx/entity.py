"""Base entity classes and the shared platform setup for Wiser for KNX."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import datapoint_role


def controller_device_info(
    coordinator: WiserKnxDataUpdateCoordinator, entry_id: str
) -> DeviceInfo:
    """Return device info for the controller itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=f"Wiser for KNX controller ({coordinator.client.host})",
        manufacturer="Schneider Electric",
        model="Wiser for KNX controller",
        configuration_url=coordinator.client.base_url,
    )


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
        """Return True if entity is available.

        A function without datapoints has nothing to read and no slot to write
        to. The controller publishes a function up to a few minutes before its
        datapoints after a configuration change (longer while several widgets are
        being edited), so this state is normal and resolves itself on a later
        poll; reporting it as unavailable is more honest than an entity that
        reads "off" and ignores every command.
        """
        return (
            super().available
            and self.coordinator.data is not None
            and self.function_id in self.coordinator.data.get("functions", {})
            and bool(self.function_data.get("datapoints"))
        )

    @property
    def room_name(self) -> str | None:
        """Return the room name of the function, if the controller knows one.

        `/locations` is a flat list - site, floors and rooms in one array, every
        `type` null - so there is no hierarchy to walk: the room title is used as
        the suggested area directly. When the function carries no usable location
        relationship, the name a datapoint reports is the same value.
        """
        loc_id = self.function_data.get("location_id")
        if loc_id and self.coordinator.data and "locations" in self.coordinator.data:
            loc = self.coordinator.data["locations"].get(loc_id)
            if loc and loc.get("title"):
                return loc["title"]
        for dp in (self.function_data.get("datapoints") or {}).values():
            if dp.get("parent_location_name"):
                return dp["parent_location_name"]
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information linking to function and room."""
        device_name = self.function_data.get("title") or f"Function {self.function_id}"
        room = self.room_name

        # The KNX function type is the most honest model name available: Touch
        # widget ids are not exposed by the API (`schneider:widgetId` is a hash).
        types = self.function_data.get("types") or []
        model = types[0].rsplit(":", 1)[-1] if types else "Wiser for KNX Device"

        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_{self.function_id}")},
            name=device_name,
            manufacturer="Schneider Electric",
            model=model,
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

    def datapoints_by_role(self) -> dict[str, dict[str, Any]]:
        """Return {role: datapoint} for this function, first datapoint per role.

        Several datapoints can share a role - a thermostat has up to six
        setpoints, a socket six power readings - and the composite entity uses
        the first in id order so the choice is stable across polls.
        """
        found: dict[str, dict[str, Any]] = {}
        types = self.function_data.get("types") or []
        for _dp_id, dp in sorted((self.function_data.get("datapoints") or {}).items()):
            role = datapoint_role(dp, types)
            if role and role not in found:
                found[role] = dp
        return found

    def role_datapoint(self, *roles: str, writable: bool = False):
        """Return the first datapoint matching one of `roles`, or None."""
        by_role = self.datapoints_by_role()
        for role in roles:
            dp = by_role.get(role)
            if dp is not None and (not writable or dp.get("writable")):
                return dp
        return None

    async def async_write_role(self, role: str, value: Any) -> bool:
        """Write a value to this function's datapoint for `role`."""
        dp = self.role_datapoint(role, writable=True)
        if dp is None:
            return False
        return await self.coordinator.async_write_datapoint(dp["id"], value)


class WiserKnxDatapointEntity(WiserKnxBaseEntity):
    """An entity for a single datapoint of a function.

    `datapoint.id` is stable across widget edits, group-address changes and
    renames (measured: the id stayed byte-identical while the API title followed
    the new name), which is what makes it usable as a unique id.
    """

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        spec: dict[str, Any],
    ) -> None:
        """Initialize the entity from a plan spec."""
        super().__init__(coordinator, entry_id, spec["function_id"])
        self.datapoint_id = spec["datapoint_id"]
        self.role = spec.get("role")
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{self.datapoint_id}"
        if spec.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def datapoint(self) -> dict[str, Any]:
        """Return the datapoint, or an empty dict while it is not published."""
        return (self.function_data.get("datapoints") or {}).get(self.datapoint_id) or {}

    @property
    def name(self) -> str | None:
        """Return the entity name.

        The datapoint title is the KNX group object's name, which the installer
        chose; it is the most specific label available, so it is used as the
        entity name under the function's device name.
        """
        return self.datapoint.get("title") or self.role or self.datapoint_id

    @property
    def available(self) -> bool:
        """Return True while the controller still publishes this datapoint."""
        return super().available and bool(self.datapoint)

    @property
    def native_value_raw(self) -> Any:
        """Return the datapoint's published value, unconverted."""
        return self.datapoint.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the datapoint identity next to the common attributes."""
        attrs = super().extra_state_attributes
        attrs["datapoint_id"] = self.datapoint_id
        attrs["datapoint_types"] = self.datapoint.get("types", [])
        if self.role:
            attrs["role"] = self.role
        return attrs


def async_setup_plan_entities(
    coordinator: WiserKnxDataUpdateCoordinator,
    entry: ConfigEntry,
    platform: str,
    factory: Callable[[dict[str, Any]], Any],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add this platform's entities, now and whenever the controller grows new ones.

    A function is published before its datapoints - measured at 2-13 s on a quiet
    controller and minutes while several widgets are being edited - so a platform
    that enumerates once at setup creates devices with no entities and misses
    everything an installer adds afterwards. Every platform therefore follows the
    plan the coordinator recomputes on each successful poll, and adds what is new.
    Nothing is ever removed here: a datapoint missing from one poll is "no new
    information", not a deletion (see the 500s on `/datapoints`).
    """
    known: set[str] = set()

    @callback
    def _sync() -> None:
        specs = coordinator.entity_plan.get(platform, [])
        fresh = [spec for spec in specs if spec["key"] not in known]
        if not fresh:
            return
        known.update(spec["key"] for spec in fresh)
        async_add_entities(_build(fresh, factory))

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


def _build(specs: Iterable[dict[str, Any]], factory) -> list[Any]:
    """Return the entities for `specs`, skipping any the factory declines."""
    entities = []
    for spec in specs:
        entity = factory(spec)
        if entity is not None:
            entities.append(entity)
    return entities
