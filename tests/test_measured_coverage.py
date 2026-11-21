"""Every datapoint shape the controller was measured to publish gets an entity.

`MEASURED` is generated from the wiser-knx-skillset `widget-api-matrix.json`: all 47
app-exportable Touch widget types, each built three ways (mandatory slots, half the
optional ones, all of them), read back over the local API. One row per distinct
(function type, archetype, datapoint type, unit, writable) combination - 144 of them,
covering 346 datapoints across 191 functions.

The claim under test is the one the whole v0.8.0 scope rests on: **no datapoint the
controller exports is invisible in Home Assistant**. A row with no role would become a
sensor with no unit and no device class; a row with no platform would become nothing at
all. Regenerate with `tools/dump_controller.py` against a real controller - it prints any
archetype that has no role.
"""

import pytest

from custom_components.wiser_for_knx.datapoints import datapoint_role
from custom_components.wiser_for_knx.plan import datapoint_platform

# (function type, dic:dpa archetype, dpt type, unit, writable) - prefixes stripped
MEASURED = [
    ("VDCThermostat", "392.52", "valueTemp", "C", True),
    ("VDCThermostat", "399.113", "valueTempShift", "", True),
    ("VDCThermostat", "399.50", "hvacOperationMode", "", True),
    ("VDCThermostat", "399.56", "valueTemp", "C", False),
    ("VDCThermostat", "399.64", "heatCool", "", True),
    ("airQuality", "337.51", "humidity", "%", False),
    ("airQuality", "399.56", "valueTemp", "C", False),
    ("airQuality", "65533.51", "scaling", "%", False),
    ("airQuality", "65533.52", "bool", "", False),
    ("airQuality", "65534.51", "airQuality", "ppm", False),
    ("airQuality", "812.51", "deviceStatus", "", False),
    ("airzone", "392.52", "valueTemp", "C", True),
    ("airzone", "392.53", "valueTemp", "C", True),
    ("airzone", "392.55", "valueTemp", "C", True),
    ("airzone", "392.56", "valueTemp", "C", True),
    ("airzone", "399.53", "airzoneMode", "", True),
    ("airzone", "399.56", "valueTemp", "C", False),
    ("airzone", "399.77", "airzoneFan", "", True),
    ("airzone", "417.71", "occupancyMode", "", True),
    ("airzone", "417.72", "switch", "", True),
    ("alarm", "65533.51", "scaling", "%", False),
    ("alarm", "65533.52", "bool", "", False),
    ("alarm", "810.51", "bool", "", False),
    ("alarm", "812.51", "deviceStatus", "", False),
    ("alarmDewPoint", "344.51", "bool", "", False),
    ("alarmFire", "65533.51", "scaling", "%", False),
    ("alarmFire", "65533.52", "bool", "", False),
    ("alarmFire", "804.51", "bool", "", False),
    ("alarmFire", "812.51", "deviceStatus", "", False),
    ("alarmGas", "65533.51", "scaling", "%", False),
    ("alarmGas", "65533.52", "bool", "", False),
    ("alarmGas", "805.51", "bool", "", False),
    ("alarmGas", "812.51", "deviceStatus", "", False),
    ("alarmLight", "808.51", "bool", "", False),
    ("alarmTemp", "807.51", "bool", "", False),
    ("alarmWater", "65533.51", "scaling", "%", False),
    ("alarmWater", "65533.52", "bool", "", False),
    ("alarmWater", "806.51", "bool", "", False),
    ("alarmWater", "812.51", "deviceStatus", "", False),
    ("alarmWind", "802.51", "bool", "", False),
    ("blinds", "800.65", "scaling", "%", True),
    ("blinds", "800.66", "scaling", "%", True),
    ("blindsHorizontal", "800.65", "scaling", "%", True),
    ("blindsHorizontal", "800.66", "scaling", "%", True),
    ("blindsHorizontal", "801.61", "upDown", "", True),
    ("blindsHorizontal", "801.62", "step", "", True),
    ("blindsHorizontal", "801.90", "startStop", "", False),
    ("blindsHorizontal", "801.91", "upDown", "", False),
    ("blindsHorizontal", "812.51", "deviceStatus", "", False),
    ("blindsVertical", "800.65", "scaling", "%", True),
    ("blindsVertical", "800.66", "scaling", "%", True),
    ("blindsVertical", "801.61", "upDown", "", True),
    ("blindsVertical", "801.62", "step", "", True),
    ("blindsVertical", "801.90", "startStop", "", False),
    ("blindsVertical", "801.91", "upDown", "", False),
    ("blindsVertical", "812.51", "deviceStatus", "", False),
    ("colorRGB", "417.69", "switch", "", True),
    ("colorRGB", "423.52", "R-G-B", "3BHEX", True),
    ("colorRGBW", "417.69", "switch", "", True),
    ("colorRGBW", "417.70", "switch", "", True),
    ("colorRGBW", "423.58", "scaling", "%", True),
    ("colorRGBW", "423.61", "scaling", "%", True),
    ("colorRGBW", "423.64", "scaling", "%", True),
    ("colorRGBW", "424.67", "scaling", "%", True),
    ("dimming", "418.61", "switch", "", True),
    ("dimming", "418.63", "scaling", "%", True),
    ("gasSensor", "65534.56", "airQuality", "ppm", False),
    ("gasSensor", "65534.57", "airQualityDensity", "μg/m³", False),
    ("gasSensor", "65534.58", "airQuality", "ppm", False),
    ("gasSensor", "65534.59", "airQuality", "ppm", False),
    ("gasSensor", "65534.60", "airQuality", "ppm", False),
    ("gasSensor", "65534.61", "tvocIndex", "", False),
    ("gauge", "417.65", "generic", "", False),
    ("iTRV", "399.65", "scaling", "%", False),
    ("iTRV", "65533.51", "scaling", "%", False),
    ("info", "417.65", "genericValue", "", False),
    ("movementDetector", "414.62", "valueLux", "", False),
    ("movementDetector", "414.63", "startStop", "", False),
    ("movementDetector", "65533.51", "scaling", "%", False),
    ("movementDetector", "65533.52", "bool", "", False),
    ("particleSensor", "65534.52", "airQualityDensity", "μg/m³", False),
    ("particleSensor", "65534.53", "airQualityDensity", "μg/m³", False),
    ("particleSensor", "65534.54", "airQualityDensity", "μg/m³", False),
    ("particleSensor", "65534.55", "airQualityDensity", "μg/m³", False),
    ("scene", "1010.54", "sceneControl", "", True),
    ("schneider.generic", "417.65", "generic", "", False),
    ("schneider.windoor.type.door", "65533.51", "scaling", "%", False),
    ("schneider.windoor.type.door", "65533.52", "bool", "", False),
    ("schneider.windoor.type.door", "811.51", "openClose", "", False),
    ("schneider.windoor.type.door", "812.51", "deviceStatus", "", False),
    ("se8000", "", "se8000FanSequence", "", True),
    ("se8000", "337.51", "humidity", "%", False),
    ("se8000", "392.52", "valueTemp", "C", True),
    ("se8000", "392.53", "valueTemp", "C", True),
    ("se8000", "392.54", "valueTemp", "C", True),
    ("se8000", "392.55", "valueTemp", "C", True),
    ("se8000", "392.56", "valueTemp", "C", True),
    ("se8000", "392.57", "valueTemp", "C", True),
    ("se8000", "399.51", "heatCool", "", False),
    ("se8000", "399.56", "valueTemp", "C", False),
    ("se8000", "399.57", "valueTemp", "C", False),
    ("se8000", "399.64", "se8000Mode", "", True),
    ("se8000", "399.75", "se8000Fan", "", True),
    ("se8000", "417.71", "occupancyMode", "", True),
    ("se8000", "65534.51", "airQuality", "", False),
    ("shadingRotary", "800.65", "scaling", "%", True),
    ("shadingRotary", "801.61", "upDown", "", True),
    ("shadingRotary", "801.62", "step", "", True),
    ("shadingRotary", "801.90", "startStop", "", False),
    ("shadingRotary", "801.91", "upDown", "", False),
    ("shadingRotary", "812.51", "deviceStatus", "", False),
    ("smartLock", "65533.51", "scaling", "%", False),
    ("smartLock", "811.52", "doorControl", "", True),
    ("smartLock", "811.53", "lockState", "", False),
    ("smartLock", "811.54", "doorState", "", False),
    ("switching", "427.71", "switch", "", True),
    ("switching", "812.51", "deviceStatus", "", False),
    ("switchingAC", "417.70", "switch", "", True),
    ("switchingAC", "812.51", "deviceStatus", "", False),
    ("switchingFan", "417.70", "switch", "", True),
    ("switchingFan", "812.51", "deviceStatus", "", False),
    ("switchingLight", "417.70", "switch", "", True),
    ("switchingSocket", "417.70", "switch", "", True),
    ("switchingSocket", "901.51", "power", "W", False),
    ("temperatureAirFan", "392.52", "valueTemp", "C", True),
    ("temperatureAirFan", "399.50", "hvacOperationMode", "", False),
    ("temperatureAirFan", "399.50", "hvacOperationMode", "", True),
    ("temperatureAirFan", "399.56", "valueTemp", "C", False),
    ("temperatureAirFan", "399.64", "heatCool", "", True),
    ("temperatureAirFan", "399.74", "scaling", "", True),
    ("temperatureAirFan", "417.70", "switch", "", True),
    ("temperatureAirFan", "417.72", "switch", "", True),
    ("temperatureAirFan", "65533.51", "scaling", "%", False),
    ("temperatureAirFan", "65533.52", "bool", "", False),
    ("temperatureAirFan", "812.51", "deviceStatus", "", False),
    ("temperatureFloor", "392.52", "valueTemp", "C", True),
    ("temperatureFloor", "417.70", "switch", "", True),
    ("weather", "320.51", "valueTemp", "", False),
    ("weather", "803.51", "bool", "", False),
    ("weather", "900.52", "windSpeed", "m/s", False),
    ("windowDoorSensor", "65533.51", "scaling", "%", False),
    ("windowDoorSensor", "65533.52", "bool", "", False),
    ("windowDoorSensor", "811.51", "openClose", "", False),
    ("windowDoorSensor", "812.51", "deviceStatus", "", False),
]


def _dp(dpa, dpt, unit, writable):
    return {
        "id": "dp",
        "title": "whatever the installer typed",
        "types": [f"dic:dpa.{dpa}", f"urn:knx:dpt.{dpt}"],
        "unit": unit,
        "writable": writable,
        "value": None,
        "enum": [],
    }


@pytest.mark.parametrize(("function", "dpa", "dpt", "unit", "writable"), MEASURED)
def test_every_measured_datapoint_has_a_role(function, dpa, dpt, unit, writable):
    assert datapoint_role(_dp(dpa, dpt, unit, writable)) is not None, (
        f"{function} publishes dic:dpa.{dpa} ({dpt}) with no role"
    )


@pytest.mark.parametrize(("function", "dpa", "dpt", "unit", "writable"), MEASURED)
def test_every_measured_datapoint_lands_on_a_platform(
    function, dpa, dpt, unit, writable
):
    dp = _dp(dpa, dpt, unit, writable)
    role = datapoint_role(dp)
    assert datapoint_platform(dp, role) is not None, (
        f"{function} publishes dic:dpa.{dpa} ({dpt}) and nothing would show it"
    )


def test_the_fixture_still_covers_the_whole_sweep():
    """A trimmed fixture would make the two tests above pass for the wrong reason."""
    assert len(MEASURED) == 144
    assert len({row[0] for row in MEASURED}) == 38  # distinct fct.* types
