"""Stable controller identity helpers (pure functions, no Home Assistant imports)."""

from __future__ import annotations

import re
from typing import Any

LEGACY_PREFIX = "wiser_knx_"
_MAC_KEYS = ("macAddress", "mac", "MAC", "macaddress")
_SERIAL_KEYS = ("serialNumber", "serial", "serialnumber")


def normalize_mac(value: Any) -> str | None:
    """Return a MAC as lower-case colon-separated hex, or None if it is not a MAC."""
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[:\-.]", "", value.strip()).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def stable_id_from_device_info(info: dict[str, Any] | None) -> str | None:
    """Pick a stable id from a controller info payload: MAC first, then serial number."""
    info = info or {}
    for key in _MAC_KEYS:
        mac = normalize_mac(info.get(key))
        if mac:
            return mac
    for key in _SERIAL_KEYS:
        serial = info.get(key)
        if isinstance(serial, str) and serial.strip():
            return serial.strip()
    return None


def stable_id_from_legacy(unique_id: str | None) -> str | None:
    """Map a pre-0.7 unique id to a stable one.

    ``wiser_knx_<mac>`` (DHCP flow) becomes the plain MAC. ``wiser_knx_<ip or host>`` cannot be
    converted offline, so it returns None and is adopted later by discovery or at setup.
    """
    if not unique_id:
        return None
    return normalize_mac(unique_id.removeprefix(LEGACY_PREFIX))
