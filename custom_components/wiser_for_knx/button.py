"""Button platform for Wiser for KNX: controller actions and KNX scenes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import (
    WiserKnxDatapointEntity,
    async_setup_plan_entities,
    controller_device_info,
)
from .plan import PLATFORM_BUTTON


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the controller buttons and one button per KNX scene."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WiserKnxBackupButton(coordinator, entry.entry_id),
            WiserKnxRescanButton(coordinator, entry.entry_id),
        ]
    )
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_BUTTON,
        lambda spec: WiserKnxSceneButton(coordinator, entry.entry_id, spec),
        async_add_entities,
    )


class WiserKnxSceneButton(WiserKnxDatapointEntity, ButtonEntity):
    """Recall a KNX scene by writing its number to the scene datapoint.

    A `se-scene` widget publishes one `dpt.sceneControl` datapoint whose enum
    lists the scene numbers configured in the widget, so there is one button per
    member. Writing a number that is not a member verbatim is accepted with
    HTTP 202 and then discarded, which is why the member is passed through
    unchanged.
    """

    _attr_icon = "mdi:palette-outline"

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        spec: dict[str, Any],
    ) -> None:
        """Initialize the scene button."""
        super().__init__(coordinator, entry_id, spec)
        self._value = spec["value"]
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{self.datapoint_id}_{self._value}"

    @property
    def name(self) -> str:
        """Return the entity name."""
        title = self.datapoint.get("title") or "Scene"
        return f"{title} {self._value}"

    async def async_press(self) -> None:
        """Recall the scene."""
        await self.coordinator.async_write_datapoint(self.datapoint_id, self._value)


class WiserKnxBackupButton(ButtonEntity):
    """Create a configuration backup of the controller."""

    _attr_has_entity_name = True
    _attr_name = "Create backup"
    _attr_icon = "mdi:cloud-download-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_create_backup"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_press(self) -> None:
        """Create a backup now."""
        await self._coordinator.backup_manager.async_create_backup()


class WiserKnxRescanButton(ButtonEntity):
    """Re-read locations and functions now instead of waiting for the hourly refresh."""

    _attr_has_entity_name = True
    _attr_name = "Rescan devices"
    _attr_icon = "mdi:magnify-scan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_rescan"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_press(self) -> None:
        """Refetch the controller's structure now."""
        await self._coordinator.async_refresh_structure()
