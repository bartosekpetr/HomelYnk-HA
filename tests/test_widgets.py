"""Tests for Touch widget based device classification."""

from custom_components.wiser_for_knx.widgets import (
    WIDGET_CATEGORIES,
    binary_device_class,
    classify_function,
    detect_widget_type,
    is_binary_datapoint,
)


def _func(title="Device", types=None, settings=None, dp_titles=()):
    return {
        "title": title,
        "types": types or [],
        "widget_settings": settings,
        "datapoints": {str(i): {"title": t} for i, t in enumerate(dp_titles)},
    }


def test_widget_type_from_settings_wins():
    func = _func(
        title="Hall",
        types=["urn:knx:fct.switching"],
        settings={"type": "se-alarm-water"},
    )
    assert detect_widget_type(func) == "se-alarm-water"
    assert classify_function(func) == "binary_sensor"


def test_every_known_widget_maps_to_a_category():
    for widget, category in WIDGET_CATEGORIES.items():
        assert classify_function(_func(settings={"widget": widget})) == category


def test_unknown_widget_in_settings_is_ignored():
    assert detect_widget_type(_func(settings={"type": "se-unknown-thing"})) is None


def test_urn_classification():
    assert classify_function(_func(types=["urn:knx:fct.switchingLight"])) == "light"
    assert classify_function(_func(types=["urn:knx:fct.dimming"])) == "light"
    assert classify_function(_func(types=["urn:knx:fct.switchingSocket"])) == "switch"
    assert classify_function(_func(types=["urn:knx:fct.blindsVertical"])) == "cover"
    assert classify_function(_func(types=["urn:knx:fct.VDCThermostat"])) == "climate"
    assert classify_function(_func(types=["urn:knx:fct.alarmWater"])) == "binary_sensor"
    assert classify_function(_func(types=["urn:knx:fct.windowDoorSensor"])) == "binary_sensor"
    assert classify_function(_func(types=["urn:knx:fct.movementDetector"])) == "binary_sensor"
    assert classify_function(_func(types=["urn:knx:fct.power"])) == "sensor"
    assert classify_function(_func(types=["urn:knx:fct.weather"])) == "sensor"


def test_datapoint_role_inference():
    shutter = _func(dp_titles=["Height position", "Slat position", "Movement object"])
    assert classify_function(shutter) == "cover"

    thermostat = _func(dp_titles=["Temperature", "Setpoint", "Operation mode"])
    assert classify_function(thermostat) == "climate"

    logic = _func(dp_titles=["Temperature", "Setpoint", "Heating demand"])
    assert classify_function(logic) == "climate"

    motion = _func(dp_titles=["Detection", "Illuminance"])
    assert classify_function(motion) == "binary_sensor"

    scene = _func(dp_titles=["Scene"])
    assert classify_function(scene) == "skip"


def test_title_fallback_and_default():
    assert classify_function(_func(title="Kitchen spot")) == "light"
    assert classify_function(_func(title="Coffee plug")) == "switch"
    assert classify_function(_func(title="Mystery")) == "sensor"


def test_plain_temperature_title_is_not_climate():
    assert classify_function(_func(title="Outdoor temperature")) == "sensor"


def test_binary_device_classes():
    assert binary_device_class(_func(settings={"t": "se-alarm-water"})) == "MOISTURE"
    assert binary_device_class(_func(settings={"t": "se-motion-sensor"})) == "MOTION"
    assert binary_device_class(_func(title="Gas leak")) == "MOISTURE"
    assert binary_device_class(_func(types=["urn:knx:fct.alarm"], title="Siren")) == "SAFETY"
    assert binary_device_class(_func(title="Hallway")) is None


def test_binary_datapoint_selection():
    func = _func()
    assert is_binary_datapoint(func, {"title": "Alarm object"})
    assert is_binary_datapoint(func, {"title": "Detection"})
    assert is_binary_datapoint(func, {"title": "Low battery"})
    assert not is_binary_datapoint(func, {"title": "Battery level", "unit": "%"})
    assert not is_binary_datapoint(func, {"title": "Illuminance", "unit": "lx"})
