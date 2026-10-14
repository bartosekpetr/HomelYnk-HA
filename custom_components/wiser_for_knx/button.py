"""Button platform for Wiser for KNX (controller maintenance actions)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import controller_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the controller buttons."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WiserKnxBackupButton(coordinator, entry.entry_id)])


class WiserKnxBackupButton(ButtonEntity):
    """Create a configuration backup of the controller."""

    _attr_has_entity_name = True
    _attr_name = "Create backup"
    _attr_icon = "mdi:cloud-download-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_create_backup"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_press(self) -> None:
        """Create a backup now."""
        await self._coordinator.backup_manager.async_create_backup()
