"""The subscribe and unsubscribe requests the push channel is made of."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.wiser_for_knx.api import (
    WiserKnxAuthError,
    WiserKnxClient,
    WiserKnxConnectionError,
    WiserKnxServerError,
)
from custom_components.wiser_for_knx.push_utils import SUBSCRIBE_TYPE

URL = "http://192.168.1.x:8123/api/webhook/abc123"
SECRET = "not-a-real-secret"


def _client(session):
    return WiserKnxClient(
        host="192.168.1.x", username="admin", password="pw", session=session
    )


def _session(status=200, body=None, method="post"):
    session = MagicMock()
    session.closed = False
    response = MagicMock(status=status)
    response.json = AsyncMock(return_value=body)
    response.text = AsyncMock(return_value="")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    getattr(session, method).return_value = response
    return session


def test_subscribe_sends_the_measured_body_and_returns_the_id():
    session = _session(body={"data": {"id": "sub-1", "type": "subscription"}})
    client = _client(session)
    result = asyncio.run(client.async_subscribe_datapoints(["dp1", "dp2"], URL, SECRET))
    assert result == "sub-1"
    call = session.post.call_args
    assert call.args[0].endswith("/api/w4knx/3rdparty/v1/subscribe")
    body = call.kwargs["json"]
    assert body["data"] == [
        {"id": "dp1", "type": "datapoint"},
        {"id": "dp2", "type": "datapoint"},
    ]
    assert body["meta"] == {"url": URL, "secret": SECRET, "type": SUBSCRIBE_TYPE}


def test_subscribe_keeps_the_vendor_json_accept_header():
    """An `application/json`-only Accept earns a 406 on this surface."""
    session = _session(body={"data": {"id": "sub-1"}})
    asyncio.run(_client(session).async_subscribe_datapoints(["dp1"], URL, SECRET))
    headers = session.post.call_args.kwargs["headers"]
    assert "application/vnd.api+json" in headers["Accept"]


def test_subscribe_raises_when_no_id_comes_back():
    session = _session(body={"data": {}})
    with pytest.raises(WiserKnxConnectionError):
        asyncio.run(_client(session).async_subscribe_datapoints(["dp1"], URL, SECRET))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, WiserKnxAuthError),
        (403, WiserKnxAuthError),
        (500, WiserKnxServerError),
        (404, WiserKnxConnectionError),
        (400, WiserKnxConnectionError),
    ],
)
def test_subscribe_maps_failures_onto_the_client_exceptions(status, expected):
    session = _session(status=status, body={})
    with pytest.raises(expected):
        asyncio.run(_client(session).async_subscribe_datapoints(["dp1"], URL, SECRET))


@pytest.mark.parametrize("status", [200, 202, 204, 404])
def test_delete_subscription_treats_an_absent_record_as_deleted(status):
    session = _session(status=status, method="delete")
    assert asyncio.run(_client(session).async_delete_subscription("sub-1")) is True
    assert session.delete.call_args.args[0].endswith("/subscriptions/sub-1")


def test_delete_subscription_reports_a_refusal():
    session = _session(status=409, method="delete")
    assert asyncio.run(_client(session).async_delete_subscription("sub-1")) is False


def test_delete_subscription_raises_on_bad_credentials():
    session = _session(status=401, method="delete")
    with pytest.raises(WiserKnxAuthError):
        asyncio.run(_client(session).async_delete_subscription("sub-1"))


def test_list_subscriptions_returns_the_records():
    session = _session(
        body={"data": [{"id": "sub-1", "meta": {"url": URL}}]}, method="get"
    )
    listed = asyncio.run(_client(session).async_list_subscriptions())
    assert listed == [{"id": "sub-1", "meta": {"url": URL}}]
    assert session.get.call_args.args[0].endswith("/subscriptions")
