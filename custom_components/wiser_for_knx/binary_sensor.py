"""Binary sensor platform for Wiser for KNX integration.

One entity per datapoint that reports an on/off state: the alarm objects of the
alarm widgets, a window/door contact, motion detection, the rain and threshold
flags of a weather station, low-battery alerts, and the `dpt.deviceStatus`
diagnostic every widget can publish.

The device class comes from the datapoint's **role** (its `dic:dpa.*`
archetype), not from its title: titles are user-defined KNX group object names.
Only the general alarm object has to fall back to the function, because one
archetype serves fire, gas, water and the general alarm alike.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WiserKnxDataUpdateCoordinator
from .datapoints import (
    ROLE_ALARM,
    ROLE_BATTERY_LOW,
    ROLE_DEVICE_STATUS,
    ROLE_DEW_POINT_ALARM,
    ROLE_FAILURE,
    ROLE_MOTION,
    ROLE_MOVING,
    ROLE_OPEN_CLOSE,
    ROLE_RAIN,
    ROLE_TEMP_ALARM,
    ROLE_WIND_ALARM,
    binary_state,
)
from .entity import WiserKnxDatapointEntity, async_setup_plan_entities
from .plan import PLATFORM_BINARY_SENSOR
from .widgets import binary_device_class

_ROLE_CLASSES = {
    ROLE_RAIN: BinarySensorDeviceClass.MOISTURE,
    ROLE_WIND_ALARM: BinarySensorDeviceClass.PROBLEM,
    ROLE_TEMP_ALARM: BinarySensorDeviceClass.HEAT,
    ROLE_DEW_POINT_ALARM: BinarySensorDeviceClass.PROBLEM,
    ROLE_FAILURE: BinarySensorDeviceClass.PROBLEM,
    ROLE_BATTERY_LOW: BinarySensorDeviceClass.BATTERY,
    ROLE_MOTION: BinarySensorDeviceClass.MOTION,
    ROLE_DEVICE_STATUS: BinarySensorDeviceClass.CONNECTIVITY,
    ROLE_MOVING: BinarySensorDeviceClass.RUNNING,
}

# The alarm and contact archetypes are shared across widget types, so what kind of
# alarm or opening it is can only come from the function.
_FUNCTION_CLASSES = {
    "MOISTURE": BinarySensorDeviceClass.MOISTURE,
    "SMOKE": BinarySensorDeviceClass.SMOKE,
    "GAS": BinarySensorDeviceClass.GAS,
    "MOTION": BinarySensorDeviceClass.MOTION,
    "WINDOW": BinarySensorDeviceClass.WINDOW,
    "DOOR": BinarySensorDeviceClass.DOOR,
    "SAFETY": BinarySensorDeviceClass.SAFETY,
}
_OPENING_CLASSES = (
    BinarySensorDeviceClass.DOOR,
    BinarySensorDeviceClass.WINDOW,
    BinarySensorDeviceClass.OPENING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wiser for KNX binary sensors."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_BINARY_SENSOR,
        lambda spec: WiserKnxBinarySensor(coordinator, entry.entry_id, spec),
        async_add_entities,
    )


class WiserKnxBinarySensor(WiserKnxDatapointEntity, BinarySensorEntity):
    """An on/off datapoint of a Wiser for KNX function."""

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class for this datapoint's role."""
        if self.role in (ROLE_ALARM, ROLE_OPEN_CLOSE):
            name = binary_device_class(self.function_data)
            device_class = _FUNCTION_CLASSES.get(name or "")
            if self.role == ROLE_OPEN_CLOSE and device_class not in _OPENING_CLASSES:
                return BinarySensorDeviceClass.OPENING
            return device_class or BinarySensorDeviceClass.PROBLEM
        return _ROLE_CLASSES.get(self.role or "")

    @property
    def is_on(self) -> bool | None:
        """Return the state, or None while the controller reports no value.

        A `dpt.deviceStatus` is `online`/`offline` and a detection object
        `start`/`stop`, so the published token is mapped rather than compared
        with "on".
        """
        return binary_state(self.native_value_raw)
