"""What a datapoint is, decided from its `dic:dpa.*` archetype.

Every archetype and enum below is one the controller actually published, taken
from the wiser-knx-skillset widget matrix (47 widget types built three ways
each). The point of these tests is that the decision never depends on a
datapoint's title: titles are user-defined KNX group object names, in the
installer's own language.
"""

import pytest

from custom_components.wiser_for_knx.datapoints import (
    ROLE_ALARM,
    ROLE_BATTERY_LEVEL,
    ROLE_BATTERY_LOW,
    ROLE_BRIGHTNESS,
    ROLE_CO2,
    ROLE_DEVICE_STATUS,
    ROLE_HEATING_DEMAND,
    ROLE_HVAC_MODE,
    ROLE_ILLUMINANCE,
    ROLE_LOCK_CONTROL,
    ROLE_MOTION,
    ROLE_MOVE,
    ROLE_OPEN_CLOSE,
    ROLE_POSITION,
    ROLE_POWER,
    ROLE_SCENE,
    ROLE_SETPOINT,
    ROLE_SWITCH,
    ROLE_TEMPERATURE,
    ROLE_TILT,
    binary_state,
    datapoint_role,
    is_binary,
    temperature_in,
    temperature_out,
    to_float,
)


def _dp(dpa, dpt, **kwargs):
    """A datapoint as the API reports it: both type tags in `types`."""
    return {"types": [dpa, dpt], **kwargs}


@pytest.mark.parametrize(
    ("dpa", "dpt", "role"),
    [
        ("dic:dpa.417.70", "urn:knx:dpt.switch", ROLE_SWITCH),
        ("dic:dpa.418.63", "urn:knx:dpt.scaling", ROLE_BRIGHTNESS),
        ("dic:dpa.800.65", "urn:knx:dpt.scaling", ROLE_POSITION),
        ("dic:dpa.800.66", "urn:knx:dpt.scaling", ROLE_TILT),
        ("dic:dpa.801.61", "urn:knx:dpt.upDown", ROLE_MOVE),
        ("dic:dpa.399.56", "urn:knx:dpt.valueTemp", ROLE_TEMPERATURE),
        ("dic:dpa.392.52", "urn:knx:dpt.valueTemp", ROLE_SETPOINT),
        ("dic:dpa.399.50", "urn:knx:dpt.hvacOperationMode", ROLE_HVAC_MODE),
        ("dic:dpa.399.65", "urn:knx:dpt.scaling", ROLE_HEATING_DEMAND),
        ("dic:dpa.65533.51", "urn:knx:dpt.scaling", ROLE_BATTERY_LEVEL),
        ("dic:dpa.65533.52", "urn:knx:dpt.bool", ROLE_BATTERY_LOW),
        ("dic:dpa.65534.51", "urn:knx:dpt.airQuality", ROLE_CO2),
        ("dic:dpa.414.62", "urn:knx:dpt.valueLux", ROLE_ILLUMINANCE),
        ("dic:dpa.414.63", "urn:knx:dpt.startStop", ROLE_MOTION),
        ("dic:dpa.811.51", "urn:knx:dpt.openClose", ROLE_OPEN_CLOSE),
        ("dic:dpa.811.52", "urn:knx:dpt.doorControl", ROLE_LOCK_CONTROL),
        ("dic:dpa.812.51", "urn:knx:dpt.deviceStatus", ROLE_DEVICE_STATUS),
        ("dic:dpa.901.51", "urn:knx:dpt.power", ROLE_POWER),
        ("dic:dpa.810.51", "urn:knx:dpt.bool", ROLE_ALARM),
        ("dic:dpa.1010.54", "urn:knx:dpt.sceneControl", ROLE_SCENE),
    ],
)
def test_measured_archetypes_identify_the_slot(dpa, dpt, role):
    assert datapoint_role(_dp(dpa, dpt)) == role


def test_the_archetype_beats_the_datapoint_type():
    """Four roles share `dpt.scaling`: brightness, position, battery, demand."""
    battery = _dp("dic:dpa.65533.51", "urn:knx:dpt.scaling", unit="%")
    position = _dp("dic:dpa.800.65", "urn:knx:dpt.scaling", unit="%")
    assert datapoint_role(battery) == ROLE_BATTERY_LEVEL
    assert datapoint_role(position) == ROLE_POSITION


def test_the_title_never_decides():
    """A group object someone called "Alarm" is still a brightness slot."""
    dp = _dp("dic:dpa.418.63", "urn:knx:dpt.scaling", title="Alarm detection")
    assert datapoint_role(dp) == ROLE_BRIGHTNESS
    assert is_binary(datapoint_role(dp), dp) is False


def test_an_unknown_archetype_falls_back_to_the_datapoint_type():
    dp = {"types": ["dic:dpa.999.99", "urn:knx:dpt.switch"]}
    assert datapoint_role(dp) == ROLE_SWITCH


def test_an_unknown_datapoint_has_no_role():
    assert (
        datapoint_role({"types": ["dic:dpa.999.99", "urn:knx:dpt.somethingNew"]})
        is None
    )
    assert datapoint_role({}) is None


def test_binary_roles_and_measurements_are_told_apart():
    """The battery level and the battery alert differ by archetype, not title."""
    level = _dp("dic:dpa.65533.51", "urn:knx:dpt.scaling", unit="%", value="77")
    alert = _dp("dic:dpa.65533.52", "urn:knx:dpt.bool", value="false")
    assert is_binary(datapoint_role(level), level) is False
    assert is_binary(datapoint_role(alert), alert) is True


def test_a_unit_always_means_a_measurement():
    """A firmware that reuses an archetype must not produce a binary sensor."""
    dp = _dp("dic:dpa.810.51", "urn:knx:dpt.bool", unit="%", value="12")
    assert is_binary(datapoint_role(dp), dp) is False


def test_an_unknown_datapoint_is_binary_only_if_its_enum_says_so():
    openclose = {"types": ["dic:dpa.999.1"], "enum": ["open", "close"]}
    modes = {"types": ["dic:dpa.999.2"], "enum": ["auto", "comfort"]}
    assert is_binary(None, openclose) is True
    assert is_binary(None, modes) is False


@pytest.mark.parametrize(
    ("value", "state"),
    [
        ("on", True),
        ("off", False),
        ("online", True),
        ("offline", False),
        ("start", True),
        ("stop", False),
        ("open", True),
        ("close", False),
        ("true", True),
        ("false", False),
        ("ajar", None),
        (None, None),
    ],
)
def test_published_tokens_map_to_a_state(value, state):
    assert binary_state(value) is state


def test_values_are_parsed_not_rescaled():
    """A `dpt.scaling` raw 128 is published as 50; rescaling would give 19.6."""
    assert to_float("50") == 50.0
    assert to_float("") is None
    assert to_float(None) is None
    assert to_float("heat") is None


def test_se8000_temperatures_are_converted_back():
    """It publishes (bus - 32) x 5/9 and still labels the unit C."""
    se8000 = ["urn:knx:fct.se8000"]
    assert temperature_in(se8000, ROLE_TEMPERATURE, "0") == 32
    assert temperature_in(se8000, ROLE_TEMPERATURE, "-17.777777777778") == 0
    assert temperature_in(se8000, ROLE_TEMPERATURE, "37.777777777778") == 100
    # and a setpoint written in degrees goes out the same way round
    assert temperature_out(se8000, 32) == 0
    assert temperature_out(se8000, 100) == 37.78  # (100 - 32) x 5/9, to 2 places


def test_every_other_temperature_function_passes_through():
    for types in (["urn:knx:fct.temperatureAirFan"], ["urn:knx:fct.iTRV"], [], None):
        assert temperature_in(types, ROLE_TEMPERATURE, "21.5") == 21.5
        assert temperature_out(types, 21.5) == 21.5
