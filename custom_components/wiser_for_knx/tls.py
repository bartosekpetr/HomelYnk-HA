"""TLS helpers: certificate fingerprints for trust-on-first-use of self-signed controllers."""

from __future__ import annotations

import hashlib
import re
import ssl

from homeassistant.core import HomeAssistant

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def normalize_fingerprint(value: str) -> str:
    """Return a SHA-256 fingerprint as 64 lowercase hex chars; raise ValueError if invalid."""
    cleaned = value.replace(":", "").replace(" ", "").lower()
    if not _FINGERPRINT_RE.match(cleaned):
        raise ValueError("Not a SHA-256 fingerprint")
    return cleaned


def fingerprint_bytes(value: str) -> bytes:
    """Return the raw digest bytes for `aiohttp.Fingerprint`."""
    return bytes.fromhex(normalize_fingerprint(value))


def format_fingerprint(value: str) -> str:
    """Format as AA:BB:... for display, the way browsers and openssl show it."""
    cleaned = normalize_fingerprint(value).upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, len(cleaned), 2))


def _fetch_fingerprint(host: str, port: int) -> str:
    """Blocking: connect and hash the peer certificate (no validation, no data sent)."""
    pem = ssl.get_server_certificate((host, port), timeout=5)
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


async def async_fetch_fingerprint(
    hass: HomeAssistant, host: str, port: int
) -> str | None:
    """Return the controller's certificate SHA-256 fingerprint, or None if unreachable.

    Runs in the executor because it uses blocking sockets. The certificate is read without
    being trusted; it only becomes trusted if the user confirms the fingerprint.
    """
    try:
        return await hass.async_add_executor_job(_fetch_fingerprint, host, port)
    except (OSError, ssl.SSLError, ValueError):
        return None
