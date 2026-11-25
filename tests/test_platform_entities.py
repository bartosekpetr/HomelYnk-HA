"""The entities built from the datapoints the controller publishes.

Covers the places where the controller's model and Home Assistant's differ and
a plausible implementation would be wrong:

* a KNX height position counts how far a shutter has come *down*, Home
  Assistant how far it is *open*;
* `dpt.hvacOperationMode` is a preset, not an HVAC mode, and a thermostat's
  on/off is a different archetype from its fan manual mode;
* `fct.se8000` publishes temperatures through an F->C conversion and still
  labels them `C`;
* a smart lock's `ajar` is neither locked nor unlocked.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import LIGHT_LUX

from custom_components.wiser_for_knx.binary_sensor import WiserKnxBinarySensor
from custom_components.wiser_for_knx.climate import WiserKnxClimate
from custom_components.wiser_for_knx.cover import WiserKnxCover
from custom_components.wiser_for_knx.light import WiserKnxLight
from custom_components.wiser_for_knx.lock import WiserKnxLock
from custom_components.wiser_for_knx.select import WiserKnxSelect
from custom_components.wiser_for_knx.sensor import WiserKnxDatapointSensor


def _dp(dp_id, dpa, dpt, writable=False, **kwargs):
    return {
        "id": dp_id,
        "title": dp_id,
        "types": [dpa, dpt],
        "writable": writable,
        "unit": kwargs.pop("unit", ""),
        "value": kwargs.pop("value", None),
        **kwargs,
    }


def _coordinator(types, *datapoints):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.async_write_datapoint = AsyncMock(return_value=True)
    coordinator.data = {
        "functions": {
            "f1": {
                "id": "f1",
                "title": "Device",
                "types": types,
                "datapoints": {dp["id"]: dp for dp in datapoints},
            }
        },
        "locations": {},
        "datapoints": {dp["id"]: dp for dp in datapoints},
    }
    return coordinator


def _composite(cls, types, *datapoints):
    return cls(_coordinator(types, *datapoints), "entry1", "f1")


def _datapoint_entity(cls, types, dp, **spec):
    coordinator = _coordinator(types, dp)
    return cls(
        coordinator,
        "entry1",
        {"function_id": "f1", "datapoint_id": dp["id"], "role": None, **spec},
    )


def _written(entity):
    return entity.coordinator.async_write_datapoint.await_args_list


# --- cover -----------------------------------------------------------------

POSITION = _dp(
    "pos", "dic:dpa.800.65", "urn:knx:dpt.scaling", True, unit="%", value="30"
)
SLAT = _dp("slat", "dic:dpa.800.66", "urn:knx:dpt.scaling", True, unit="%", value="0")
MOVE = _dp("move", "dic:dpa.801.61", "urn:knx:dpt.upDown", True, enum=["down", "up"])
MOVING = _dp(
    "moving", "dic:dpa.801.90", "urn:knx:dpt.startStop", enum=["start", "stop"]
)
DIRECTION = _dp("dir", "dic:dpa.801.91", "urn:knx:dpt.upDown", enum=["down", "up"])


def test_a_knx_height_position_is_inverted_for_home_assistant():
    """30 % down the way KNX counts it is 70 % open the way HA does."""
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION)
    assert cover.current_cover_position == 70
    assert cover.is_closed is False

    asyncio.run(cover.async_set_cover_position(position=25))
    assert _written(cover)[0].args == ("pos", 75)


def test_a_fully_closed_cover_reports_closed():
    closed = _dp(
        "pos", "dic:dpa.800.65", "urn:knx:dpt.scaling", True, unit="%", value="100"
    )
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], closed)
    assert cover.current_cover_position == 0
    assert cover.is_closed is True


def test_a_cover_with_only_a_movement_object_does_not_guess_its_state():
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], MOVE)
    assert cover.current_cover_position is None
    assert cover.is_closed is None
    features = cover.supported_features
    assert features & CoverEntityFeature.OPEN
    assert not features & CoverEntityFeature.SET_POSITION


def test_a_cover_prefers_its_movement_object_for_open_and_close():
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, MOVE)
    asyncio.run(cover.async_open_cover())
    asyncio.run(cover.async_close_cover())
    assert [call.args for call in _written(cover)] == [("move", "up"), ("move", "down")]


def test_a_cover_without_a_movement_object_opens_by_position():
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION)
    asyncio.run(cover.async_open_cover())
    assert _written(cover)[0].args == ("pos", 0)


def test_stop_writes_the_member_that_puts_a_zero_on_the_bus():
    """`decrease` is raw 0 on a `dpt.step`, and raw 0 is what stop means.

    Measured 2026-11-22: through the API `increase` put raw `01` on the stop
    group object and `decrease` raw `00`, and all three of the vendor's own
    shutter widgets write literal `0` to that slot from their stop button.
    """
    stop = _dp(
        "stop",
        "dic:dpa.801.62",
        "urn:knx:dpt.step",
        True,
        enum=["increase", "decrease"],
    )
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, stop)
    assert cover.supported_features & CoverEntityFeature.STOP

    asyncio.run(cover.async_stop_cover())
    assert _written(cover)[0].args == ("stop", "decrease")


def test_stop_is_not_advertised_when_no_member_of_the_enum_was_measured():
    """An unmeasured spelling is left alone rather than guessed at.

    The controller answers 202 to any well-formed write and then discards a
    value that is not a member verbatim, and on a shutter the cost of guessing
    is movement rather than a no-op.
    """
    stop = _dp(
        "stop",
        "dic:dpa.801.62",
        "urn:knx:dpt.step",
        True,
        enum=["schritt-auf", "schritt-ab"],
    )
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, stop)
    assert not cover.supported_features & CoverEntityFeature.STOP

    asyncio.run(cover.async_stop_cover())
    assert _written(cover) == []


def test_a_read_only_stop_slot_is_not_a_stop_button():
    stop = _dp(
        "stop",
        "dic:dpa.801.62",
        "urn:knx:dpt.step",
        False,
        enum=["increase", "decrease"],
    )
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, stop)
    assert not cover.supported_features & CoverEntityFeature.STOP


def test_slats_are_a_tilt_position():
    cover = _composite(WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, SLAT)
    assert cover.supported_features & CoverEntityFeature.SET_TILT_POSITION
    assert cover.current_cover_tilt_position == 100
    asyncio.run(cover.async_set_cover_tilt_position(tilt_position=40))
    assert _written(cover)[0].args == ("slat", 60)


def test_movement_needs_both_the_moving_flag_and_the_direction():
    moving = dict(MOVING, value="start")
    going_up = dict(DIRECTION, value="up")
    cover = _composite(
        WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, moving, going_up
    )
    assert cover.is_opening is True
    assert cover.is_closing is False

    only_moving = _composite(
        WiserKnxCover, ["urn:knx:fct.blindsVertical"], POSITION, moving
    )
    assert only_moving.is_opening is None


# --- climate ---------------------------------------------------------------

TEMP = _dp("temp", "dic:dpa.399.56", "urn:knx:dpt.valueTemp", unit="C", value="21.5")
SETPOINT = _dp(
    "set",
    "dic:dpa.392.52",
    "urn:knx:dpt.valueTemp",
    True,
    unit="C",
    value="22",
    minimum="5",
    maximum="30",
)
HVAC = _dp(
    "hvac",
    "dic:dpa.399.50",
    "urn:knx:dpt.hvacOperationMode",
    True,
    enum=["auto", "comfort", "standby", "economy", "buildingProtection"],
    value="comfort",
)
HEAT_COOL = _dp(
    "hc",
    "dic:dpa.399.64",
    "urn:knx:dpt.heatCool",
    True,
    enum=["heat", "cool"],
    value="heat",
)
THERMOSTAT_SWITCH = _dp(
    "onoff",
    "dic:dpa.417.72",
    "urn:knx:dpt.switch",
    True,
    enum=["on", "off"],
    value="on",
)
FAN_MANUAL = _dp(
    "fanman",
    "dic:dpa.417.70",
    "urn:knx:dpt.switch",
    True,
    enum=["on", "off"],
    value="off",
)


def test_a_thermostat_reports_its_temperatures_and_limits():
    climate = _composite(
        WiserKnxClimate, ["urn:knx:fct.temperatureAirFan"], TEMP, SETPOINT
    )
    assert climate.current_temperature == 21.5
    assert climate.target_temperature == 22
    assert (climate.min_temp, climate.max_temp) == (5, 30)
    assert climate.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE

    asyncio.run(climate.async_set_temperature(temperature=23.5))
    assert _written(climate)[0].args == ("set", 23.5)


def test_the_operation_mode_is_a_preset_not_an_hvac_mode():
    climate = _composite(
        WiserKnxClimate, ["urn:knx:fct.temperatureAirFan"], TEMP, SETPOINT, HVAC
    )
    assert climate.preset_mode == "comfort"
    assert "eco" in climate.preset_modes
    assert climate.hvac_modes == [HVACMode.HEAT]

    asyncio.run(climate.async_set_preset_mode("eco"))
    # written back as the controller spells it, not as Home Assistant does
    assert _written(climate)[0].args == ("hvac", "economy")


def test_heating_cooling_and_the_thermostat_switch_make_the_hvac_mode():
    climate = _composite(
        WiserKnxClimate,
        ["urn:knx:fct.temperatureAirFan"],
        TEMP,
        SETPOINT,
        HEAT_COOL,
        THERMOSTAT_SWITCH,
    )
    assert set(climate.hvac_modes) == {HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF}
    assert climate.hvac_mode == HVACMode.HEAT

    asyncio.run(climate.async_set_hvac_mode(HVACMode.COOL))
    assert [call.args for call in _written(climate)] == [
        ("onoff", "on"),
        ("hc", "cool"),
    ]


def test_turning_a_thermostat_off_does_not_touch_its_fan():
    """Both are writable `dpt.switch`; only `dpa.417.72` is the thermostat."""
    climate = _composite(
        WiserKnxClimate,
        ["urn:knx:fct.temperatureAirFan"],
        TEMP,
        SETPOINT,
        FAN_MANUAL,
        THERMOSTAT_SWITCH,
    )
    asyncio.run(climate.async_set_hvac_mode(HVACMode.OFF))
    assert _written(climate)[0].args == ("onoff", "off")

    off = dict(THERMOSTAT_SWITCH, value="off")
    stopped = _composite(
        WiserKnxClimate, ["urn:knx:fct.temperatureAirFan"], TEMP, SETPOINT, off
    )
    assert stopped.hvac_mode == HVACMode.OFF


def test_an_se8000_thermostat_is_read_and_written_in_real_degrees():
    """It publishes (bus - 32) x 5/9 while labelling the unit C."""
    temp = _dp("temp", "dic:dpa.399.56", "urn:knx:dpt.valueTemp", unit="C", value="0")
    setpoint = _dp(
        "set", "dic:dpa.392.52", "urn:knx:dpt.valueTemp", True, unit="C", value="0"
    )
    climate = _composite(WiserKnxClimate, ["urn:knx:fct.se8000"], temp, setpoint)
    assert climate.current_temperature == 32
    asyncio.run(climate.async_set_temperature(temperature=32))
    assert _written(climate)[0].args == ("set", 0)


def test_a_fan_mode_datapoint_becomes_fan_modes():
    fan = _dp(
        "fan",
        "dic:dpa.399.75",
        "urn:knx:dpt.se8000Fan",
        True,
        enum=["Low", "Med", "High"],
        value="Low",
    )
    climate = _composite(WiserKnxClimate, ["urn:knx:fct.se8000"], TEMP, SETPOINT, fan)
    assert climate.fan_modes == ["Low", "Med", "High"]
    assert climate.supported_features & ClimateEntityFeature.FAN_MODE
    asyncio.run(climate.async_set_fan_mode("High"))
    assert _written(climate)[0].args == ("fan", "High")


# --- lock ------------------------------------------------------------------


def test_a_lock_reports_locked_unlocked_and_neither():
    control = _dp(
        "ctl",
        "dic:dpa.811.52",
        "urn:knx:dpt.doorControl",
        True,
        enum=["lock", "unlock"],
    )
    for value, expected in (("locked", True), ("unlocked", False), ("ajar", None)):
        state = _dp(
            "state",
            "dic:dpa.811.53",
            "urn:knx:dpt.lockState",
            enum=["ajar", "locked", "unlocked"],
            value=value,
        )
        lock = _composite(WiserKnxLock, ["urn:knx:fct.smartLock"], control, state)
        assert lock.is_locked is expected

    lock = _composite(WiserKnxLock, ["urn:knx:fct.smartLock"], control)
    asyncio.run(lock.async_lock())
    asyncio.run(lock.async_unlock())
    assert [call.args for call in _written(lock)] == [
        ("ctl", "lock"),
        ("ctl", "unlock"),
    ]


# --- light -----------------------------------------------------------------


def test_an_rgbw_light_reads_and_writes_its_channels_as_percentages():
    channels = [
        _dp("r", "dic:dpa.423.58", "urn:knx:dpt.scaling", True, unit="%", value="100"),
        _dp("g", "dic:dpa.423.61", "urn:knx:dpt.scaling", True, unit="%", value="0"),
        _dp("b", "dic:dpa.423.64", "urn:knx:dpt.scaling", True, unit="%", value="0"),
        _dp("w", "dic:dpa.424.67", "urn:knx:dpt.scaling", True, unit="%", value="50"),
    ]
    light = _composite(WiserKnxLight, ["urn:knx:fct.colorRGBW"], *channels)
    assert light.rgb_color == (255, 0, 0)
    assert light.rgbw_color == (255, 0, 0, 127)
    assert light.is_on is True

    asyncio.run(light.async_turn_on(rgbw_color=(0, 255, 0, 0)))
    assert [call.args for call in _written(light)] == [
        ("r", 0),
        ("g", 100),
        ("b", 0),
        ("w", 0),
    ]


def test_the_lowest_home_assistant_brightness_dims_instead_of_switching_off():
    """HA brightness 1 is 0.4 %, which truncates to 0 - and 0 % is off.

    So the minimum a user can ask for on the slider must still reach the
    controller as a dim light, not as a light that went out.
    """
    dimmer = _dp(
        "dim", "dic:dpa.418.63", "urn:knx:dpt.scaling", True, unit="%", value="50"
    )
    light = _composite(WiserKnxLight, ["urn:knx:fct.dimming"], dimmer)

    asyncio.run(light.async_turn_on(brightness=1))
    assert _written(light)[0].args == ("dim", 1)

    asyncio.run(light.async_turn_on(brightness=128))
    assert _written(light)[1].args == ("dim", 50)

    asyncio.run(light.async_turn_on(brightness=255))
    assert _written(light)[2].args == ("dim", 100)

    asyncio.run(light.async_turn_off())
    assert _written(light)[3].args == ("dim", 0)


def test_an_rgb_light_parses_the_hex_triplet_it_publishes():
    rgb = _dp(
        "rgb", "dic:dpa.423.52", "urn:knx:dpt.R-G-B", True, unit="3BHEX", value="FF8000"
    )
    light = _composite(WiserKnxLight, ["urn:knx:fct.colorRGB"], rgb)
    assert light.rgb_color == (255, 128, 0)
    asyncio.run(light.async_turn_on(rgb_color=(0, 16, 255)))
    assert _written(light)[0].args == ("rgb", "0010FF")


def test_a_colour_value_that_is_not_a_triplet_is_not_guessed_at():
    rgb = _dp("rgb", "dic:dpa.423.52", "urn:knx:dpt.R-G-B", True, value="nonsense")
    light = _composite(WiserKnxLight, ["urn:knx:fct.colorRGB"], rgb)
    assert light.rgb_color is None


# --- datapoint entities ----------------------------------------------------


def test_a_device_status_datapoint_is_connectivity_not_a_problem():
    dp = _dp(
        "status",
        "dic:dpa.812.51",
        "urn:knx:dpt.deviceStatus",
        enum=["offline", "online"],
        value="online",
    )
    entity = _datapoint_entity(
        WiserKnxBinarySensor, ["urn:knx:fct.switching"], dp, role="device_status"
    )
    assert entity.is_on is True
    assert entity.device_class is BinarySensorDeviceClass.CONNECTIVITY

    entity.datapoint["value"] = "offline"
    assert entity.is_on is False


def test_an_alarm_datapoints_class_comes_from_its_function():
    dp = _dp(
        "alarm",
        "dic:dpa.806.51",
        "urn:knx:dpt.bool",
        enum=["true", "false"],
        value="true",
    )
    entity = _datapoint_entity(
        WiserKnxBinarySensor, ["urn:knx:fct.alarmWater"], dp, role="alarm"
    )
    assert entity.is_on is True
    assert entity.device_class is BinarySensorDeviceClass.MOISTURE


def test_a_sensor_datapoint_is_parsed_and_given_the_right_unit():
    lux = _dp("lux", "dic:dpa.414.62", "urn:knx:dpt.valueLux", value="2200.32")
    entity = _datapoint_entity(
        WiserKnxDatapointSensor,
        ["urn:knx:fct.movementDetector"],
        lux,
        role="illuminance",
    )
    assert entity.native_value == 2200.32
    assert entity.native_unit_of_measurement is LIGHT_LUX
    assert entity.device_class is SensorDeviceClass.ILLUMINANCE


def test_an_enum_sensor_publishes_its_options():
    door = _dp(
        "door",
        "dic:dpa.811.54",
        "urn:knx:dpt.doorState",
        enum=["open", "closed", "jammed"],
        value="closed",
    )
    entity = _datapoint_entity(
        WiserKnxDatapointSensor, ["urn:knx:fct.smartLock"], door, role="door_state"
    )
    assert entity.native_value == "closed"
    assert entity.options == ["open", "closed", "jammed"]


def test_a_select_writes_the_enum_member_verbatim():
    stop = _dp(
        "stop",
        "dic:dpa.801.62",
        "urn:knx:dpt.step",
        True,
        enum=["increase", "decrease"],
        value="increase",
    )
    entity = _datapoint_entity(
        WiserKnxSelect, ["urn:knx:fct.blindsVertical"], stop, role="stop"
    )
    assert entity.options == ["increase", "decrease"]
    assert entity.current_option == "increase"
    asyncio.run(entity.async_select_option("decrease"))
    assert _written(entity)[0].args == ("stop", "decrease")


def test_a_datapoint_entity_is_unavailable_while_it_is_not_published():
    """A function arrives before its datapoints, and 15 s later they attach."""
    dp = _dp("temp", "dic:dpa.399.56", "urn:knx:dpt.valueTemp", value="21")
    entity = _datapoint_entity(
        WiserKnxDatapointSensor, ["urn:knx:fct.airQuality"], dp, role="temperature"
    )
    assert entity.available is True
    entity.coordinator.data["functions"]["f1"]["datapoints"] = {}
    assert entity.available is False
    assert entity.native_value is None
