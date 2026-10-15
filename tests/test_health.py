"""Tests for controller health parsing."""

from custom_components.wiser_for_knx.health import parse_health

STATUS = {
    "General": {"SystemUptime": 28140, "LoadAverage1": 0.88, "LoadAverage2": 0.44, "LoadAverage3": 0.29},
    "Memory": {"total": 260395008, "used": 66826240},
    "Partitions": [
        {"MountedOn": "/", "Free": 199831552, "TotalSize": 243113984},
        {"MountedOn": "/data", "Free": 468443136, "TotalSize": 601563136},
    ],
}
INFO = {"fwVersion": "3.1.0", "hwVersion": ">=3.2", "architecture": "i.MX6UL LM2i", "uptime": 1}


def test_parse_health_full():
    health = parse_health(INFO, STATUS)
    assert health["firmware"] == "3.1.0"
    assert health["uptime"] == 28140
    assert health["load_1m"] == 0.88
    assert health["memory_used_percent"] == 25.7
    assert health["storage_used_percent"] == 22.1


def test_parse_health_missing_data():
    health = parse_health({}, {})
    assert health["firmware"] is None
    assert health["memory_used_percent"] is None
    assert health["storage_used_percent"] is None
    assert health["uptime"] is None
