"""Device classification for Wiser for KNX.

Wiser Touch widgets (see the "Widget Configuration" chapter of the Wiser KNX
application user guide) are exposed through the KNX IoT 3rd Party API as
functions and datapoints. This module decides which Home Assistant platform a
function belongs to, using (in order): the Touch widget type when the API
exposes it, the KNX function URN, datapoint roles and finally the title.
"""

from __future__ import annotations

import json
import re
from typing import Any

CAT_LIGHT = "light"
CAT_SWITCH = "switch"
CAT_COVER = "cover"
CAT_CLIMATE = "climate"
CAT_SENSOR = "sensor"
CAT_BINARY_SENSOR = "binary_sensor"
CAT_LOCK = "lock"
CAT_SCENE = "scene"
# Widgets that have no sensible Home Assistant entity (media, web content, the
# controller's own automation-trigger virtuals)
CAT_SKIP = "skip"

# Touch widget id -> category
WIDGET_CATEGORIES: dict[str, str] = {
    "se-light-switch": CAT_LIGHT,
    "se-light-dimmer-rotary": CAT_LIGHT,
    "se-light-dimmer-horizontal": CAT_LIGHT,
    "se-light-dimmer-vertical": CAT_LIGHT,
    "se-dali-group": CAT_LIGHT,
    "se-dali-group-rotary": CAT_LIGHT,
    "se-light-rgb": CAT_LIGHT,
    "se-light-rgbw": CAT_LIGHT,
    "se-general-switch": CAT_SWITCH,
    "se-ac-switch": CAT_SWITCH,
    "se-fan-switch": CAT_SWITCH,
    "se-socket-switch": CAT_SWITCH,
    "se-shutter-rotary": CAT_COVER,
    "se-shutter-vertical": CAT_COVER,
    "se-shutter-horizontal": CAT_COVER,
    "se-thermostat": CAT_CLIMATE,
    "se-thermostat-vdc": CAT_CLIMATE,
    "se-logic-thermostat": CAT_CLIMATE,
    "se-floor-heating": CAT_CLIMATE,
    "se-alarm-general": CAT_BINARY_SENSOR,
    "se-alarm-fire": CAT_BINARY_SENSOR,
    "se-alarm-smoke": CAT_BINARY_SENSOR,
    "se-alarm-gas": CAT_BINARY_SENSOR,
    "se-alarm-water": CAT_BINARY_SENSOR,
    "se-window-door-sensor": CAT_BINARY_SENSOR,
    "se-door-sensor": CAT_BINARY_SENSOR,
    "se-window-sensor": CAT_BINARY_SENSOR,
    "se-motion-sensor": CAT_BINARY_SENSOR,
    "se-co2-humidity": CAT_SENSOR,
    "se-air-quality": CAT_SENSOR,
    "se-weather-station": CAT_SENSOR,
    "se-gauge": CAT_SENSOR,
    "se-energy": CAT_SENSOR,
    "se-info-1": CAT_SENSOR,
    "se-info-2": CAT_SENSOR,
    "se-particle-sensor": CAT_SENSOR,
    "se-8000": CAT_CLIMATE,
    "se-airzone": CAT_CLIMATE,
    "se-danfoss-thermostat": CAT_CLIMATE,
    "se-clc": CAT_LIGHT,
    "se-dali-group-slider": CAT_LIGHT,
    "se-rgb-dimmer": CAT_LIGHT,
    "se-rgbw-dimmer": CAT_LIGHT,
    "se-somfy-shades": CAT_COVER,
    "se-somfy-garage": CAT_COVER,
    "se-somfy-motor": CAT_SENSOR,
    "se-smart-lock": CAT_LOCK,
    "se-battery-alarm": CAT_BINARY_SENSOR,
    "se-scene": CAT_SCENE,
    "se-sonos": CAT_SKIP,
    "se-music": CAT_SKIP,
    "se-camera": CAT_SKIP,
    "se-notification": CAT_SKIP,
    "se-url": CAT_SKIP,
    "se-content": CAT_SKIP,
    "chart_widget": CAT_SKIP,
    "custom_widget": CAT_SKIP,
}

# Binary sensor device class (BinarySensorDeviceClass member name) per widget
WIDGET_BINARY_CLASSES: dict[str, str] = {
    "se-alarm-general": "SAFETY",
    "se-alarm-fire": "SMOKE",
    "se-alarm-smoke": "SMOKE",
    "se-alarm-gas": "GAS",
    "se-alarm-water": "MOISTURE",
    "se-window-door-sensor": "OPENING",
    "se-door-sensor": "DOOR",
    "se-window-sensor": "WINDOW",
    "se-motion-sensor": "MOTION",
}

_WIDGET_ID_RE = re.compile(
    r"\b(se-[a-z0-9]+(?:-[a-z0-9]+)*|chart_widget|custom_widget)\b"
)

# Datapoint titles that represent an on/off state rather than a measurement
_BINARY_DP_WORDS = (
    "alarm",
    "alert",
    "detection",
    "detect",
    "leak",
    "smoke",
    "fire",
    "gas",
    "contact",
    "motion",
    "presence",
    "opened",
    "open/closed",
    "low battery",
    "battery low",
    "failure",
)

# Datapoint archetypes / types seen on real controllers that carry an on/off state
_BINARY_DP_TYPES = (
    "dic:dpa.810.51",  # alarm
    "dic:dpa.344.51",  # status/alarm flag
    "dic:dpa.808.51",  # status flag
    "dic:dpa.811.51",  # open/close
    "dic:dpa.414.63",  # motion detection (start/stop)
    "urn:knx:dpt.bool",
    "urn:knx:dpt.openclose",
    "urn:knx:dpt.switch",
)
_BINARY_TOKENS = frozenset(
    {
        "true",
        "false",
        "on",
        "off",
        "open",
        "opened",
        "close",
        "closed",
        "start",
        "stop",
        "active",
        "inactive",
        "alarm",
        "detected",
    }
)


def detect_widget_type(func: dict[str, Any]) -> str | None:
    """Return the Touch widget id for a function if the API exposes one."""
    candidates: list[str] = []
    for key in ("widget_settings", "types"):
        value = func.get(key)
        if value:
            candidates.append(value if isinstance(value, str) else json.dumps(value))
    for text in candidates:
        for match in _WIDGET_ID_RE.findall(text.lower()):
            if match in WIDGET_CATEGORIES:
                return match
    return None


def _titles(func: dict[str, Any]) -> list[str]:
    return [
        (dp.get("title") or "").lower()
        for dp in (func.get("datapoints") or {}).values()
    ]


def _classify_by_urn(types: list[str]) -> str | None:
    """Return the category for a function's KNX function URNs.

    Matched on substrings of the **whole** URN, because vendor types exist:
    `se-logic-thermostat` publishes `urn:knx:fct.schneider.logicThermostat.type.thermostat`,
    which a parser that splits on `.` and takes a segment reads as `thermostat`
    or as `schneider`. The order below is the priority order, so the narrower
    type wins: `fct.switchingLight` is a light before it is a switch, and
    `fct.colorRGBW` is a light although it carries no "light" at all.
    """
    lowered = [t.lower() for t in types]

    if any("alarmautomation" in t for t in lowered):
        return CAT_SKIP
    if any("fct.content" in t for t in lowered):
        return CAT_SKIP

    if any(
        "switchinglight" in t or "dimming" in t or "color" in t or "fct.clc" in t
        for t in lowered
    ):
        return CAT_LIGHT
    if any("smartlock" in t or "doorcontrol" in t for t in lowered):
        return CAT_LOCK
    if any("fct.scene" in t for t in lowered):
        return CAT_SCENE
    if any(
        "blind" in t or "shutter" in t or "shading" in t or "fct.blinds" in t
        for t in lowered
    ):
        return CAT_COVER
    if any(
        "thermostat" in t
        or "climate" in t
        or "temperature" in t
        or "fct.se8000" in t
        or "fct.airzone" in t
        or "fct.itrv" in t
        for t in lowered
    ):
        return CAT_CLIMATE
    if any(
        "alarm" in t
        or "windoor" in t
        or "windowdoor" in t
        or "movement" in t
        or "motion" in t
        for t in lowered
    ):
        return CAT_BINARY_SENSOR
    if any("switch" in t or "socket" in t or "fct.switching" in t for t in lowered):
        return CAT_SWITCH
    if any(
        "sensor" in t
        or "power" in t
        or "airquality" in t
        or "weather" in t
        or "gauge" in t
        or "fct.info" in t
        for t in lowered
    ):
        return CAT_SENSOR
    return None


def _classify_by_datapoints(func: dict[str, Any]) -> str | None:
    """Infer the category from datapoint roles (object names of the Touch widgets)."""
    titles = _titles(func)
    if not titles:
        return None
    joined = " | ".join(titles)

    if any(w in joined for w in ("height position", "slat position", "slats position")):
        return CAT_COVER
    if "setpoint" in joined and any(
        w in joined
        for w in ("operation mode", "heating", "cooling", "hvac", "temperature")
    ):
        return CAT_CLIMATE
    if "scene" in joined and "value" not in joined:
        return CAT_SCENE
    if any(w in joined for w in ("alarm", "detection")) and "setpoint" not in joined:
        return CAT_BINARY_SENSOR
    return None


def _classify_by_title(title: str) -> str | None:
    if any(w in title for w in ("dimm", "light", "lamp", "spot", "led", "eclairage")):
        return CAT_LIGHT
    if any(w in title for w in ("switch", "socket", "prise", "plug")):
        return CAT_SWITCH
    if any(w in title for w in ("blind", "shutter", "volet", "curtain")):
        return CAT_COVER
    if any(w in title for w in ("thermostat", "heating", "cooling", "chauffage")):
        return CAT_CLIMATE
    return None


def classify_function(func: dict[str, Any]) -> str:
    """Return the Home Assistant category for a function."""
    widget = detect_widget_type(func)
    if widget:
        return WIDGET_CATEGORIES[widget]

    category = _classify_by_urn(func.get("types", []))
    if category:
        return category

    category = _classify_by_datapoints(func)
    if category:
        return category

    category = _classify_by_title((func.get("title") or "").lower())
    return category or CAT_SENSOR


def binary_device_class(func: dict[str, Any]) -> str | None:
    """Return the BinarySensorDeviceClass member name for a binary sensor function."""
    widget = detect_widget_type(func)
    if widget and widget in WIDGET_BINARY_CLASSES:
        return WIDGET_BINARY_CLASSES[widget]

    haystack = (
        " ".join(func.get("types", [])).lower()
        + " "
        + (func.get("title") or "").lower()
    )
    for words, device_class in (
        (("water", "leak", "flood"), "MOISTURE"),
        (("smoke", "fire"), "SMOKE"),
        (("gas",), "GAS"),
        (("motion", "movement", "presence"), "MOTION"),
        (("window",), "WINDOW"),
        (("door",), "DOOR"),
        (("alarm",), "SAFETY"),
    ):
        if any(w in haystack for w in words):
            return device_class
    return None


def _is_number(value: Any) -> bool:
    try:
        float(str(value))
    except ValueError:
        return False
    return True


def is_binary_datapoint(func: dict[str, Any], dp: dict[str, Any]) -> bool:
    """Return True if a datapoint of a binary-sensor function is an on/off state.

    Datapoint titles are user-defined group object names, so the datapoint
    type and the current value are checked before the title.
    """
    types = [t.lower() for t in dp.get("types") or []]
    if "urn:knx:dpt.uuid" in types or dp.get("unit"):
        return False

    value = dp.get("value")
    token = str(value).strip().lower() if value is not None else ""
    if token in _BINARY_TOKENS:
        return True
    if token and _is_number(token):
        return False
    if any(t in _BINARY_DP_TYPES for t in types):
        return True

    title = (dp.get("title") or "").lower()
    if "level" in title and "battery" in title:
        return False
    if any(w in title for w in _BINARY_DP_WORDS):
        return True
    return dp.get("value_type") == "boolean"
