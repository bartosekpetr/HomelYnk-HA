"""Unit tests for Wiser for KNX API client, parsing, and classification."""

import asyncio
import json
import os

from custom_components.wiser_for_knx.api import WiserKnxClient
from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator


def test_classify_functions():
    """Test classifying functions from KNX IoT 3rd Party API into HA domains."""
    # Dimmer
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Living room dimmer",
        "types": ["urn:knx:fct.dimming"],
    }) == "light"

    # Switching light
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Ceiling Spot",
        "types": ["urn:knx:fct.switchingLight"],
    }) == "light"

    # Socket / Switch
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Coffee socket",
        "types": ["urn:knx:fct.switchingSocket"],
    }) == "switch"

    # Cover / Blinds
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Balcony blinds",
        "types": ["urn:knx:fct.blindsVertical"],
    }) == "cover"

    # Climate / Thermostat
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Room Thermostat",
        "types": ["urn:knx:fct.temperatureAirFan"],
    }) == "climate"

    # Sensor
    assert WiserKnxDataUpdateCoordinator.classify_function({
        "title": "Power Meter",
        "types": ["urn:knx:fct.power"],
    }) == "sensor"


def test_live_data_parsing():
    """Test parsing the captured live JSON payload from controller 192.168.0.104."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    locations_file = os.path.join(base_dir, "live_locations.json")
    functions_file = os.path.join(base_dir, "live_functions.json")
    datapoints_file = os.path.join(base_dir, "live_datapoints.json")

    if not os.path.exists(locations_file):
        return

    with open(locations_file, "r", encoding="utf-8") as f:
        locs_raw = json.load(f)["data"]
    with open(functions_file, "r", encoding="utf-8") as f:
        funcs_raw = json.load(f)["data"]
    with open(datapoints_file, "r", encoding="utf-8") as f:
        dps_raw = json.load(f)["data"]

    # Verify locations structure
    locations = {}
    for item in locs_raw:
        lid = item["id"]
        locations[lid] = {
            "id": lid,
            "type": item["type"],
            "title": item["attributes"]["title"],
        }

    assert "Site" in [l["title"] for l in locations.values()]
    assert "1 room" in [l["title"] for l in locations.values()]
    assert "4 dimmers" in [l["title"] for l in locations.values()]

    # Verify classifications of live functions
    classifications = {}
    for fn in funcs_raw:
        cat = WiserKnxDataUpdateCoordinator.classify_function({
            "title": fn["attributes"]["title"],
            "types": fn.get("meta", {}).get("@type", []),
        })
        classifications[cat] = classifications.get(cat, 0) + 1

    print("Live classifications:", classifications)
    assert classifications.get("light", 0) > 0
    assert classifications.get("switch", 0) > 0
    assert classifications.get("climate", 0) > 0


if __name__ == "__main__":
    test_classify_functions()
    test_live_data_parsing()
    print("All tests passed!")
