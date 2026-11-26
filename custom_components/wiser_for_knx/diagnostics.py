"""Downloadable diagnostics for a Wiser for KNX config entry.

Settings -> Devices & services -> Wiser for KNX -> the three dots -> Download
diagnostics. This is the only way to see, from outside a running Home Assistant,
what an installation's export actually became: which functions turned into a
light or a climate, which fell through to loose datapoint entities, what every
datapoint's archetype and role are, and the entity id, name and state each one
ended up with.

Thin on purpose - the shaping and the redaction live in `diagnostics_utils.py`,
which has no Home Assistant imports and is unit-tested.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PUSH_STATUS_OFF
from .coordinator import WiserKnxDataUpdateCoordinator
from .diagnostics_utils import build_diagnostics


def _entities(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the registry rows for this entry, with each entity's current state.

    The registry is the authority on what exists: an entity that was created and
    then stopped being exported is still in it, which is exactly the case a
    screenshot of the device page cannot distinguish from a fresh one.
    """
    registry = er.async_get(hass)
    rows = []
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        state = hass.states.get(entity.entity_id)
        rows.append(
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "name": entity.name,
                "original_name": entity.original_name,
                "device_id": entity.device_id,
                "entity_category": _value(entity.entity_category),
                "disabled_by": _value(entity.disabled_by),
                "hidden_by": _value(entity.hidden_by),
                "state": state.state if state else None,
            }
        )
    return rows


def _devices(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the devices this entry owns: one controller plus one per function."""
    registry = dr.async_get(hass)
    return [
        {
            "id": device.id,
            "name": device.name_by_user or device.name,
            "model": device.model,
            "area_id": device.area_id,
            "via_device_id": device.via_device_id,
        }
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
    ]


def _value(enum_or_str: Any) -> Any:
    """Return an enum's value, or the value itself. Registry fields are both."""
    return getattr(enum_or_str, "value", enum_or_str)


def _controller(coordinator: WiserKnxDataUpdateCoordinator) -> dict[str, Any]:
    """Return the controller-side state: health, push, the poll and the backups."""
    push = coordinator.push
    manager = coordinator.backup_manager
    poll = {
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            int(coordinator.update_interval.total_seconds())
            if coordinator.update_interval
            else None
        ),
        # Consecutive 5xx answers. `/datapoints` 500s while the export is being
        # recomputed and permanently while a Danfoss thermostat widget has its
        # device status object set, which strands every entity until it answers.
        "consecutive_server_errors": coordinator.server_errors,
        "structure_age_seconds": coordinator.structure_age,
    }
    return {
        "health": dict(coordinator.health.data or {}) if coordinator.health else None,
        "push": {
            "status": push.status if push else PUSH_STATUS_OFF,
            **(push.diagnostics if push else {}),
        },
        "poll": poll,
        "backup": {
            "configured": bool(manager and manager.configured),
            "last_backup": (
                str(manager.last_backup) if manager and manager.last_backup else None
            ),
            "last_error": manager.last_error if manager else None,
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}
    return build_diagnostics(
        entry={
            "version": entry.version,
            "source": entry.source,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        controller=_controller(coordinator),
        functions=data.get("functions") or {},
        datapoints=data.get("datapoints") or {},
        plan=coordinator.entity_plan,
        entities=_entities(hass, entry),
        devices=_devices(hass, entry),
    )
