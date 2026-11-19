"""The discovered api_base must be a plain path, never able to change the host."""

import pytest

from custom_components.wiser_for_knx.api import WiserKnxClient
from custom_components.wiser_for_knx.const import DEFAULT_API_BASE


def _client():
    return WiserKnxClient("192.168.1.2", 443, True, "admin", "pw", verify_ssl=False)


@pytest.mark.parametrize(
    "value",
    [".evil.example/v1", "@evil.example/v1", "//evil.example/v1", "https://evil/v1",
     "api/v1", "/a//b", "/a@b", "/a b", "", None, 5],
)
def test_hostile_api_base_falls_back(value):
    c = _client()
    c.api_base = value
    assert c.api_base == DEFAULT_API_BASE
    assert c.base_url + c.api_base + "/locations" == (
        "https://192.168.1.2:443" + DEFAULT_API_BASE + "/locations"
    )


def test_valid_api_base_kept():
    c = _client()
    c.api_base = "/api/w4knx/3rdparty/v2"
    assert c.api_base == "/api/w4knx/3rdparty/v2"
