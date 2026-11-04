"""Discovery must reject non-Wiser devices before prompting, and duplicates before connecting."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.wiser_for_knx import config_flow
from custom_components.wiser_for_knx.config_flow import WiserKnxConfigFlow


def _flow(probe_results):
    """Flow whose probe answers come from `probe_results` ({(port, ssl): data or None})."""
    flow = WiserKnxConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow._async_current_entries = MagicMock(return_value=[])
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_abort = lambda reason: {"type": "abort", "reason": reason}
    flow.async_step_credentials = AsyncMock(return_value={"type": "form"})

    def fake_client(host, port, ssl, *args, **kwargs):
        client = MagicMock()
        client.probe = AsyncMock(return_value=probe_results.get((port, ssl)))
        return client

    flow._client = fake_client
    return flow


def test_knx_router_on_udp_port_is_not_offered():
    # Generic KNX/IP router advertising _knx._udp on 3671: nothing answers /.well-known/knx
    info = SimpleNamespace(
        ip_address="192.168.1.50", hostname="knxrouter.local.", port=3671, properties={}
    )
    flow = _flow({})
    assert asyncio.run(flow.async_step_zeroconf(info)) == {
        "type": "abort",
        "reason": "not_wiser_knx",
    }
    flow.async_step_credentials.assert_not_called()


def test_dhcp_non_wiser_device_in_same_oui_is_rejected():
    info = SimpleNamespace(ip="192.168.1.60", macaddress="000cc6aabbcc")
    flow = _flow({})
    assert asyncio.run(flow.async_step_dhcp(info)) == {
        "type": "abort",
        "reason": "not_wiser_knx",
    }


def test_zeroconf_port_and_scheme_follow_the_probe():
    # mDNS says port 80; the controller actually answers over http on 80
    info = SimpleNamespace(
        ip_address="192.168.1.20", hostname="wiser-1.local.", port=80, properties={}
    )
    flow = _flow({(80, False): {"api": {"base": "/api/w4knx/3rdparty/v1"}}})
    asyncio.run(flow.async_step_zeroconf(info))
    assert (flow._discovered_port, flow._discovered_ssl) == (80, False)
    flow.async_step_credentials.assert_called_once()


def test_dhcp_uses_normalized_mac_as_unique_id():
    info = SimpleNamespace(ip="192.168.1.20", macaddress="000CC6AABBCC")
    flow = _flow({(443, True): {"api": {"base": "/x"}}})
    asyncio.run(flow.async_step_dhcp(info))
    flow.async_set_unique_id.assert_awaited_with("00:0c:c6:aa:bb:cc")
    assert flow._discovered_ssl is True


def test_duplicate_is_aborted_before_any_network_request():
    info = SimpleNamespace(ip="192.168.1.20", macaddress="000cc6aabbcc")
    flow = _flow({(443, True): {"api": {}}})
    flow._abort_if_unique_id_configured = MagicMock(side_effect=RuntimeError("aborted"))
    flow._client = MagicMock(
        side_effect=AssertionError("network used before duplicate check")
    )
    try:
        asyncio.run(flow.async_step_dhcp(info))
    except RuntimeError as err:
        assert str(err) == "aborted"
    else:
        raise AssertionError("expected abort")
