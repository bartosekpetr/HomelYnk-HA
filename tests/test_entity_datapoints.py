"""Which datapoint a light or switch controls, and when it has none (SMA-59).

A widget's control and status slots collapse into one datapoint on this
controller: the value is the status object and a write to it drives the control
object. Measured facts behind these tests:

* titles are user-defined KNX group object names, so the datapoint type has to
  decide before any title heuristic;
* a socket publishes its active power as a read-only `dpt.power` in W next to
  the switch, and a dimmer its brightness as `dpt.scaling` in `%`;
* brightness is published in percent, not as the raw 0-255 KNX byte;
* a function is published up to minutes before its datapoints after a config
  change, so "function without datapoints" is a real, temporary state.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.wiser_for_knx.light import WiserKnxLight
from custom_components.wiser_for_knx.switch import WiserKnxSwitch

SWITCH_DP = {
    "id": "dp-switch",
    "title": "Lamp on/off",
    "types": ["urn:knx:dpt.switch"],
    "value": "off",
    "writable": True,
    "unit": "",
}
POWER_DP = {
    "id": "dp-power",
    "title": "Active power status",
    "types": ["urn:knx:dpt.power"],
    "value": "41.5",
    "writable": False,
    "unit": "W",
}
BRIGHTNESS_DP = {
    "id": "dp-brightness",
    "title": "Dimm value status",
    "types": ["urn:knx:dpt.scaling"],
    "value": "50",
    "writable": True,
    "unit": "%",
}


def _entity(cls, *datapoints):
    """Return an entity whose function owns the given datapoints, in that order."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.async_write_datapoint = AsyncMock(return_value=True)
    coordinator.data = {
        "functions": {
            "f1": {
                "id": "f1",
                "title": "Kitchen",
                "datapoints": {dp["id"]: dp for dp in datapoints},
            }
        },
        "locations": {},
        "datapoints": {dp["id"]: dp for dp in datapoints},
    }
    return cls(coordinator, "entry1", "f1")


@pytest.mark.parametrize("cls", [WiserKnxLight, WiserKnxSwitch])
def test_a_measurement_is_never_the_control_datapoint(cls):
    """The power reading is listed first and its title even matches "status"."""
    entity = _entity(cls, POWER_DP, SWITCH_DP)
    assert entity._get_switch_dp()["id"] == "dp-switch"


@pytest.mark.parametrize("cls", [WiserKnxLight, WiserKnxSwitch])
def test_a_power_only_function_has_no_control_datapoint(cls):
    entity = _entity(cls, POWER_DP)
    assert entity._get_switch_dp() is None
    assert entity.is_on is False


@pytest.mark.parametrize("cls", [WiserKnxLight, WiserKnxSwitch])
def test_the_datapoint_type_decides_before_the_title(cls):
    """A group object someone called "On off status" must not beat a dpt.switch."""
    decoy = {
        "id": "dp-decoy",
        "title": "On off status",
        "types": ["urn:knx:dpt.value1Ucount"],
        "value": "3",
        "writable": True,
        "unit": "",
    }
    entity = _entity(cls, decoy, SWITCH_DP)
    assert entity._get_switch_dp()["id"] == "dp-switch"


@pytest.mark.parametrize("cls", [WiserKnxLight, WiserKnxSwitch])
def test_a_function_without_datapoints_is_unavailable(cls):
    """Reporting unavailable beats an entity that reads "off" and ignores commands."""
    entity = _entity(cls)
    assert entity.available is False
    assert _entity(cls, SWITCH_DP).available is True


def test_a_dimmer_without_a_switch_object_is_driven_by_brightness():
    """The brightness datapoint is in percent, so it is not an on/off slot."""
    light = _entity(WiserKnxLight, BRIGHTNESS_DP)
    assert light._get_switch_dp() is None
    assert light._get_brightness_dp()["id"] == "dp-brightness"
    assert light.is_on is True
    assert light.brightness == 127

    asyncio.run(light.async_turn_off())
    light.coordinator.async_write_datapoint.assert_awaited_once_with("dp-brightness", 0)


def test_a_dimmer_writes_brightness_as_a_percentage():
    """A raw 0-255 value would be wrong by a factor of 2.55 on the controller."""
    light = _entity(WiserKnxLight, SWITCH_DP, BRIGHTNESS_DP)
    asyncio.run(light.async_turn_on(brightness=255))
    light.coordinator.async_write_datapoint.assert_awaited_once_with(
        "dp-brightness", 100
    )


def test_a_dimmer_turns_on_through_its_switch_object():
    light = _entity(WiserKnxLight, SWITCH_DP, BRIGHTNESS_DP)
    assert light._get_switch_dp()["id"] == "dp-switch"
    asyncio.run(light.async_turn_on())
    light.coordinator.async_write_datapoint.assert_awaited_once_with("dp-switch", "on")
