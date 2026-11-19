"""Collections are retried on 5xx (SMA-59).

The controller answers HTTP 500 on `/datapoints` and `/functions` now and then,
typically while it recomputes which group objects to export after a config
change. `/datapoints` is the one request the whole entity graph is built from, so
an unretried 500 makes every entity unavailable at runtime and looks like an
empty installation at startup.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wiser_for_knx.api import (
    WiserKnxAuthError,
    WiserKnxClient,
    WiserKnxConnectionError,
    WiserKnxServerError,
)
from custom_components.wiser_for_knx.const import (
    COLLECTION_RETRIES,
    COLLECTION_RETRY_BACKOFF,
    SERVER_ERROR_HINT_AFTER,
)
from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator


class _FakeResponse:
    def __init__(self, status, body=None):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._body


def _client(statuses):
    """Return (client, calls) answering `statuses` in order, repeating the last one."""
    calls: list[str] = []

    def get(url, **kwargs):
        calls.append(url)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return _FakeResponse(status, {"data": [{"id": "dp1", "attributes": {}}]})

    session = MagicMock()
    session.closed = False
    session.get = get
    client = WiserKnxClient(
        host="wiser.local", username="admin", password="pw", session=session
    )
    return client, calls


def test_a_transient_500_is_retried_and_succeeds(retry_sleeps):
    client, calls = _client([500, 200])
    assert "dp1" in asyncio.run(client.get_datapoints())
    assert len(calls) == 2


def test_a_persistent_500_raises_after_the_retries_are_used_up(retry_sleeps):
    client, calls = _client([500])
    with pytest.raises(WiserKnxServerError):
        asyncio.run(client.get_datapoints())
    assert len(calls) == COLLECTION_RETRIES


def test_the_backoff_grows_between_attempts(retry_sleeps):
    client, _ = _client([500])
    with pytest.raises(WiserKnxServerError):
        asyncio.run(client.get_functions())
    assert retry_sleeps == [
        COLLECTION_RETRY_BACKOFF * 2**n for n in range(COLLECTION_RETRIES - 1)
    ]


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, WiserKnxConnectionError), (406, WiserKnxConnectionError)],
)
def test_a_client_error_is_not_retried(status, error):
    """Only 5xx is worth retrying; a 404 or a 406 would answer the same way forever."""
    client, calls = _client([status])
    with pytest.raises(error):
        asyncio.run(client.get_locations())
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_unauthorized_is_not_retried(status):
    client, calls = _client([status])
    with pytest.raises(WiserKnxAuthError):
        asyncio.run(client.get_locations())
    assert len(calls) == 1


def test_a_server_error_is_still_a_connection_error():
    """Existing handling (UpdateFailed, keeping the static cache) must keep working."""
    assert issubclass(WiserKnxServerError, WiserKnxConnectionError)


def _coordinator_failing_on_datapoints():
    client = MagicMock()
    client.get_locations = AsyncMock(return_value={})
    client.get_functions = AsyncMock(return_value={})
    client.get_datapoints = AsyncMock(
        side_effect=WiserKnxServerError(
            "https://wiser.local/api/w4knx/3rdparty/v1/datapoints returned HTTP 500"
        )
    )
    return WiserKnxDataUpdateCoordinator(MagicMock(), client, MagicMock())


def test_a_persistent_server_error_is_no_new_data_not_an_empty_installation():
    coordinator = _coordinator_failing_on_datapoints()
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_the_known_controller_side_cause_is_logged_once(caplog):
    """Repeated refusals name the Danfoss floor-heating widget, but only once."""
    coordinator = _coordinator_failing_on_datapoints()
    with caplog.at_level(logging.WARNING):
        for _ in range(SERVER_ERROR_HINT_AFTER + 3):
            with pytest.raises(UpdateFailed):
                asyncio.run(coordinator._async_update_data())

    hints = [r for r in caplog.records if "Danfoss" in r.getMessage()]
    assert len(hints) == 1


def test_the_hint_is_not_logged_for_a_short_outage(caplog):
    coordinator = _coordinator_failing_on_datapoints()
    with caplog.at_level(logging.WARNING):
        for _ in range(SERVER_ERROR_HINT_AFTER - 1):
            with pytest.raises(UpdateFailed):
                asyncio.run(coordinator._async_update_data())

    assert not [r for r in caplog.records if "Danfoss" in r.getMessage()]


def test_a_successful_poll_resets_the_counter(caplog):
    """A recovered controller must not be one failed poll away from the warning."""
    coordinator = _coordinator_failing_on_datapoints()
    for _ in range(SERVER_ERROR_HINT_AFTER - 1):
        with pytest.raises(UpdateFailed):
            asyncio.run(coordinator._async_update_data())

    coordinator.client.get_datapoints = AsyncMock(return_value={})
    asyncio.run(coordinator._async_update_data())
    assert coordinator._server_errors == 0

    coordinator.client.get_datapoints = AsyncMock(
        side_effect=WiserKnxServerError("/datapoints returned HTTP 500")
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpdateFailed):
            asyncio.run(coordinator._async_update_data())
    assert not [r for r in caplog.records if "Danfoss" in r.getMessage()]
