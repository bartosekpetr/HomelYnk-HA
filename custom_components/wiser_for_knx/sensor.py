"""Sensor platform for Wiser for KNX integration.

Three groups of sensor:

* **datapoint sensors** - every readable datapoint a richer entity did not
  consume: temperatures, humidity, CO2 and the other air-quality readings,
  illuminance, wind speed, a socket's active power, battery levels, a valve
  drive's heating demand, a lock's state, a gauge's raw value.
* **controller health** - firmware, uptime, load, memory and storage from the
  management API.
* **the backup sensor** - when the last controller backup succeeded.

Units and device classes are chosen from the datapoint's role, never from the
unit string the controller sends: its degrees are `C`, its micrograms use a
Greek mu, and `dpt.valueLux` carries no unit at all.
"""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    PUSH_STATUS_DEGRADED,
    PUSH_STATUS_FAILED,
    PUSH_STATUS_LIVE,
    PUSH_STATUS_OFF,
    PUSH_STATUS_PENDING,
)
from .coordinator import WiserKnxDataUpdateCoordinator, WiserKnxHealthCoordinator
from .datapoints import (
    ROLE_BATTERY_LEVEL,
    ROLE_CO,
    ROLE_CO2,
    ROLE_DIRECTION,
    ROLE_DOOR_STATE,
    ROLE_FAN_PERCENT,
    ROLE_FORMALDEHYDE,
    ROLE_HEAT_COOL,
    ROLE_HEATING_DEMAND,
    ROLE_HUMIDITY,
    ROLE_HVAC_MODE,
    ROLE_ILLUMINANCE,
    ROLE_LOCK_STATE,
    ROLE_NO2,
    ROLE_OCCUPANCY_MODE,
    ROLE_OZONE,
    ROLE_PM1,
    ROLE_PM5,
    ROLE_PM10,
    ROLE_PM25,
    ROLE_POWER,
    ROLE_SETPOINT,
    ROLE_SYSTEM_MODE,
    ROLE_TEMPERATURE,
    ROLE_TEMPERATURE_OUTDOOR,
    ROLE_TVOC,
    ROLE_TVOC_INDEX,
    ROLE_WIND_SPEED,
    temperature_in,
    to_float,
)
from .entity import (
    WiserKnxDatapointEntity,
    async_setup_plan_entities,
    controller_device_info,
)
from .plan import PLATFORM_SENSOR

HealthSensorDescription = SensorEntityDescription

HEALTH_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="firmware", name="Firmware version"),
    SensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="load_1m",
        name="CPU load (1 min)",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="load_5m",
        name="CPU load (5 min)",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="load_15m",
        name="CPU load (15 min)",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="memory_used_percent",
        name="Memory used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="storage_used_percent",
        name="Storage used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

# role -> (device class, unit, state class). A role that is not in here becomes a
# plain sensor reporting the published string, which is always safe.
_NUMERIC_ROLES: dict[str, tuple[SensorDeviceClass | None, str | None]] = {
    ROLE_TEMPERATURE: (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ROLE_TEMPERATURE_OUTDOOR: (
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
    ),
    ROLE_SETPOINT: (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ROLE_HUMIDITY: (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    ROLE_CO2: (SensorDeviceClass.CO2, CONCENTRATION_PARTS_PER_MILLION),
    ROLE_CO: (SensorDeviceClass.CO, CONCENTRATION_PARTS_PER_MILLION),
    # NO2, ozone and TVOC are published in ppm; Home Assistant's device classes
    # for them are defined in ug/m3, so they are reported without one. The
    # controller's own factor of 1000 on `fct.gasSensor` concentrations is
    # measured but unexplained, so the value is passed through untouched.
    ROLE_NO2: (None, CONCENTRATION_PARTS_PER_MILLION),
    ROLE_OZONE: (None, CONCENTRATION_PARTS_PER_MILLION),
    ROLE_TVOC: (None, CONCENTRATION_PARTS_PER_MILLION),
    ROLE_TVOC_INDEX: (None, None),
    ROLE_FORMALDEHYDE: (None, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ROLE_PM1: (SensorDeviceClass.PM1, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ROLE_PM25: (SensorDeviceClass.PM25, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ROLE_PM5: (None, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ROLE_PM10: (SensorDeviceClass.PM10, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ROLE_ILLUMINANCE: (SensorDeviceClass.ILLUMINANCE, LIGHT_LUX),
    ROLE_WIND_SPEED: (
        SensorDeviceClass.WIND_SPEED,
        UnitOfSpeed.METERS_PER_SECOND,
    ),
    ROLE_POWER: (SensorDeviceClass.POWER, UnitOfPower.WATT),
    ROLE_BATTERY_LEVEL: (SensorDeviceClass.BATTERY, PERCENTAGE),
    ROLE_HEATING_DEMAND: (None, PERCENTAGE),
    ROLE_FAN_PERCENT: (None, PERCENTAGE),
}

# Roles whose value is one of a published set of names
_ENUM_ROLES = frozenset(
    {
        ROLE_DIRECTION,
        ROLE_LOCK_STATE,
        ROLE_DOOR_STATE,
        ROLE_HVAC_MODE,
        ROLE_HEAT_COOL,
        ROLE_SYSTEM_MODE,
        ROLE_OCCUPANCY_MODE,
    }
)

_TEMPERATURE_ROLES = (ROLE_TEMPERATURE, ROLE_TEMPERATURE_OUTDOOR, ROLE_SETPOINT)


class WiserKnxDatapointSensor(WiserKnxDatapointEntity, SensorEntity):
    """A readable datapoint of a Wiser for KNX function."""

    @property
    def _numeric(self) -> tuple[SensorDeviceClass | None, str | None] | None:
        return _NUMERIC_ROLES.get(self.role or "")

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class for this datapoint's role."""
        numeric = self._numeric
        if numeric:
            return numeric[0]
        if self.role in _ENUM_ROLES:
            return SensorDeviceClass.ENUM
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit for this datapoint's role.

        The controller's own unit string is not used: it reports `C` for degrees
        and a Greek mu for micrograms, neither of which Home Assistant accepts,
        and it leaves `dpt.valueLux` with no unit at all.
        """
        numeric = self._numeric
        return numeric[1] if numeric else None

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return MEASUREMENT for the numeric roles, nothing for the rest."""
        return SensorStateClass.MEASUREMENT if self._numeric else None

    @property
    def options(self) -> list[str] | None:
        """Return the published enum members for an enum sensor."""
        if self.role not in _ENUM_ROLES:
            return None
        return [str(member) for member in (self.datapoint.get("enum") or [])] or None

    @property
    def native_value(self) -> Any:
        """Return the value, parsed for the numeric roles.

        Values arrive as strings and already in engineering units, so they are
        parsed and never rescaled. A number that will not parse is reported as
        unknown rather than as text, which a numeric device class would reject.
        """
        value = self.native_value_raw
        if self.role in _TEMPERATURE_ROLES:
            return temperature_in(self.function_data.get("types"), self.role, value)
        if self._numeric:
            return to_float(value)
        if value is None or value == "":
            return None
        return str(value)


class WiserKnxLastBackupSensor(SensorEntity):
    """Time of the last successful controller backup."""

    _attr_has_entity_name = True
    _attr_name = "Last backup"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the sensor."""
        self._manager = coordinator.backup_manager
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_last_backup"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_added_to_hass(self) -> None:
        """Refresh the state whenever a backup finishes."""
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    @property
    def native_value(self):
        """Return the time of the last backup."""
        return self._manager.last_backup

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return backup details."""
        attrs: dict[str, Any] = {
            "scheduled": self._manager.interval_hours > 0 and self._manager.configured,
            "keep": self._manager.keep,
        }
        if self._manager.last_files:
            attrs["files"] = self._manager.last_files
        if self._manager.last_error:
            attrs["last_error"] = self._manager.last_error
        return attrs


class WiserKnxPushSensor(SensorEntity):
    """Whether the controller is really delivering datapoint callbacks.

    This exists because the controller gives nothing away: with its delivery
    daemon dead the subscription stays listed and every endpoint keeps answering
    200, so "push silently stopped and we are back to polling" would otherwise
    be invisible. `live` means callbacks are arriving and the poll has slowed to
    its backstop; `pending` means subscribed but nothing delivered yet;
    `degraded` means a poll caught values no callback reported; `failed`
    means it could not be set up at all - and all three of those poll at the
    configured interval, exactly as the integration did before push existed.

    None of those values may be one of Home Assistant's own reserved state
    strings, and `failed` is named that way because it once was not: it read
    `unavailable` through v0.9.0, which is also how Home Assistant renders an
    entity it is not being given a state for. The two look identical in the UI
    and in a screenshot, and they call for opposite responses - so the one state
    that says "look at the reason attribute" was the one state whose attributes
    a reader could not trust. `tests/test_platform_entities.py` pins this.
    """

    _attr_has_entity_name = True
    _attr_name = "Push"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        PUSH_STATUS_OFF,
        PUSH_STATUS_FAILED,
        PUSH_STATUS_PENDING,
        PUSH_STATUS_LIVE,
        PUSH_STATUS_DEGRADED,
    ]
    _attr_should_poll = False

    def __init__(
        self, coordinator: WiserKnxDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the sensor."""
        self._push = coordinator.push
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_push"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    async def async_added_to_hass(self) -> None:
        """Refresh whenever the push state changes."""
        self.async_on_remove(self._push.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        """Return the push status."""
        return self._push.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the callback counters. Never the signing secret."""
        return self._push.diagnostics


class WiserKnxHealthSensor(CoordinatorEntity[WiserKnxHealthCoordinator], SensorEntity):
    """A diagnostic value read from the controller's management API."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: WiserKnxHealthCoordinator,
        main: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        description: HealthSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = controller_device_info(main, entry_id)

    @property
    def native_value(self):
        """Return the current value."""
        return (self.coordinator.data or {}).get(self.entity_description.key)


class WiserKnxExportSensor(
    CoordinatorEntity[WiserKnxDataUpdateCoordinator], SensorEntity
):
    """How much of the installation the controller is currently exporting.

    Worth watching: a widget whose "Disable API Export" setting is set, or a
    channel missing its status feedback object, is simply absent from the API -
    there is nothing in the function graph that says so. A count that drops is
    the only in-band signal that something stopped being exported.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: WiserKnxDataUpdateCoordinator,
        entry_id: str,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{key}"
        self._attr_device_info = controller_device_info(coordinator, entry_id)

    @property
    def native_value(self) -> int | None:
        """Return the number of exported functions or datapoints."""
        data = self.coordinator.data
        if not data:
            return None
        return len(data.get(self._key) or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the writable share, which is what can be controlled."""
        data = self.coordinator.data or {}
        if self._key != "datapoints":
            return {}
        datapoints = data.get("datapoints") or {}
        return {
            "writable": sum(1 for dp in datapoints.values() if dp.get("writable")),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Wiser for KNX sensors."""
    coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        WiserKnxLastBackupSensor(coordinator, entry.entry_id),
        WiserKnxExportSensor(
            coordinator, entry.entry_id, "functions", "Exported functions"
        ),
        WiserKnxExportSensor(
            coordinator, entry.entry_id, "datapoints", "Exported datapoints"
        ),
    ]
    if coordinator.push is not None:
        entities.append(WiserKnxPushSensor(coordinator, entry.entry_id))
    if coordinator.health is not None:
        entities.extend(
            WiserKnxHealthSensor(coordinator.health, coordinator, entry.entry_id, desc)
            for desc in HEALTH_SENSORS
        )
    async_add_entities(entities)

    async_setup_plan_entities(
        coordinator,
        entry,
        PLATFORM_SENSOR,
        lambda spec: WiserKnxDatapointSensor(coordinator, entry.entry_id, spec),
        async_add_entities,
    )
