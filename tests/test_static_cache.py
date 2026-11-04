"""Tests for the static (locations/functions) cache in the coordinator (SMA-19: F8)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wiser_for_knx.api import (
    WiserKnxAuthError,
    WiserKnxConnectionError,
)
from custom_components.wiser_for_knx.const import (
    STATIC_MAX_AGE,
    STATIC_REFRESH_INTERVAL,
    STATIC_RETRY_INTERVAL,
)
from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator

CLOCK = "custom_components.wiser_for_knx.coordinator.time.monotonic"


def _dp(dp_id, func_id="f1", loc_id="l1", value="off"):
    return {
        "id": dp_id,
        "value": value,
        "parent_function_id": func_id,
        "parent_location_id": loc_id,
    }


def _setup(datapoints=None):
    """Return (coordinator, client) with a fake client that counts every request."""
    client = MagicMock()
    client.get_locations = AsyncMock(
        return_value={"l1": {"id": "l1", "title": "Kitchen"}}
    )
    client.get_functions = AsyncMock(
        return_value={
            "f1": {"id": "f1", "title": "Lamp", "location_id": None, "datapoints": {}}
        }
    )
    client.get_datapoints = AsyncMock(
        return_value=datapoints if datapoints is not None else {"d1": _dp("d1")}
    )
    return WiserKnxDataUpdateCoordinator(MagicMock(), client, MagicMock()), client


def _requests(client):
    return (
        client.get_locations.await_count
        + client.get_functions.await_count
        + client.get_datapoints.await_count
    )


def _poll(coordinator):
    return asyncio.run(coordinator._async_update_data())


def test_warm_poll_is_one_request_not_three():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
        assert _requests(client) == 3  # cold: everything once
        for _ in range(5):
            _poll(coordinator)
    assert _requests(client) == 3 + 5  # warm: datapoints only
    assert client.get_locations.await_count == 1
    assert client.get_functions.await_count == 1


def test_static_data_refreshes_after_the_slow_interval():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
    with patch(CLOCK, return_value=1000.0 + STATIC_REFRESH_INTERVAL - 1):
        _poll(coordinator)
    assert client.get_functions.await_count == 1
    client.get_functions.return_value = {
        "f1": {"id": "f1", "title": "Renamed", "location_id": None, "datapoints": {}}
    }
    with patch(CLOCK, return_value=1000.0 + STATIC_REFRESH_INTERVAL):
        data = _poll(coordinator)
    assert client.get_locations.await_count == 2
    assert client.get_functions.await_count == 2
    assert data["functions"]["f1"]["title"] == "Renamed"


def test_datapoints_and_location_do_not_leak_into_the_cache():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        first = _poll(coordinator)
        client.get_datapoints.return_value = {}
        second = _poll(coordinator)
    assert first["functions"]["f1"]["datapoints"] == {"d1": _dp("d1")}
    assert first["functions"]["f1"]["location_id"] == "l1"
    assert second["functions"]["f1"]["datapoints"] == {}  # not the previous cycle's
    assert coordinator._static[1]["f1"]["datapoints"] == {}
    assert coordinator._static[1]["f1"]["location_id"] is None


def test_datapoint_values_are_live_on_every_poll():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
        client.get_datapoints.return_value = {"d1": _dp("d1", value="on")}
        data = _poll(coordinator)
    assert data["functions"]["f1"]["datapoints"]["d1"]["value"] == "on"


def test_failed_static_fetch_at_setup_fails_and_is_retried():
    coordinator, client = _setup()
    client.get_functions.side_effect = WiserKnxConnectionError("down")
    with patch(CLOCK, return_value=1000.0):
        with pytest.raises(UpdateFailed):
            _poll(coordinator)
        assert coordinator._static is None  # nothing half-cached
        client.get_functions.side_effect = None
        assert _poll(coordinator)["functions"]["f1"]
    assert client.get_locations.await_count == 2  # the retry fetched again


def test_auth_error_on_static_fetch_at_setup_starts_reauth():
    coordinator, client = _setup()
    client.get_locations.side_effect = WiserKnxAuthError("nope")
    with pytest.raises(ConfigEntryAuthFailed):
        _poll(coordinator)


def test_transient_static_failure_with_warm_cache_keeps_entities_working(caplog):
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
    client.get_functions.side_effect = WiserKnxConnectionError("blip")
    due = 1000.0 + STATIC_REFRESH_INTERVAL
    with patch(CLOCK, return_value=due):
        data = _poll(coordinator)
    assert data["functions"]["f1"]["title"] == "Lamp"  # cache served
    assert data["functions"]["f1"]["datapoints"]  # with live datapoints
    assert "Could not refresh locations and functions" in caplog.text
    # Retried after the short retry interval, not every poll and not an hour later
    before = client.get_functions.await_count
    with patch(CLOCK, return_value=due + STATIC_RETRY_INTERVAL - 1):
        _poll(coordinator)
    assert client.get_functions.await_count == before
    client.get_functions.side_effect = None
    with patch(CLOCK, return_value=due + STATIC_RETRY_INTERVAL):
        _poll(coordinator)
    assert client.get_functions.await_count == before + 1
    assert coordinator._static_failing is False


def test_cache_is_not_trusted_forever_when_refresh_keeps_failing():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
    client.get_functions.side_effect = WiserKnxConnectionError("gone")
    with patch(CLOCK, return_value=1000.0 + STATIC_MAX_AGE - 1):
        _poll(coordinator)  # still inside the grace period: served from cache
    with patch(CLOCK, return_value=1000.0 + STATIC_MAX_AGE + STATIC_RETRY_INTERVAL):
        with pytest.raises(UpdateFailed):
            _poll(coordinator)


def test_dead_controller_still_fails_the_update_with_a_warm_cache():
    """Entities must go unavailable when datapoints cannot be read, cache or not."""
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
        client.get_datapoints.side_effect = WiserKnxConnectionError("down")
        with pytest.raises(UpdateFailed):
            _poll(coordinator)
    # and the dead poll did not touch the static endpoints
    assert client.get_functions.await_count == 1


def test_auth_error_on_due_static_refresh_is_not_swallowed():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
    client.get_functions.side_effect = WiserKnxAuthError("revoked")
    with patch(CLOCK, return_value=1000.0 + STATIC_REFRESH_INTERVAL):
        with pytest.raises(ConfigEntryAuthFailed):
            _poll(coordinator)


def test_unknown_function_in_datapoints_triggers_an_early_refresh():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
        client.get_functions.return_value = {
            "f1": {"id": "f1", "title": "Lamp", "location_id": None, "datapoints": {}},
            "f2": {"id": "f2", "title": "New", "location_id": None, "datapoints": {}},
        }
        client.get_datapoints.return_value = {"d1": _dp("d1"), "d2": _dp("d2", "f2")}
        data = _poll(coordinator)  # same instant: far from the hourly refresh
    assert client.get_functions.await_count == 2
    assert "f2" in data["functions"]


def test_orphan_datapoint_costs_one_refresh_not_one_per_poll():
    coordinator, client = _setup(
        {"d1": _dp("d1"), "orphan": _dp("orphan", "ghost", "l1")}
    )
    with patch(CLOCK, return_value=1000.0):
        for _ in range(5):
            _poll(coordinator)
    assert client.get_functions.await_count == 1
    assert client.get_datapoints.await_count == 5


def test_on_demand_refresh_refetches_static_data_before_the_interval():
    coordinator, client = _setup()
    with patch(CLOCK, return_value=1000.0):
        _poll(coordinator)
        coordinator.async_refresh = AsyncMock(
            side_effect=coordinator._async_update_data
        )
        asyncio.run(coordinator.async_refresh_structure())
    assert client.get_locations.await_count == 2
    assert client.get_functions.await_count == 2
