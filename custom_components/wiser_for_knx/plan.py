"""Which entities a set of functions becomes, decided in one place.

Two kinds of entity come out of the controller's model:

* a **composite** entity per function - a light, switch, cover, climate or lock -
  which consumes the datapoints it understands (`COMPOSITE_ROLES`);
* a **datapoint** entity for everything the composite did not consume, so an
  exported datapoint is never invisible in Home Assistant: a socket's active
  power, a sensor's battery level, a shutter's "is moving" flag, a thermostat's
  twelve valve-drive heating demands.

A function whose datapoints cannot support its composite (a `fct.temperatureAir`
with nothing but a current temperature, a `fct.iTRV` with nothing but a heating
demand) falls through to datapoint entities instead of becoming a climate with
no controls. That is what keeps a misclassification harmless: the worst case is
a sensor where a richer entity could have been, never a broken thermostat.

Pure module: no Home Assistant imports, so it stays unit-testable.
"""

from __future__ import annotations

from typing import Any

from .datapoints import (
    DIAGNOSTIC_ROLES,
    ROLE_BRIGHTNESS,
    ROLE_COLOR_BLUE,
    ROLE_COLOR_GREEN,
    ROLE_COLOR_RED,
    ROLE_COLOR_RGB,
    ROLE_COLOR_WHITE,
    ROLE_HEAT_COOL,
    ROLE_HVAC_MODE,
    ROLE_LOCK_CONTROL,
    ROLE_LOCK_STATE,
    ROLE_MOVE,
    ROLE_POSITION,
    ROLE_SCENE,
    ROLE_SETPOINT,
    ROLE_SWITCH,
    ROLE_SWITCH_FEEDBACK,
    ROLE_TEMPERATURE,
    ROLE_TILT,
    ROLE_TRIGGER,
    datapoint_role,
    is_binary,
    to_float,
)
from .widgets import (
    CAT_CLIMATE,
    CAT_COVER,
    CAT_LIGHT,
    CAT_LOCK,
    CAT_SKIP,
    CAT_SWITCH,
    classify_function,
)

PLATFORM_BINARY_SENSOR = "binary_sensor"
PLATFORM_BUTTON = "button"
PLATFORM_CLIMATE = "climate"
PLATFORM_COVER = "cover"
PLATFORM_LIGHT = "light"
PLATFORM_LOCK = "lock"
PLATFORM_NUMBER = "number"
PLATFORM_SELECT = "select"
PLATFORM_SENSOR = "sensor"
PLATFORM_SWITCH = "switch"

# The roles each composite entity reads and writes. Anything else the function owns
# becomes its own entity next to it.
COMPOSITE_ROLES: dict[str, frozenset[str]] = {
    CAT_LIGHT: frozenset(
        {
            ROLE_SWITCH,
            ROLE_SWITCH_FEEDBACK,
            ROLE_BRIGHTNESS,
            ROLE_COLOR_RGB,
            ROLE_COLOR_RED,
            ROLE_COLOR_GREEN,
            ROLE_COLOR_BLUE,
            ROLE_COLOR_WHITE,
        }
    ),
    CAT_SWITCH: frozenset({ROLE_SWITCH, ROLE_SWITCH_FEEDBACK}),
    CAT_COVER: frozenset({ROLE_POSITION, ROLE_TILT, ROLE_MOVE}),
    CAT_CLIMATE: frozenset(
        {
            ROLE_TEMPERATURE,
            ROLE_SETPOINT,
            ROLE_HVAC_MODE,
            ROLE_HEAT_COOL,
            ROLE_SWITCH_FEEDBACK,
        }
    ),
    CAT_LOCK: frozenset({ROLE_LOCK_CONTROL, ROLE_LOCK_STATE}),
}

_COMPOSITE_PLATFORMS = {
    CAT_LIGHT: PLATFORM_LIGHT,
    CAT_SWITCH: PLATFORM_SWITCH,
    CAT_COVER: PLATFORM_COVER,
    CAT_CLIMATE: PLATFORM_CLIMATE,
    CAT_LOCK: PLATFORM_LOCK,
}


def _roles(func: dict[str, Any]) -> dict[str, str | None]:
    """Return {datapoint id: role} for a function's datapoints."""
    return {
        dp_id: datapoint_role(dp)
        for dp_id, dp in (func.get("datapoints") or {}).items()
    }


def composite_is_viable(category: str, func: dict[str, Any]) -> bool:
    """Return True if the function's datapoints can actually drive the composite.

    The controller exports only channels that have both a write object and its
    status feedback, so a viable composite always has something writable - but a
    function can still arrive with a subset (or, for a few seconds after a config
    change, with nothing at all).
    """
    datapoints = func.get("datapoints") or {}
    roles = _roles(func)
    writable = {roles[dp_id] for dp_id, dp in datapoints.items() if dp.get("writable")}
    present = set(roles.values())

    if category in (CAT_LIGHT, CAT_SWITCH):
        return bool(
            writable
            & {
                ROLE_SWITCH,
                ROLE_SWITCH_FEEDBACK,
                ROLE_BRIGHTNESS,
                ROLE_COLOR_RGB,
                ROLE_COLOR_RED,
            }
        )
    if category == CAT_COVER:
        return bool(writable & {ROLE_POSITION, ROLE_MOVE, ROLE_TILT})
    if category == CAT_CLIMATE:
        # A setpoint is enough on its own; a bare current temperature is not a
        # thermostat, and neither is a lone valve-drive heating demand.
        if ROLE_SETPOINT in writable:
            return True
        return ROLE_TEMPERATURE in present and bool(
            writable & {ROLE_SWITCH_FEEDBACK, ROLE_HVAC_MODE, ROLE_HEAT_COOL}
        )
    if category == CAT_LOCK:
        return ROLE_LOCK_CONTROL in writable
    return False


def datapoint_platform(dp: dict[str, Any], role: str | None) -> str | None:
    """Return the platform a standalone datapoint belongs on, or None to skip it."""
    if role == ROLE_TRIGGER:
        # The two built-in automation-trigger virtuals every subscription carries
        return None
    if role == ROLE_SCENE:
        return PLATFORM_BUTTON
    if role in (ROLE_SWITCH, ROLE_SWITCH_FEEDBACK):
        # An on/off slot a composite did not take - a thermostat's fan manual
        # mode, an RGBW light's white channel. Writable means it is a control.
        return PLATFORM_SWITCH if dp.get("writable") else PLATFORM_BINARY_SENSOR
    if is_binary(role, dp):
        return PLATFORM_BINARY_SENSOR
    if dp.get("writable"):
        if dp.get("enum"):
            return PLATFORM_SELECT
        if dp.get("unit") or to_float(dp.get("value")) is not None:
            return PLATFORM_NUMBER
        # Writable, no enum, no number: nothing sensible to offer but the reading
        return PLATFORM_SENSOR
    return PLATFORM_SENSOR


def plan_entities(functions: dict[str, dict[str, Any]]) -> dict[str, list[dict]]:
    """Return {platform: [spec]} for every entity the current data supports.

    A spec always carries `function_id` and `key` (unique within its platform);
    datapoint specs also carry `datapoint_id`, `role` and `diagnostic`.
    """
    plan: dict[str, list[dict]] = {}

    def add(platform: str, spec: dict) -> None:
        plan.setdefault(platform, []).append(spec)

    for func_id, func in sorted((functions or {}).items()):
        category = classify_function(func)
        if category == CAT_SKIP:
            continue

        roles = _roles(func)
        consumed: set[str] = set()

        if category in _COMPOSITE_PLATFORMS and composite_is_viable(category, func):
            wanted = COMPOSITE_ROLES[category]
            consumed = {
                dp_id
                for dp_id, role in roles.items()
                if role in wanted and role not in DIAGNOSTIC_ROLES
            }
            add(
                _COMPOSITE_PLATFORMS[category],
                {"function_id": func_id, "key": func_id},
            )

        # Everything else - and everything a category such as binary_sensor, sensor
        # or scene owns outright - becomes an entity of its own.
        for dp_id, dp in sorted((func.get("datapoints") or {}).items()):
            if dp_id in consumed:
                continue
            role = roles[dp_id]
            platform = datapoint_platform(dp, role)
            if platform is None:
                continue
            spec = {
                "function_id": func_id,
                "datapoint_id": dp_id,
                "role": role,
                "diagnostic": role in DIAGNOSTIC_ROLES,
                "key": dp_id,
            }
            if platform == PLATFORM_BUTTON:
                members = [str(m) for m in (dp.get("enum") or [])] or ["1"]
                for member in members:
                    add(
                        platform,
                        {**spec, "value": member, "key": f"{dp_id}_{member}"},
                    )
                continue
            add(platform, spec)

    return plan
