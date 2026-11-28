"""Which entities a function becomes.

The functions below are the shapes the controller published in the widget
matrix: a socket with active power, a dimmer, a fully configured vertical
shutter, a thermostat, a motion sensor, a smart lock, a scene and the two
degenerate cases that must not become composites (`fct.temperatureAir` with
nothing but a reading, `fct.iTRV` with nothing but a heating demand).
"""

from custom_components.wiser_for_knx.plan import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_BUTTON,
    PLATFORM_CLIMATE,
    PLATFORM_COVER,
    PLATFORM_LIGHT,
    PLATFORM_LOCK,
    PLATFORM_NUMBER,
    PLATFORM_SELECT,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    plan_entities,
)


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


def _func(func_id, types, *datapoints):
    return {
        func_id: {
            "id": func_id,
            "title": func_id,
            "types": types,
            "datapoints": {dp["id"]: dp for dp in datapoints},
        }
    }


def _keys(plan, platform):
    return sorted(spec["key"] for spec in plan.get(platform, []))


def test_a_socket_is_a_switch_and_its_power_is_a_sensor():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.switchingSocket"],
            _dp("sw", "dic:dpa.417.70", "urn:knx:dpt.switch", True, value="on"),
            _dp("pw", "dic:dpa.901.51", "urn:knx:dpt.power", unit="W", value="41.5"),
        )
    )
    assert _keys(plan, PLATFORM_SWITCH) == ["f1"]
    assert _keys(plan, PLATFORM_SENSOR) == ["pw"]


def test_a_dimmer_consumes_both_of_its_datapoints():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.dimming"],
            _dp("sw", "dic:dpa.418.61", "urn:knx:dpt.switch", True, value="on"),
            _dp(
                "br",
                "dic:dpa.418.63",
                "urn:knx:dpt.scaling",
                True,
                unit="%",
                value="50",
            ),
        )
    )
    assert _keys(plan, PLATFORM_LIGHT) == ["f1"]
    assert plan.get(PLATFORM_SENSOR) is None
    assert plan.get(PLATFORM_NUMBER) is None


def test_a_full_shutter_keeps_its_extra_slots_as_their_own_entities():
    """7 datapoints, which is what a full `se-shutter-vertical` really exports.

    Measured live on 2026-11-22: the two control slots collapse into their
    status datapoints, so the cover takes position, slats, movement and stop,
    and what is left is the three diagnostics. `height-invert` exports nothing
    at all.
    """
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.blindsVertical"],
            _dp(
                "pos",
                "dic:dpa.800.65",
                "urn:knx:dpt.scaling",
                True,
                unit="%",
                value="0",
            ),
            _dp(
                "slat",
                "dic:dpa.800.66",
                "urn:knx:dpt.scaling",
                True,
                unit="%",
                value="0",
            ),
            _dp(
                "move",
                "dic:dpa.801.61",
                "urn:knx:dpt.upDown",
                True,
                enum=["down", "up"],
            ),
            _dp(
                "stop",
                "dic:dpa.801.62",
                "urn:knx:dpt.step",
                True,
                enum=["increase", "decrease"],
            ),
            _dp(
                "moving",
                "dic:dpa.801.90",
                "urn:knx:dpt.startStop",
                enum=["start", "stop"],
            ),
            _dp("dir", "dic:dpa.801.91", "urn:knx:dpt.upDown", enum=["down", "up"]),
            _dp(
                "status",
                "dic:dpa.812.51",
                "urn:knx:dpt.deviceStatus",
                enum=["offline", "online"],
            ),
        )
    )
    assert _keys(plan, PLATFORM_COVER) == ["f1"]
    # The stop object is the cover's STOP now that its bus value is measured,
    # so it is no longer offered as a select of increase/decrease.
    assert plan.get(PLATFORM_SELECT) is None
    assert _keys(plan, PLATFORM_BINARY_SENSOR) == ["moving", "status"]
    # "last direction" is down/up, which is not an on/off state - it is an enum
    assert _keys(plan, PLATFORM_SENSOR) == ["dir"]


def test_a_thermostat_is_a_climate_entity_with_its_batteries_alongside():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.temperatureAirFan"],
            _dp(
                "temp",
                "dic:dpa.399.56",
                "urn:knx:dpt.valueTemp",
                unit="C",
                value="21.5",
            ),
            _dp(
                "set",
                "dic:dpa.392.52",
                "urn:knx:dpt.valueTemp",
                True,
                unit="C",
                value="22",
            ),
            _dp(
                "hvac",
                "dic:dpa.399.50",
                "urn:knx:dpt.hvacOperationMode",
                True,
                enum=["auto", "comfort", "standby", "economy", "buildingProtection"],
            ),
            _dp(
                "hc",
                "dic:dpa.399.64",
                "urn:knx:dpt.heatCool",
                True,
                enum=["heat", "cool"],
            ),
            _dp(
                "onoff",
                "dic:dpa.417.72",
                "urn:knx:dpt.switch",
                True,
                enum=["on", "off"],
            ),
            _dp("fan", "dic:dpa.399.74", "urn:knx:dpt.scaling", True, value="0"),
            _dp(
                "batt", "dic:dpa.65533.51", "urn:knx:dpt.scaling", unit="%", value="90"
            ),
            _dp(
                "demand", "dic:dpa.399.65", "urn:knx:dpt.scaling", unit="%", value="30"
            ),
            _dp("dew", "dic:dpa.344.51", "urn:knx:dpt.bool", value="false"),
        )
    )
    assert _keys(plan, PLATFORM_CLIMATE) == ["f1"]
    # the fan percentage is writable but not a fan *mode*, so it is a number
    assert _keys(plan, PLATFORM_NUMBER) == ["fan"]
    assert _keys(plan, PLATFORM_SENSOR) == ["batt", "demand"]
    assert _keys(plan, PLATFORM_BINARY_SENSOR) == ["dew"]


def test_a_bare_temperature_reading_is_not_a_thermostat():
    """`se-danfoss-thermostat` publishes `fct.temperatureAir` with one reading."""
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.temperatureAir"],
            _dp(
                "temp", "dic:dpa.399.56", "urn:knx:dpt.valueTemp", unit="C", value="21"
            ),
        )
    )
    assert plan.get(PLATFORM_CLIMATE) is None
    assert _keys(plan, PLATFORM_SENSOR) == ["temp"]


def test_a_valve_drive_demand_is_not_a_thermostat():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.iTRV"],
            _dp(
                "demand", "dic:dpa.399.65", "urn:knx:dpt.scaling", unit="%", value="30"
            ),
        )
    )
    assert plan.get(PLATFORM_CLIMATE) is None
    assert _keys(plan, PLATFORM_SENSOR) == ["demand"]


def test_a_function_without_datapoints_yet_produces_nothing():
    """Measured: a function is published 2-13 s before its datapoints."""
    plan = plan_entities(_func("f1", ["urn:knx:fct.switchingLight"]))
    assert plan == {}


def test_an_alarm_and_a_motion_sensor_become_binary_sensors():
    plan = plan_entities(
        {
            **_func(
                "f1",
                ["urn:knx:fct.alarmWater"],
                _dp(
                    "alarm",
                    "dic:dpa.806.51",
                    "urn:knx:dpt.bool",
                    enum=["true", "false"],
                ),
                _dp(
                    "batt",
                    "dic:dpa.65533.51",
                    "urn:knx:dpt.scaling",
                    unit="%",
                    value="80",
                ),
            ),
            **_func(
                "f2",
                ["urn:knx:fct.movementDetector"],
                _dp(
                    "det",
                    "dic:dpa.414.63",
                    "urn:knx:dpt.startStop",
                    enum=["start", "stop"],
                ),
                _dp("lux", "dic:dpa.414.62", "urn:knx:dpt.valueLux", value="2200"),
            ),
        }
    )
    assert _keys(plan, PLATFORM_BINARY_SENSOR) == ["alarm", "det"]
    assert _keys(plan, PLATFORM_SENSOR) == ["batt", "lux"]


def test_a_smart_lock_is_a_lock_and_the_door_state_is_a_sensor():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.smartLock"],
            _dp(
                "ctl",
                "dic:dpa.811.52",
                "urn:knx:dpt.doorControl",
                True,
                enum=["lock", "unlock"],
            ),
            _dp(
                "state",
                "dic:dpa.811.53",
                "urn:knx:dpt.lockState",
                enum=["ajar", "locked", "unlocked"],
                value="locked",
            ),
            _dp(
                "door",
                "dic:dpa.811.54",
                "urn:knx:dpt.doorState",
                enum=["open", "closed", "jammed", "forced", "unspecified"],
                value="closed",
            ),
        )
    )
    assert _keys(plan, PLATFORM_LOCK) == ["f1"]
    assert _keys(plan, PLATFORM_SENSOR) == ["door"]


def test_a_scene_becomes_one_button_per_published_number():
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.scene"],
            _dp(
                "sc",
                "dic:dpa.1010.54",
                "urn:knx:dpt.sceneControl",
                True,
                enum=["1", "2"],
            ),
        )
    )
    assert _keys(plan, PLATFORM_BUTTON) == ["sc_1", "sc_2"]
    assert [spec["value"] for spec in plan[PLATFORM_BUTTON]] == ["1", "2"]


def test_the_automation_trigger_virtuals_are_skipped():
    """Every subscription carries these two; they are not devices."""
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.alarmAutomation"],
            _dp("t1", "dic:dpa.999.99", "urn:knx:dpt.uuid", value="0000"),
        )
    )
    assert plan == {}


def test_a_lone_status_datapoint_still_becomes_a_sensor():
    """A function the classifier calls a switch but that cannot be written."""
    plan = plan_entities(
        _func(
            "f1",
            ["urn:knx:fct.switching"],
            _dp("sw", "dic:dpa.417.70", "urn:knx:dpt.switch", False, value="on"),
        )
    )
    assert plan.get(PLATFORM_SWITCH) is None
    assert _keys(plan, PLATFORM_BINARY_SENSOR) == ["sw"]


# --- the gauge --------------------------------------------------------------
#
# A gauge publishes one read-only `dic:dpa.417.65` datapoint whatever is wired
# to it, and says what it measures - when it has been configured to - in a
# second function `@type` composed from its `gauge-device` setting. The whole
# decision is in `datapoints.FCT_GAUGE_ROLES`; what matters here is that it
# changes the role and nothing else, because an entity that moved platform
# would arrive as a second entity beside the one it replaced.


def _gauge(*types):
    return _func(
        "f1",
        ["urn:knx:fct.gauge", *types],
        _dp("g", "dic:dpa.417.65", "urn:knx:dpt.generic", False, value="41.8"),
    )


def test_a_configured_gauge_keeps_its_platform_and_gains_its_role():
    plan = plan_entities(_gauge("urn:knx:fct.schneider.weather.humiditySensor"))
    assert _keys(plan, PLATFORM_SENSOR) == ["g"]
    assert plan[PLATFORM_SENSOR][0]["role"] == "humidity"
    assert plan[PLATFORM_SENSOR][0]["diagnostic"] is False


def test_an_unconfigured_gauge_is_the_plain_sensor_it_has_always_been():
    plan = plan_entities(_gauge("urn:knx:fct.schneider.generic"))
    assert _keys(plan, PLATFORM_SENSOR) == ["g"]
    assert plan[PLATFORM_SENSOR][0]["role"] == "value"


def test_a_gauge_named_after_a_device_type_is_still_one_sensor():
    """`fct.schneider.device.<name>` is free text, and the name is hostile here.

    `classify_function` reads "Temperature" as a climate function; the datapoint
    is read-only, so no composite is viable and the degradation contract gives
    exactly one sensor - with no device class, because an unvalidated string
    must not pick one.
    """
    plan = plan_entities(_gauge("urn:knx:fct.schneider.device.Temperature"))
    assert list(plan) == [PLATFORM_SENSOR]
    assert plan[PLATFORM_SENSOR][0]["role"] == "value"
