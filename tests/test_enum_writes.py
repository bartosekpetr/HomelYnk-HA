"""Enum datapoints are written with their own members, verbatim (SMA-59).

The controller answers 202 to any well-formed write and then silently discards a
value that is not a member of the datapoint's `enum`: measured on one writable
switch datapoint, `on` produced a KNX telegram while `1` and `true` produced
nothing at all. The HTTP status cannot tell the two apart, so the value has to be
matched against what the datapoint published.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator


def _coordinator(enum=None, value="off"):
    client = MagicMock()
    client.write_datapoint_value = AsyncMock(return_value=True)
    coordinator = WiserKnxDataUpdateCoordinator(MagicMock(), client, MagicMock())
    datapoint = {"id": "dp1", "value": value}
    if enum is not None:
        datapoint["enum"] = enum
    coordinator.data = {"datapoints": {"dp1": datapoint}}
    coordinator.async_update_listeners = MagicMock()
    return coordinator


def _written(coordinator):
    return coordinator.client.write_datapoint_value.await_args.args[1]


@pytest.mark.parametrize(
    ("members", "requested", "expected"),
    [
        (["On", "Off"], "on", "On"),
        (["On", "Off"], True, "On"),
        (["On", "Off"], False, "Off"),
        (["on", "off"], "on", "on"),
        (["ON", "OFF"], "off", "OFF"),
        (["Enabled", "Disabled"], "enabled", "Enabled"),
    ],
)
def test_the_datapoints_own_spelling_is_sent(members, requested, expected):
    coordinator = _coordinator(enum=members)
    assert asyncio.run(coordinator.async_write_datapoint("dp1", requested)) is True
    assert _written(coordinator) == expected


def test_the_optimistic_state_uses_the_same_member():
    """Local state and the request must not diverge over spelling."""
    coordinator = _coordinator(enum=["On", "Off"])
    asyncio.run(coordinator.async_write_datapoint("dp1", True))
    assert coordinator.data["datapoints"]["dp1"]["value"] == "On"


@pytest.mark.parametrize("enum", [None, []])
def test_a_datapoint_without_an_enum_is_written_unchanged(enum, caplog):
    """Brightness and the other numeric datapoints publish no enum at all."""
    coordinator = _coordinator(enum=enum)
    with caplog.at_level(logging.WARNING):
        asyncio.run(coordinator.async_write_datapoint("dp1", 40))

    assert _written(coordinator) == 40
    assert not caplog.records


def test_a_value_outside_the_enum_is_sent_anyway_and_logged(caplog):
    """Nothing else reports it: the controller answers 202 and drops the write.

    The value is still sent: the enum is what the datapoint published, not a
    schema, so refusing the write locally could break a case not measured here.
    """
    coordinator = _coordinator(enum=["On", "Off"])
    with caplog.at_level(logging.WARNING):
        asyncio.run(coordinator.async_write_datapoint("dp1", "1"))

    assert _written(coordinator) == "1"
    assert [r for r in caplog.records if "discard" in r.getMessage()]


def test_an_unknown_datapoint_is_written_unchanged():
    coordinator = _coordinator(enum=["On", "Off"])
    asyncio.run(coordinator.async_write_datapoint("dp-other", "on"))
    assert _written(coordinator) == "on"


def test_non_string_enum_members_are_ignored():
    """Defensive: the enum is documented as strings; a stray value must not crash."""
    coordinator = _coordinator(enum=[1, None])
    asyncio.run(coordinator.async_write_datapoint("dp1", "on"))
    assert _written(coordinator) == "on"
