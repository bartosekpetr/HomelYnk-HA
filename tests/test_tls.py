"""TLS verification: default-on, trust-on-first-use pinning, mismatch, opt-out, migration.

The client tests talk to a real local aiohttp server with a self-signed certificate, so they
exercise the actual TLS handshake rather than a mock.
"""

import asyncio
import hashlib
import shutil
import ssl
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from custom_components.wiser_for_knx import (
    _sync_transport_issues,
    async_migrate_entry,
    async_remove_entry,
    config_flow,
)
from custom_components.wiser_for_knx.api import (
    WiserKnxCertificateError,
    WiserKnxClient,
    WiserKnxFingerprintMismatchError,
)
from custom_components.wiser_for_knx.config_flow import WiserKnxConfigFlow
from custom_components.wiser_for_knx.const import (
    CONF_CERT_FINGERPRINT,
    CONF_SKIP_VERIFY,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    ISSUE_INSECURE_HTTP,
    ISSUE_INSECURE_TLS,
)
from custom_components.wiser_for_knx.tls import (
    format_fingerprint,
    normalize_fingerprint,
)

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="no openssl")


def _make_cert(tmp_path, name):
    cert, key = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
         "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )  # fmt: skip
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    return cert, key, hashlib.sha256(der).hexdigest()


@pytest.fixture
async def server(tmp_path, request):
    """Yield (port, fingerprint) of a TLS server using a self-signed certificate."""
    try:
        # pytest-homeassistant-custom-component blocks sockets; this server is loopback-only.
        request.getfixturevalue("socket_enabled")
    except pytest.FixtureLookupError:
        pass  # plain pytest run: nothing blocks sockets
    cert, key, fp = _make_cert(tmp_path, "srv")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)

    async def well_known(request):
        return web.json_response({"api": {"base": "/api/x"}})

    app = web.Application()
    app.router.add_get("/.well-known/knx", well_known)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ctx)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port, fp
    await runner.cleanup()


def _client(port, **kwargs):
    return WiserKnxClient(host="127.0.0.1", port=port, ssl=True, **kwargs)


def test_verification_is_the_default():
    assert DEFAULT_VERIFY_SSL is True
    assert WiserKnxClient(host="h").verify_ssl is True
    assert WiserKnxClient(host="h").tls_setting is True


def test_fingerprint_wins_over_verify_ssl_false_and_ignores_injected_session():
    fp = "ab" * 32
    client = WiserKnxClient(
        host="h", verify_ssl=False, fingerprint=fp, session=object()
    )
    assert client._session is None  # a pin needs its own connector
    assert client.tls_setting._fingerprint == bytes.fromhex(fp)


def test_fingerprint_normalisation():
    raw = "AB:" * 31 + "AB"
    assert normalize_fingerprint(raw) == "ab" * 32
    assert format_fingerprint("ab" * 32) == ":".join(["AB"] * 32)
    with pytest.raises(ValueError):
        normalize_fingerprint("abc")


@needs_openssl
async def test_self_signed_certificate_is_rejected_by_default(server):
    port, _ = server
    client = _client(port)
    with pytest.raises(WiserKnxCertificateError):
        await client.async_check_tls()
    await client.close()


@needs_openssl
async def test_pinned_fingerprint_is_accepted(server):
    port, fp = server
    client = _client(port, fingerprint=fp)
    await client.async_check_tls()
    assert (await client.probe()) == {"api": {"base": "/api/x"}}
    await client.close()


@needs_openssl
async def test_fingerprint_mismatch_is_rejected(server):
    port, _ = server
    client = _client(port, fingerprint="00" * 32)
    with pytest.raises(WiserKnxFingerprintMismatchError):
        await client.async_check_tls()
    await client.close()


@needs_openssl
async def test_insecure_opt_out_connects(server):
    port, _ = server
    client = _client(port, verify_ssl=False)
    await client.async_check_tls()
    await client.close()


def _flow():
    flow = WiserKnxConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_abort = lambda reason: {"type": "abort", "reason": reason}
    flow.async_show_form = lambda **kw: {"type": "form", **kw}
    flow.async_step_backup = AsyncMock(
        return_value={"type": "form", "step_id": "backup"}
    )
    return flow


# Keys come from the flow module: without Home Assistant installed they are mocks
_INPUT = {
    config_flow.CONF_HOST: "10.0.0.5",
    config_flow.CONF_PORT: 443,
    config_flow.CONF_SSL: True,
    config_flow.CONF_USERNAME: "admin",
    config_flow.CONF_PASSWORD: "pw",
}


async def test_flow_untrusted_certificate_then_confirm_pins_fingerprint():
    flow = _flow()
    seen = []

    def fake_client(
        host, port, ssl, verify_ssl, username=None, password="", fingerprint=None
    ):
        seen.append((verify_ssl, fingerprint))
        client = MagicMock()
        client.ssl = ssl
        client.async_check_tls = AsyncMock(
            side_effect=None if fingerprint else WiserKnxCertificateError("self signed")
        )
        client.discover_endpoints = AsyncMock(return_value={"api_base": "/api/x"})
        client.authenticate = AsyncMock(return_value=True)
        client.async_get_device_info = AsyncMock(return_value={})
        return client

    flow._client = fake_client
    fp = "cd" * 32
    with patch.object(
        config_flow, "async_fetch_fingerprint", AsyncMock(return_value=fp)
    ):
        assert await flow._async_try_connect(_INPUT) == "untrusted_certificate"
        # Nothing was saved and no credentials were sent before the user confirmed
        assert flow._entry_data == {}
        form = await flow.async_step_trust_certificate()
        assert form["description_placeholders"]["fingerprint"] == format_fingerprint(fp)
        await flow.async_step_trust_certificate({})
    assert flow._entry_data[CONF_CERT_FINGERPRINT] == fp
    assert flow._entry_data[CONF_VERIFY_SSL] is True
    assert seen[-1] == (True, fp)


async def test_flow_pinned_mismatch_aborts_instead_of_retrusting():
    flow = _flow()
    client = MagicMock(ssl=True)
    client.discover_endpoints = AsyncMock(
        side_effect=WiserKnxFingerprintMismatchError("x")
    )
    flow._client = lambda *a, **k: client
    flow._trusted_fingerprint = "ee" * 32
    assert await flow._async_try_connect(_INPUT) == "fingerprint_mismatch"
    assert flow._entry_data == {}


async def test_flow_skip_verify_is_explicit_opt_in():
    flow = _flow()
    calls = []

    def fake_client(
        host, port, ssl, verify_ssl, username=None, password="", fingerprint=None
    ):
        calls.append((verify_ssl, fingerprint))
        client = MagicMock(ssl=ssl)
        client.discover_endpoints = AsyncMock(return_value={"api_base": "/a"})
        client.authenticate = AsyncMock(return_value=True)
        client.async_get_device_info = AsyncMock(return_value={})
        return client

    flow._client = fake_client
    assert await flow._async_try_connect({**_INPUT, CONF_SKIP_VERIFY: True}) is None
    assert calls == [(False, None)]
    assert flow._entry_data[CONF_VERIFY_SSL] is False
    assert CONF_CERT_FINGERPRINT not in flow._entry_data
    # And without the opt-in the form default is verified
    calls.clear()
    flow._trusted_fingerprint = None
    flow._client = fake_client
    await flow._async_try_connect(_INPUT)
    assert calls == [(True, None)]


def _entry(data, version=2):
    return SimpleNamespace(entry_id="e1", unique_id="u", version=version, data=data)


def test_migration_keeps_existing_insecure_entry_insecure():
    # Pre-fix installs that never stored verify_ssl effectively ran unverified
    entry = _entry({"host": "h"})
    hass = MagicMock()
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={"host": "h", CONF_VERIFY_SSL: False}, version=3
    )


def test_migration_preserves_explicit_setting():
    entry = _entry({"host": "h", CONF_VERIFY_SSL: True})
    hass = MagicMock()
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=3)


# --- plain HTTP (ssl off) -----------------------------------------------------------------


class _FakeIssues:
    """Stands in for the issue registry: tracks which issue ids are currently active."""

    IssueSeverity = SimpleNamespace(WARNING="warning")

    def __init__(self):
        self.active = {}

    def async_create_issue(self, hass, domain, issue_id, **kwargs):
        self.active[issue_id] = kwargs

    def async_delete_issue(self, hass, domain, issue_id):
        self.active.pop(issue_id, None)


def _sync(issues, ssl, verify_ssl=True, fingerprint=None):
    with patch("custom_components.wiser_for_knx.ir", issues):
        _sync_transport_issues(MagicMock(), "e1", "h", ssl, verify_ssl, fingerprint)


def test_new_entry_form_defaults_to_https_even_after_plain_http_discovery():
    flow = WiserKnxConfigFlow()
    # Discovery that only saw the controller answer on port 80
    flow._discovered_port, flow._discovered_ssl = 80, False
    assert flow._prefill_port() == DEFAULT_PORT
    assert DEFAULT_SSL is True
    # Without the plain_http field the flow connects over HTTPS
    flow2 = _flow()
    seen = []

    def fake_client(host, port, ssl, *rest):
        seen.append(ssl)
        client = MagicMock(ssl=ssl)
        client.async_check_tls = AsyncMock()
        client.discover_endpoints = AsyncMock(return_value={"api_base": "/a"})
        client.authenticate = AsyncMock(return_value=True)
        client.async_get_device_info = AsyncMock(return_value={})
        return client

    flow2._client = fake_client
    plain_input = {k: v for k, v in _INPUT.items() if k != config_flow.CONF_SSL}
    assert asyncio.run(flow2._async_try_connect(plain_input)) is None
    assert seen == [True]
    assert flow2._entry_data[config_flow.CONF_SSL] is True


def test_plain_http_is_an_explicit_opt_in_and_stays_possible():
    flow = _flow()
    seen = []

    def fake_client(host, port, ssl, *rest):
        seen.append(ssl)
        client = MagicMock(ssl=ssl)
        client.discover_endpoints = AsyncMock(return_value={"api_base": "/a"})
        client.authenticate = AsyncMock(return_value=True)
        client.async_get_device_info = AsyncMock(return_value={})
        return client

    flow._client = fake_client
    data = {**_INPUT, config_flow.CONF_PLAIN_HTTP: True}
    assert asyncio.run(flow._async_try_connect(data)) is None
    assert seen == [False]
    assert flow._entry_data[config_flow.CONF_SSL] is False


def test_discovery_probe_prefers_https_when_both_answer():
    flow = _flow()
    order = []

    def fake_client(host, port, ssl, *rest, **kw):
        client = MagicMock()

        async def probe():
            order.append((port, ssl))
            return {"api": {}} if (port, ssl) in {(80, False), (443, True)} else None

        client.probe = probe
        return client

    flow._client = fake_client
    assert asyncio.run(flow._async_probe_discovered("h", 80)) == (443, True)


def test_http_issue_appears_when_ssl_off_and_clears_when_on():
    issues = _FakeIssues()
    _sync(issues, ssl=False)
    assert set(issues.active) == {ISSUE_INSECURE_HTTP.format(entry_id="e1")}
    assert (
        issues.active[ISSUE_INSECURE_HTTP.format(entry_id="e1")]["is_fixable"] is False
    )
    _sync(issues, ssl=True)
    assert issues.active == {}


def test_tls_and_http_issues_are_never_active_together():
    issues = _FakeIssues()
    for use_https in (True, False):
        for verify_ssl in (True, False):
            for fingerprint in (None, "ab"):
                _sync(issues, use_https, verify_ssl, fingerprint)
                assert len(issues.active) <= 1
    _sync(issues, ssl=True, verify_ssl=False)
    assert set(issues.active) == {ISSUE_INSECURE_TLS.format(entry_id="e1")}
    # Turning ssl off swaps the TLS notice for the HTTP one, it does not add to it
    _sync(issues, ssl=False, verify_ssl=False)
    assert set(issues.active) == {ISSUE_INSECURE_HTTP.format(entry_id="e1")}


def test_removing_an_entry_clears_both_issues():
    issues = _FakeIssues()
    _sync(issues, ssl=False)
    issues.active[ISSUE_INSECURE_TLS.format(entry_id="e1")] = {}
    with patch("custom_components.wiser_for_knx.ir", issues):
        asyncio.run(async_remove_entry(MagicMock(), _entry({"host": "h"})))
    assert issues.active == {}


def test_migration_leaves_a_stored_plain_http_choice_alone():
    # No ssl rewrite: a missing key already resolves to the unchanged default (HTTPS), and a
    # stored False must survive the upgrade untouched.
    hass = MagicMock()
    entry = _entry({"host": "h", config_flow.CONF_SSL: False, CONF_VERIFY_SSL: True})
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=3)
    hass = MagicMock()
    entry = _entry({"host": "h", config_flow.CONF_SSL: False})
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    (_, kwargs) = hass.config_entries.async_update_entry.call_args
    assert kwargs["data"][config_flow.CONF_SSL] is False


def test_options_flow_switches_transport_without_touching_other_data():
    entry = SimpleNamespace(
        data={"host": "h", config_flow.CONF_SSL: True, CONF_VERIFY_SSL: True}
    )
    handler = config_flow.WiserKnxOptionsFlowHandler()
    handler.hass = MagicMock()
    handler.hass.config_entries.async_update_entry = MagicMock()
    with patch.object(
        config_flow.WiserKnxOptionsFlowHandler,
        "config_entry",
        entry,
        create=True,
    ):
        handler._apply_transport_choice(plain=True, skip=False)
        handler.hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={"host": "h", config_flow.CONF_SSL: False, CONF_VERIFY_SSL: True},
        )


def _options_handler(data):
    entry = SimpleNamespace(data=data, options={})
    handler = config_flow.WiserKnxOptionsFlowHandler()
    handler.hass = MagicMock()
    handler.hass.config_entries.async_update_entry = MagicMock()
    patcher = patch.object(
        config_flow.WiserKnxOptionsFlowHandler, "config_entry", entry, create=True
    )
    return handler, entry, patcher


def _stored_data(handler, entry):
    calls = handler.hass.config_entries.async_update_entry.call_args_list
    return calls[-1].kwargs["data"] if calls else entry.data


@pytest.mark.parametrize(
    ("stored_port", "stored_ssl", "plain", "port", "expected_port"),
    [
        (80, False, False, 80, 443),  # untick plain HTTP on the default HTTP port
        (443, True, True, 443, 80),  # tick plain HTTP on the default HTTPS port
        (8443, True, True, 8443, 8443),  # deliberate port is kept
        (8080, False, False, 8080, 8080),
        (80, False, False, 8443, 8443),  # explicit edit wins over the suggestion
        (443, True, False, 443, 443),  # no transport change, nothing suggested
    ],
)
def test_options_port_edit_and_suggestion(
    stored_port, stored_ssl, plain, port, expected_port
):
    handler, entry, patcher = _options_handler(
        {
            "host": "h",
            config_flow.CONF_PORT: stored_port,
            config_flow.CONF_SSL: stored_ssl,
            CONF_VERIFY_SSL: True,
        }
    )
    with patcher:
        handler._apply_transport_choice(plain=plain, skip=False, port=port)
        assert _stored_data(handler, entry)[config_flow.CONF_PORT] == expected_port


def test_options_saving_unchanged_leaves_entry_untouched():
    handler, _, patcher = _options_handler(
        {
            "host": "h",
            config_flow.CONF_PORT: 80,
            config_flow.CONF_SSL: False,
            CONF_VERIFY_SSL: True,
        }
    )
    with patcher:
        handler._apply_transport_choice(plain=True, skip=False, port=80)
        handler.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_options_flow_rejects_out_of_range_port(port):
    handler, _, patcher = _options_handler(
        {"host": "h", config_flow.CONF_PORT: 443, config_flow.CONF_SSL: True}
    )
    handler.async_show_form = MagicMock(side_effect=lambda **kw: kw)
    handler.async_create_entry = MagicMock()
    with patcher:
        result = asyncio.run(handler.async_step_init({config_flow.CONF_PORT: port}))
    assert result["errors"] == {config_flow.CONF_PORT: "invalid_port"}
    handler.async_create_entry.assert_not_called()
    handler.hass.config_entries.async_update_entry.assert_not_called()


def test_options_flow_never_connects():
    """SMA-15: the options flow sends no request, so no credentials leave unverified."""
    handler, _, patcher = _options_handler(
        {"host": "h", config_flow.CONF_PORT: 80, config_flow.CONF_SSL: False}
    )
    handler.async_create_entry = MagicMock()
    with (
        patcher,
        patch.object(config_flow, "WiserKnxClient") as client,
        patch.object(config_flow, "async_fetch_fingerprint") as fingerprint,
        patch.object(config_flow, "async_get_clientsession") as session,
    ):
        asyncio.run(
            handler.async_step_init(
                {config_flow.CONF_PORT: 443, config_flow.CONF_PLAIN_HTTP: False}
            )
        )
    client.assert_not_called()
    fingerprint.assert_not_called()
    session.assert_not_called()
