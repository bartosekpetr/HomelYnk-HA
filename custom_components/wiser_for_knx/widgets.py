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

from .const import (
    FCT_AIR_QUALITY,
    FCT_ALARM,
    FCT_ALARM_DEW_POINT,
    FCT_ALARM_WATER,
    FCT_BLINDS,
    FCT_DIMMING,
    FCT_GAUGE,
    FCT_GENERIC_THERMOSTAT,
    FCT_ITRV,
    FCT_MOVEMENT,
    FCT_POWER,
    FCT_SWITCHING,
    FCT_SWITCHING_LIGHT,
    FCT_SWITCHING_SOCKET,
    FCT_TEMPERATURE_AIR_FAN,
    FCT_VDC_THERMOSTAT,
    FCT_WEATHER,
    FCT_WINDOW_DOOR,
)

CAT_LIGHT = "light"
CAT_SWITCH = "switch"
CAT_COVER = "cover"
CAT_CLIMATE = "climate"
CAT_SENSOR = "sensor"
CAT_BINARY_SENSOR = "binary_sensor"
# Widgets that have no sensible Home Assistant entity (scenes, media, web content)
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
    "se-scene": CAT_SKIP,
    "se-sonos": CAT_SKIP,
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

_WIDGET_ID_RE = re.compile(r"\b(se-[a-z0-9]+(?:-[a-z0-9]+)*|chart_widget|custom_widget)\b")

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
    lowered = [t.lower() for t in types]

    if any(t == FCT_DIMMING or "dimming" in t for t in types):
        return CAT_LIGHT
    if any(t == FCT_SWITCHING_LIGHT or "switchinglight" in t for t in lowered):
        return CAT_LIGHT
    if any(
        t in (FCT_SWITCHING_SOCKET, FCT_SWITCHING) or "switch" in t or "socket" in t
        for t in types
    ):
        return CAT_SWITCH
    if any(t == FCT_BLINDS or "blind" in t or "shutter" in t for t in types):
        return CAT_COVER
    if any(
        t in (FCT_TEMPERATURE_AIR_FAN, FCT_GENERIC_THERMOSTAT, FCT_VDC_THERMOSTAT, FCT_ITRV)
        or "thermostat" in t
        or "climate" in t
        for t in types
    ):
        return CAT_CLIMATE
    if any(
        t in (FCT_ALARM, FCT_ALARM_DEW_POINT, FCT_ALARM_WATER, FCT_WINDOW_DOOR, FCT_MOVEMENT)
        or "alarm" in t
        or "windowdoor" in t
        or "movement" in t
        or "motion" in t
        for t in types
    ):
        return CAT_BINARY_SENSOR
    if any(
        t in (FCT_POWER, FCT_AIR_QUALITY, FCT_WEATHER, FCT_GAUGE)
        or "sensor" in t
        or "power" in t
        for t in types
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
        w in joined for w in ("operation mode", "heating", "cooling", "hvac", "temperature")
    ):
        return CAT_CLIMATE
    if "scene" in joined and "value" not in joined:
        return CAT_SKIP
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

    haystack = " ".join(func.get("types", [])).lower() + " " + (func.get("title") or "").lower()
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


def is_binary_datapoint(func: dict[str, Any], dp: dict[str, Any]) -> bool:
    """Return True if a datapoint of a binary-sensor function is an on/off state."""
    title = (dp.get("title") or "").lower()
    if "level" in title and "battery" in title:
        return False
    if any(w in title for w in _BINARY_DP_WORDS):
        return True
    return dp.get("value_type") == "boolean" and not dp.get("unit")
