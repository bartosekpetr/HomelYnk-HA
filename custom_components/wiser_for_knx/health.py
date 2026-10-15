"""Parsing of the controller health data from the management API."""

from __future__ import annotations

from typing import Any


def _percent(used: float, total: float) -> float | None:
    if not total:
        return None
    return round(used / total * 100, 1)


def parse_health(device_info: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    """Build a flat dict of health values from deviceInfo and SystemStatus `data` payloads."""
    general = status.get("General") or {}
    memory = status.get("Memory") or {}
    partitions = status.get("Partitions") or []

    data_part = next((p for p in partitions if p.get("MountedOn") == "/data"), None)
    storage = None
    if data_part and data_part.get("TotalSize"):
        storage = _percent(data_part["TotalSize"] - data_part.get("Free", 0), data_part["TotalSize"])

    # "used" in the controller output excludes buffers/cache, so it reflects real usage
    mem_percent = _percent(memory.get("used", 0), memory.get("total", 0)) if memory else None

    return {
        "firmware": device_info.get("fwVersion"),
        "hardware": device_info.get("hwVersion"),
        "architecture": device_info.get("architecture"),
        "uptime": general.get("SystemUptime", device_info.get("uptime")),
        "load_1m": general.get("LoadAverage1"),
        "load_5m": general.get("LoadAverage2"),
        "load_15m": general.get("LoadAverage3"),
        "memory_used_percent": mem_percent,
        "storage_used_percent": storage,
    }
