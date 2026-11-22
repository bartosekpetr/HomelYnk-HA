"""What a datapoint *is*, decided from the controller's own type tags.

A datapoint's ``meta["@type"]`` carries two tags: a `dic:dpa.<archetype>` and a
`urn:knx:dpt.<type>`. The archetype is the useful one — it identifies the Touch
widget **slot** the datapoint came from, which the API does not otherwise
expose. Measured over every app-exportable widget type (47 types, built three
ways each, in the wiser-knx-skillset `widget-api-matrix.json`), the mapping is
one-to-one in the direction that matters here:

    dic:dpa.800.65   -> shutter height position     dic:dpa.65533.51 -> battery level
    dic:dpa.800.66   -> shutter slat position       dic:dpa.65533.52 -> low battery
    dic:dpa.399.56   -> current temperature         dic:dpa.901.51   -> active power
    dic:dpa.392.52+  -> setpoint                    dic:dpa.812.51   -> device status

That is why nothing in this module looks at a datapoint's title: titles are
user-defined KNX group object names (the installer's own language), so they are
display text, never a key. The datapoint type is the fallback when an archetype
has not been measured, and a role of ``None`` is a valid answer.

Pure module: no Home Assistant imports, so it stays unit-testable.
"""

from __future__ import annotations

from typing import Any

# --- roles -----------------------------------------------------------------

ROLE_SWITCH = "switch"
ROLE_SWITCH_FEEDBACK = "switch_feedback"
ROLE_BRIGHTNESS = "brightness"
ROLE_COLOR_RGB = "color_rgb"
ROLE_COLOR_RED = "color_red"
ROLE_COLOR_GREEN = "color_green"
ROLE_COLOR_BLUE = "color_blue"
ROLE_COLOR_WHITE = "color_white"
ROLE_POSITION = "position"
ROLE_TILT = "tilt"
ROLE_MOVE = "move"
ROLE_STOP = "stop"
ROLE_MOVING = "moving"
ROLE_DIRECTION = "direction"
ROLE_TEMPERATURE = "temperature"
ROLE_TEMPERATURE_OUTDOOR = "temperature_outdoor"
ROLE_SETPOINT = "setpoint"
ROLE_SETPOINT_SHIFT = "setpoint_shift"
ROLE_HVAC_MODE = "hvac_mode"
ROLE_HEAT_COOL = "heat_cool"
ROLE_SYSTEM_MODE = "system_mode"
ROLE_FAN_PERCENT = "fan_percent"
ROLE_FAN_MODE = "fan_mode"
ROLE_FAN_SEQUENCE = "fan_sequence"
ROLE_OCCUPANCY_MODE = "occupancy_mode"
ROLE_HEATING_DEMAND = "heating_demand"
ROLE_BATTERY_LEVEL = "battery_level"
ROLE_BATTERY_LOW = "battery_low"
ROLE_HUMIDITY = "humidity"
ROLE_CO2 = "co2"
ROLE_CO = "co"
ROLE_NO2 = "no2"
ROLE_OZONE = "ozone"
ROLE_TVOC = "tvoc"
ROLE_TVOC_INDEX = "tvoc_index"
ROLE_FORMALDEHYDE = "formaldehyde"
ROLE_PM1 = "pm1"
ROLE_PM25 = "pm25"
ROLE_PM5 = "pm5"
ROLE_PM10 = "pm10"
ROLE_ILLUMINANCE = "illuminance"
ROLE_MOTION = "motion"
ROLE_OPEN_CLOSE = "open_close"
ROLE_LOCK_CONTROL = "lock_control"
ROLE_LOCK_STATE = "lock_state"
ROLE_DOOR_STATE = "door_state"
ROLE_DEVICE_STATUS = "device_status"
ROLE_WIND_SPEED = "wind_speed"
ROLE_POWER = "power"
ROLE_ALARM = "alarm"
ROLE_RAIN = "rain"
ROLE_WIND_ALARM = "wind_alarm"
ROLE_TEMP_ALARM = "temp_alarm"
ROLE_DEW_POINT_ALARM = "dew_point_alarm"
ROLE_FAILURE = "failure"
ROLE_SCENE = "scene"
ROLE_VALUE = "value"
ROLE_TRIGGER = "trigger"

# Archetype -> role. Every row was measured; the comment is the Touch slot it came from.
DPA_ROLES: dict[str, str] = {
    "dic:dpa.417.69": ROLE_SWITCH,  # switch-object-status (RGB/RGBW)
    "dic:dpa.417.70": ROLE_SWITCH,  # object-status-N, switch-status, fan-manual-mode
    # The thermostat's own on/off. Kept apart from 417.70 because a thermostat
    # publishes both - 417.70 is its fan manual mode - and picking the wrong one
    # would turn the fan off when Home Assistant asked for the thermostat.
    "dic:dpa.417.72": ROLE_SWITCH_FEEDBACK,  # thermostat-switch-status, switch-feedback
    "dic:dpa.418.61": ROLE_SWITCH,  # switch-object-status-N (dimmer)
    "dic:dpa.427.71": ROLE_SWITCH,  # object-status-1 (AC/fan switch)
    "dic:dpa.418.63": ROLE_BRIGHTNESS,  # value-object-status-N (dimmer)
    "dic:dpa.423.52": ROLE_COLOR_RGB,  # rgb-status
    "dic:dpa.423.58": ROLE_COLOR_RED,  # red-value-object-status
    "dic:dpa.423.61": ROLE_COLOR_GREEN,  # green-value-object-status
    "dic:dpa.423.64": ROLE_COLOR_BLUE,  # blue-value-object-status
    "dic:dpa.424.67": ROLE_COLOR_WHITE,  # white-value-object-status
    "dic:dpa.800.65": ROLE_POSITION,  # height-position-status
    "dic:dpa.800.66": ROLE_TILT,  # slat-position-status
    "dic:dpa.801.61": ROLE_MOVE,  # movement-object
    "dic:dpa.801.62": ROLE_STOP,  # stop-object
    "dic:dpa.801.90": ROLE_MOVING,  # moving
    "dic:dpa.801.91": ROLE_DIRECTION,  # last-direction
    "dic:dpa.320.51": ROLE_TEMPERATURE,  # temperature-value (weather, multi sensor)
    "dic:dpa.399.56": ROLE_TEMPERATURE,  # temperature, indoor-temperature
    "dic:dpa.399.57": ROLE_TEMPERATURE_OUTDOOR,  # outdoor-temperature
    "dic:dpa.392.52": ROLE_SETPOINT,  # setpoint-status, scale-status, occupied heat
    "dic:dpa.392.53": ROLE_SETPOINT,  # setpoint-unoccupied-heat
    "dic:dpa.392.54": ROLE_SETPOINT,  # setpoint-standby-heat
    "dic:dpa.392.55": ROLE_SETPOINT,  # setpoint-occupied-cool
    "dic:dpa.392.56": ROLE_SETPOINT,  # setpoint-unoccupied-cool
    "dic:dpa.392.57": ROLE_SETPOINT,  # setpoint-standby-cool
    "dic:dpa.399.113": ROLE_SETPOINT_SHIFT,  # current-setpoint-shifting
    "dic:dpa.399.50": ROLE_HVAC_MODE,  # hvac-status
    "dic:dpa.399.51": ROLE_HEAT_COOL,  # system-mode
    "dic:dpa.399.53": ROLE_SYSTEM_MODE,  # system-mode-feedback (airzone)
    "dic:dpa.399.64": ROLE_HEAT_COOL,  # heating-cooling-status, rtc-status
    "dic:dpa.399.65": ROLE_HEATING_DEMAND,  # object-itrv-heating-demand-N
    "dic:dpa.399.74": ROLE_FAN_PERCENT,  # fan-speed-status
    "dic:dpa.399.75": ROLE_FAN_MODE,  # fan-mode (SE8000)
    "dic:dpa.399.77": ROLE_FAN_MODE,  # fan-mode-feedback (airzone)
    "dic:dpa.417.71": ROLE_OCCUPANCY_MODE,  # occupancy, occupancy-status
    "dic:dpa.65533.51": ROLE_BATTERY_LEVEL,  # battery-level, object-itrv-battery-N
    "dic:dpa.65533.52": ROLE_BATTERY_LOW,  # battery-alert, object-battery-low
    "dic:dpa.337.51": ROLE_HUMIDITY,  # humidity-value
    "dic:dpa.65534.51": ROLE_CO2,  # co2-value
    "dic:dpa.65534.52": ROLE_PM1,  # 1um
    "dic:dpa.65534.53": ROLE_PM25,  # 2_5um
    "dic:dpa.65534.54": ROLE_PM5,  # 5um
    "dic:dpa.65534.55": ROLE_PM10,  # 10um
    "dic:dpa.65534.56": ROLE_TVOC,  # tvoc
    "dic:dpa.65534.57": ROLE_FORMALDEHYDE,  # formaldehyde
    "dic:dpa.65534.58": ROLE_CO,  # co
    "dic:dpa.65534.59": ROLE_NO2,  # no2
    "dic:dpa.65534.60": ROLE_OZONE,  # ozone
    "dic:dpa.65534.61": ROLE_TVOC_INDEX,  # tvoc-index
    "dic:dpa.414.62": ROLE_ILLUMINANCE,  # object-illuminance
    "dic:dpa.414.63": ROLE_MOTION,  # object-detection (motion)
    "dic:dpa.811.51": ROLE_OPEN_CLOSE,  # object-detection (window/door)
    "dic:dpa.811.52": ROLE_LOCK_CONTROL,  # door-control
    "dic:dpa.811.53": ROLE_LOCK_STATE,  # lock-state
    "dic:dpa.811.54": ROLE_DOOR_STATE,  # door-state
    "dic:dpa.812.51": ROLE_DEVICE_STATUS,  # object-device-status
    "dic:dpa.900.52": ROLE_WIND_SPEED,  # wind-speed
    "dic:dpa.901.51": ROLE_POWER,  # object-power-N
    "dic:dpa.802.51": ROLE_WIND_ALARM,  # wind-threshold
    "dic:dpa.803.51": ROLE_RAIN,  # rain-sensor
    "dic:dpa.804.51": ROLE_ALARM,  # alarm-object (fire)
    "dic:dpa.805.51": ROLE_ALARM,  # alarm-object (gas)
    "dic:dpa.806.51": ROLE_ALARM,  # alarm-object (water)
    "dic:dpa.807.51": ROLE_TEMP_ALARM,  # temp-alarm-object, temperature-threshold
    "dic:dpa.808.51": ROLE_FAILURE,  # failure-status
    "dic:dpa.810.51": ROLE_ALARM,  # alarm-object (general)
    "dic:dpa.344.51": ROLE_DEW_POINT_ALARM,  # dev-point-alarm-status
    "dic:dpa.1010.54": ROLE_SCENE,  # scene
    "dic:dpa.417.65": ROLE_VALUE,  # gauge-object, info text
}

# Datapoint type -> role, used when the archetype is unknown (a firmware the matrix
# has not seen). Deliberately coarse: a wrong guess here must still be harmless.
DPT_ROLES: dict[str, str] = {
    "urn:knx:dpt.switch": ROLE_SWITCH,
    "urn:knx:dpt.scaling": ROLE_BRIGHTNESS,
    "urn:knx:dpt.R-G-B": ROLE_COLOR_RGB,
    "urn:knx:dpt.upDown": ROLE_MOVE,
    "urn:knx:dpt.step": ROLE_STOP,
    "urn:knx:dpt.startStop": ROLE_MOVING,
    "urn:knx:dpt.valueTemp": ROLE_TEMPERATURE,
    "urn:knx:dpt.valueTempShift": ROLE_SETPOINT_SHIFT,
    "urn:knx:dpt.hvacOperationMode": ROLE_HVAC_MODE,
    "urn:knx:dpt.heatCool": ROLE_HEAT_COOL,
    "urn:knx:dpt.se8000Mode": ROLE_SYSTEM_MODE,
    "urn:knx:dpt.airzoneMode": ROLE_SYSTEM_MODE,
    "urn:knx:dpt.se8000Fan": ROLE_FAN_MODE,
    "urn:knx:dpt.airzoneFan": ROLE_FAN_MODE,
    "urn:knx:dpt.se8000FanSequence": ROLE_FAN_SEQUENCE,
    "urn:knx:dpt.occupancyMode": ROLE_OCCUPANCY_MODE,
    "urn:knx:dpt.humidity": ROLE_HUMIDITY,
    "urn:knx:dpt.airQuality": ROLE_CO2,
    "urn:knx:dpt.airQualityDensity": ROLE_PM25,
    "urn:knx:dpt.tvocIndex": ROLE_TVOC_INDEX,
    "urn:knx:dpt.valueLux": ROLE_ILLUMINANCE,
    "urn:knx:dpt.openClose": ROLE_OPEN_CLOSE,
    "urn:knx:dpt.doorControl": ROLE_LOCK_CONTROL,
    "urn:knx:dpt.lockState": ROLE_LOCK_STATE,
    "urn:knx:dpt.doorState": ROLE_DOOR_STATE,
    "urn:knx:dpt.deviceStatus": ROLE_DEVICE_STATUS,
    "urn:knx:dpt.windSpeed": ROLE_WIND_SPEED,
    "urn:knx:dpt.power": ROLE_POWER,
    "urn:knx:dpt.bool": ROLE_ALARM,
    "urn:knx:dpt.sceneControl": ROLE_SCENE,
    "urn:knx:dpt.generic": ROLE_VALUE,
    "urn:knx:dpt.genericValue": ROLE_VALUE,
    "urn:knx:dpt.uuid": ROLE_TRIGGER,
}

# Roles whose datapoint is a diagnostic, not part of the user-facing control
DIAGNOSTIC_ROLES = frozenset(
    {
        ROLE_DEVICE_STATUS,
        ROLE_BATTERY_LEVEL,
        ROLE_BATTERY_LOW,
        ROLE_FAILURE,
        ROLE_MOVING,
        ROLE_DIRECTION,
        ROLE_TRIGGER,
    }
)

# Roles that read as an on/off state rather than a measurement
BINARY_ROLES = frozenset(
    {
        ROLE_SWITCH,
        ROLE_SWITCH_FEEDBACK,
        ROLE_ALARM,
        ROLE_RAIN,
        ROLE_WIND_ALARM,
        ROLE_TEMP_ALARM,
        ROLE_DEW_POINT_ALARM,
        ROLE_FAILURE,
        ROLE_BATTERY_LOW,
        ROLE_MOTION,
        ROLE_OPEN_CLOSE,
        ROLE_DEVICE_STATUS,
        ROLE_MOVING,
    }
)

# The value tokens those roles report. `online`/`offline` is the device-status enum,
# `start`/`stop` the detection and movement enums, `open`/`close` the window contact.
#
# The two shutter diagnostics were measured from the bus inwards on 2026-11-22:
# raw 1 on a `dic:dpa.812.51` publishes `offline` and raw 0 `online`, raw 1 on a
# `dic:dpa.801.90` publishes `start` and raw 0 `stop`. So a device-status object
# reads "online" while its bit is **clear**, which is the opposite of the reading
# a KNX error object invites.
BINARY_TRUE_TOKENS = frozenset(
    {"true", "on", "open", "opened", "start", "detected", "online", "active"}
)
BINARY_FALSE_TOKENS = frozenset(
    {"false", "off", "close", "closed", "stop", "offline", "inactive"}
)

# What a one-bit enum member puts on the bus.
#
# A member encodes **by name, to its own DPT's bit** - never by its position in
# the published `enum` list. Measured with the controller's bus monitor on
# 2026-11-21 (`dpt.heatCool`, published `["heat","cool"]`: `heat` -> raw 01,
# `cool` -> raw 00, i.e. DPT 1.100's order, the reverse of the list) and again on
# 2026-11-22 on a live shutter function (`dpt.step`, published
# `["increase","decrease"]`: `increase` -> raw 01, `decrease` -> raw 00;
# `dpt.upDown`: `up` -> raw 00, `down` -> raw 01). Decoding agrees with
# encoding in both directions.
#
# This table is therefore the only safe way to ask "which member sets this bit",
# and it is why the shutter stop member could not be guessed from the enum.
ENUM_BIT_BY_TOKEN: dict[str, int] = {
    "decrease": 0,  # dpt.step
    "increase": 1,
    "up": 0,  # dpt.upDown
    "down": 1,
    "stop": 0,  # dpt.startStop
    "start": 1,
    "online": 0,  # dpt.deviceStatus
    "offline": 1,
    "cool": 0,  # dpt.heatCool
    "heat": 1,
    "off": 0,  # dpt.switch
    "on": 1,
}

# fct.se8000 publishes every dpt.valueTemp through an F->C conversion while still
# labelling the unit "C": a bus value of 32 is published as 0, 100 as 37.77. Measured
# against a control thermostat on the same group address, so it is the function's
# behaviour and there is no flag to detect it from - it has to be keyed on the type.
FCT_FAHRENHEIT_TEMPS = "urn:knx:fct.se8000"
_TEMPERATURE_ROLES = frozenset(
    {ROLE_TEMPERATURE, ROLE_TEMPERATURE_OUTDOOR, ROLE_SETPOINT}
)


def datapoint_role(dp: dict[str, Any]) -> str | None:
    """Return the role of a datapoint, or None when nothing identifies it.

    The archetype decides; the datapoint type is only consulted when the
    archetype is unknown. A datapoint that carries a unit but reads as a role
    with no unit keeps its archetype answer either way - the unit is reported,
    never used to classify.
    """
    types = dp.get("types") or []
    for type_ in types:
        role = DPA_ROLES.get(type_)
        if role:
            return role
    for type_ in types:
        role = DPT_ROLES.get(type_)
        if role:
            return role
    return None


def is_binary(role: str | None, dp: dict[str, Any]) -> bool:
    """Return True if the datapoint reports an on/off state.

    A datapoint with a unit is a measurement whatever its role says: the battery
    *level* and the battery *alert* share neither archetype nor unit, but a
    firmware that reuses an archetype must not turn a percentage into a
    binary_sensor.
    """
    if dp.get("unit"):
        return False
    if role in BINARY_ROLES:
        return True
    if role is not None:
        return False
    # Unknown role: fall back to the published enum, which the controller fills in
    members = {str(m).strip().casefold() for m in (dp.get("enum") or [])}
    return bool(members) and members <= (BINARY_TRUE_TOKENS | BINARY_FALSE_TOKENS)


def enum_member_for_bit(dp: dict[str, Any], bit: int) -> str | None:
    """Return the member of this datapoint's enum that puts `bit` on the bus.

    `None` when the datapoint has no enum, or when no member of it has been
    measured - a caller that cannot name the member it needs must not write a
    guess, because the controller answers 202 to anything well-formed and then
    discards what is not a member verbatim.
    """
    for member in dp.get("enum") or []:
        if not isinstance(member, str):
            continue
        if ENUM_BIT_BY_TOKEN.get(member.strip().casefold()) == bit:
            return member
    return None


def binary_state(value: Any) -> bool | None:
    """Return the on/off meaning of a datapoint value, or None if it has none."""
    token = str(value).strip().casefold() if value is not None else ""
    if token in BINARY_TRUE_TOKENS:
        return True
    if token in BINARY_FALSE_TOKENS:
        return False
    return None


def to_float(value: Any) -> float | None:
    """Return a datapoint value as a number, or None.

    Values arrive as strings (every `valueType` on this controller is `string`),
    already converted to engineering units - a `dpt.scaling` raw 128 is
    published as `50` with `unit: "%"` - so they are parsed, never rescaled.
    """
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def temperature_in(
    function_types: list[str] | None, role: str | None, value: Any
) -> float | None:
    """Return a published temperature as degrees Celsius.

    Only `fct.se8000` needs anything done: it publishes `(bus - 32) x 5/9` and
    labels it `C`, so the published number is read back through the inverse. Any
    other function passes straight through.
    """
    number = to_float(value)
    if number is None:
        return None
    if role in _TEMPERATURE_ROLES and _is_fahrenheit(function_types):
        return round(number * 9 / 5 + 32, 2)
    return number


def temperature_out(function_types: list[str] | None, value: float) -> float:
    """Return a Celsius setpoint in the form `fct.se8000` expects on the wire."""
    if not _is_fahrenheit(function_types):
        return value
    return round((value - 32) * 5 / 9, 2)


def _is_fahrenheit(function_types: list[str] | None) -> bool:
    return any(FCT_FAHRENHEIT_TEMPS in t for t in (function_types or []))
