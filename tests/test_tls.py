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

from custom_components.wiser_for_knx import async_migrate_entry, config_flow
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
    DEFAULT_VERIFY_SSL,
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
async def server(tmp_path):
    """Yield (port, fingerprint) of a TLS server using a self-signed certificate."""
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
