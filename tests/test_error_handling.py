"""Tests for outage and authentication error handling (SMA-8: F3 and F2)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.wiser_for_knx.api import (
    WiserKnxAuthError,
    WiserKnxClient,
    WiserKnxConnectionError,
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


def _client(get):
    """Return a client whose session.get is the given callable."""
    session = MagicMock()
    session.closed = False
    session.get = get
    return WiserKnxClient(
        host="wiser.local", username="admin", password="pw", session=session
    )


def _coordinator(client):
    return WiserKnxDataUpdateCoordinator(MagicMock(), client, MagicMock())


@pytest.mark.parametrize("getter", ["get_locations", "get_functions", "get_datapoints"])
def test_timeout_raises_connection_error(getter):
    """A timeout must not be reported as an empty successful result."""

    def get(*args, **kwargs):
        raise TimeoutError

    with pytest.raises(WiserKnxConnectionError):
        asyncio.run(getattr(_client(get), getter)())


@pytest.mark.parametrize("getter", ["get_locations", "get_functions", "get_datapoints"])
def test_client_error_raises_connection_error(getter):
    def get(*args, **kwargs):
        raise aiohttp.ClientConnectionError("boom")

    with pytest.raises(WiserKnxConnectionError):
        asyncio.run(getattr(_client(get), getter)())


@pytest.mark.parametrize("getter", ["get_locations", "get_functions", "get_datapoints"])
@pytest.mark.parametrize("status", [500, 502, 404])
def test_non_200_raises_connection_error(getter, status):
    with pytest.raises(WiserKnxConnectionError):
        asyncio.run(getattr(_client(lambda *a, **k: _FakeResponse(status)), getter)())


@pytest.mark.parametrize("status", [401, 403])
def test_unauthorized_raises_auth_error(status):
    with pytest.raises(WiserKnxAuthError):
        asyncio.run(_client(lambda *a, **k: _FakeResponse(status)).get_locations())


def test_empty_installation_is_still_success():
    """A genuine 200 with no data is a valid, empty result."""
    result = asyncio.run(
        _client(lambda *a, **k: _FakeResponse(200, {"data": []})).get_locations()
    )
    assert result == {}


def test_password_without_username_is_an_explicit_error():
    client = WiserKnxClient(host="wiser.local", username=None, password="pw")
    with pytest.raises(WiserKnxAuthError):
        client._get_auth()


def test_no_credentials_means_no_auth():
    assert WiserKnxClient(host="wiser.local")._get_auth() is None


def test_authenticate_unexpected_status_is_connection_error():
    with pytest.raises(WiserKnxConnectionError):
        asyncio.run(_client(lambda *a, **k: _FakeResponse(503)).authenticate())


def test_coordinator_timeout_during_refresh_is_update_failed():
    client = MagicMock()
    client.get_locations = AsyncMock(side_effect=WiserKnxConnectionError("timed out"))
    with pytest.raises(UpdateFailed):
        asyncio.run(_coordinator(client)._async_update_data())


def test_coordinator_non_200_during_refresh_is_update_failed():
    """End to end: HTTP 500 from the controller fails the refresh."""
    coordinator = _coordinator(_client(lambda *a, **k: _FakeResponse(500)))
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())


def test_coordinator_401_triggers_reauth():
    """End to end: HTTP 401 raises ConfigEntryAuthFailed, which starts the reauth flow."""
    coordinator = _coordinator(_client(lambda *a, **k: _FakeResponse(401)))
    with pytest.raises(ConfigEntryAuthFailed):
        asyncio.run(coordinator._async_update_data())
