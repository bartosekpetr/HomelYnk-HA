"""Optimistic datapoint state must use the controller's value format."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.wiser_for_knx.api import WiserKnxClient
from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator


def _coordinator(value_before="off"):
    client = MagicMock()
    client.write_datapoint_value = AsyncMock(return_value=True)
    coordinator = WiserKnxDataUpdateCoordinator(MagicMock(), client, MagicMock())
    coordinator.data = {"datapoints": {"dp1": {"id": "dp1", "value": value_before}}}
    coordinator.async_update_listeners = MagicMock()
    return coordinator


@pytest.mark.parametrize(
    ("written", "expected"),
    [(True, "on"), (False, "off"), ("on", "on"), ("off", "off"), (40, "40")],
)
def test_optimistic_state_matches_wire_format(written, expected):
    coordinator = _coordinator()
    assert asyncio.run(coordinator.async_write_datapoint("dp1", written)) is True
    assert coordinator.data["datapoints"]["dp1"]["value"] == expected


@pytest.mark.parametrize(
    ("written", "wire"), [(True, "on"), (False, "off"), (40, "40")]
)
def test_request_body_uses_wire_format(written, wire):
    session = MagicMock()
    session.closed = False
    response = MagicMock(status=204)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session.put = MagicMock(return_value=response)
    client = WiserKnxClient(
        host="wiser.local", username="admin", password="pw", session=session
    )
    assert asyncio.run(client.write_datapoint_value("dp1", written)) is True
    body = session.put.call_args.kwargs["json"]
    assert body["data"][0]["attributes"]["value"] == wire
