"""API client for communicating with Wiser for KNX IoT 3rd Party API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import BasicAuth

from .const import MGMT_API_BASE
from .health import parse_health
from .tls import fingerprint_bytes

_LOGGER = logging.getLogger(__name__)


class WiserKnxAuthError(Exception):
    """Raised when authentication fails."""


class WiserKnxConnectionError(Exception):
    """Raised when connection to Wiser for KNX fails."""


class WiserKnxCertificateError(WiserKnxConnectionError):
    """Raised when the controller's TLS certificate is not trusted."""


class WiserKnxFingerprintMismatchError(WiserKnxCertificateError):
    """Raised when the certificate does not match the pinned fingerprint."""


def _connection_error(
    message: str, err: aiohttp.ClientError
) -> WiserKnxConnectionError:
    """Map an aiohttp error to the matching client exception, keeping TLS failures distinct."""
    if isinstance(err, aiohttp.ServerFingerprintMismatch):
        return WiserKnxFingerprintMismatchError(message)
    if isinstance(err, aiohttp.ClientSSLError):
        return WiserKnxCertificateError(message)
    return WiserKnxConnectionError(message)


class WiserKnxClient:
    """Client for Wiser for KNX IoT 3rd Party API."""

    def __init__(
        self,
        host: str,
        port: int = 443,
        ssl: bool = True,
        username: str | None = None,
        password: str | None = None,
        session: aiohttp.ClientSession | None = None,
        verify_ssl: bool = True,
        fingerprint: str | None = None,
    ) -> None:
        """Initialize the client.

        TLS trust is one of three mutually exclusive modes, decided once here:
        a pinned SHA-256 `fingerprint` (self-signed controllers, trusted on first use),
        normal verification (`verify_ssl=True`), or none (`verify_ssl=False`, insecure).
        A fingerprint always wins; it is never combined with `verify_ssl=False`.
        """
        self.host = host
        self.port = port
        self.ssl = ssl
        self.fingerprint = fingerprint
        self.verify_ssl = verify_ssl
        self.username = username
        self.password = password
        self._session = (
            None if fingerprint else session
        )  # a pin needs its own connector
        self._own_session = False

        self.api_base = "/api/w4knx/3rdparty/v1"
        self.discovered_info: dict[str, Any] = {}

    @property
    def base_url(self) -> str:
        """Return base URL for controller."""
        proto = "https" if self.ssl else "http"
        if (self.ssl and self.port == 443) or (not self.ssl and self.port == 80):
            return f"{proto}://{self.host}"
        return f"{proto}://{self.host}:{self.port}"

    def _get_auth(self) -> BasicAuth | None:
        """Return BasicAuth if credentials provided."""
        if self.password and not self.username:
            raise WiserKnxAuthError("A password was provided without a username")
        if self.username and self.password:
            return BasicAuth(self.username, self.password)
        return None

    def _get_headers(self) -> dict[str, str]:
        """Headers required by KNX IoT 3rd Party API."""
        return {
            "Accept": "application/vnd.api+json, application/json",
            "Content-Type": "application/vnd.api+json",
        }

    @property
    def tls_setting(self) -> aiohttp.Fingerprint | bool:
        """Value for the connector's `ssl=` argument; set once, never per request."""
        if self.fingerprint:
            return aiohttp.Fingerprint(fingerprint_bytes(self.fingerprint))
        return self.verify_ssl

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return or create aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self.tls_setting)
            self._session = aiohttp.ClientSession(connector=connector)
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Close session if created internally."""
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def discover_endpoints(self) -> dict[str, Any]:
        """Probe and discover the KNX IoT entry point."""
        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=5)

        well_known_url = f"{self.base_url}/.well-known/knx"
        try:
            async with session.get(
                well_known_url,
                headers={"Accept": "application/json, */*"},
                timeout=timeout,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    self.discovered_info = data
                    api_base = data.get("api", {}).get("base")
                    if api_base:
                        self.api_base = api_base
                    _LOGGER.info("Discovered KNX API base: %s", self.api_base)
        except (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch) as err:
            raise _connection_error(
                f"TLS failure talking to {well_known_url}: {err}", err
            ) from err
        except Exception as err:  # noqa: BLE001 - optional probe; any failure falls back to the default base
            _LOGGER.debug(
                "Well-known probe notice: %s (using default base %s)",
                err,
                self.api_base,
            )

        return {
            "api_base": self.api_base,
            "info": self.discovered_info,
        }

    async def probe(self) -> dict[str, Any] | None:
        """Unauthenticated check for a KNX IoT endpoint; return its /.well-known/knx data or None."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/.well-known/knx",
                headers={"Accept": "application/json, */*"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("KNX probe of %s failed: %s", self.base_url, err)
            return None
        if not isinstance(data, dict) or not isinstance(data.get("api"), dict):
            return None
        return data

    async def async_check_tls(self) -> None:
        """Unauthenticated TLS check; raise WiserKnxCertificateError if the cert is untrusted.

        Sends no credentials, so it is safe to call before the certificate is trusted.
        """
        session = await self._get_session()
        url = f"{self.base_url}/.well-known/knx"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                await resp.read()
        except aiohttp.ClientError as err:
            raise _connection_error(f"Request to {url} failed: {err}", err) from err
        except TimeoutError as err:
            raise WiserKnxConnectionError(f"Request to {url} timed out") from err

    async def async_get_device_info(self) -> dict[str, Any]:
        """Return the management API deviceInfo payload (requires authentication)."""
        return await self._async_mgmt_get("/custom/deviceInfo")

    async def authenticate(self) -> bool:
        """Verify credentials; False only for 401/403, connection problems raise."""
        session = await self._get_session()
        auth = self._get_auth()
        headers = self._get_headers()
        timeout = aiohttp.ClientTimeout(total=8)

        url = f"{self.base_url}{self.api_base}/locations"
        try:
            async with session.get(
                url,
                headers=headers,
                auth=auth,
                timeout=timeout,
            ) as resp:
                if resp.status == 200:
                    return True
                if resp.status in (401, 403):
                    _LOGGER.warning(
                        "Authentication failed (HTTP %s) at %s", resp.status, url
                    )
                    return False
                raise WiserKnxConnectionError(
                    f"Unexpected HTTP {resp.status} from {url}"
                )
        except aiohttp.ClientError as err:
            raise _connection_error(f"Connection failed to {url}: {err}", err) from err
        except TimeoutError as err:
            raise WiserKnxConnectionError(f"Connection timed out to {url}") from err

    async def _async_get_items(self, resource: str) -> list[dict[str, Any]]:
        """GET a collection from the 3rd party API and return its `data` list.

        Raises WiserKnxAuthError on 401/403 and WiserKnxConnectionError on any
        other failure, so callers (the coordinator) can tell an outage from an
        empty installation.
        """
        session = await self._get_session()
        url = f"{self.base_url}{self.api_base}/{resource}"
        try:
            async with session.get(
                url,
                headers=self._get_headers(),
                auth=self._get_auth(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (401, 403):
                    raise WiserKnxAuthError(f"Unauthorized reading {resource}")
                if resp.status != 200:
                    raise WiserKnxConnectionError(f"{url} returned HTTP {resp.status}")
                json_data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise _connection_error(f"Request to {url} failed: {err}", err) from err
        except TimeoutError as err:
            raise WiserKnxConnectionError(f"Request to {url} timed out") from err
        except ValueError as err:
            raise WiserKnxConnectionError(f"Invalid JSON from {url}: {err}") from err
        return (json_data or {}).get("data") or []

    async def get_locations(self) -> dict[str, dict[str, Any]]:
        """Retrieve all locations (sites, floors, rooms) mapped by location ID."""
        locations = {}
        for item in await self._async_get_items("locations"):
            loc_id = item.get("id")
            if loc_id:
                locations[loc_id] = {
                    "id": loc_id,
                    "type": item.get("type"),  # site, floor, room
                    "title": item.get("attributes", {}).get("title", ""),
                    "parent_id": item.get("attributes", {}).get(
                        "schneider:parentLocation"
                    ),
                }
        return locations

    async def get_functions(self) -> dict[str, dict[str, Any]]:
        """Retrieve all functions (devices/logical entities) mapped by function ID."""
        functions = {}
        for item in await self._async_get_items("functions"):
            func_id = item.get("id")
            if not func_id:
                continue

            # Extract location id from relationships if available
            loc_rel = (
                item.get("relationships", {})
                .get("functionLocations", {})
                .get("links", {})
                .get("related", "")
            )
            # loc_rel format: "/locations/{id}"
            loc_id = loc_rel.split("/")[-1] if "/locations/" in loc_rel else None

            functions[func_id] = {
                "id": func_id,
                "title": item.get("attributes", {}).get("title", f"Function {func_id}"),
                "types": item.get("meta", {}).get("@type", []),
                "location_id": loc_id,
                "alarm_text": item.get("attributes", {}).get("schneider:alarmText"),
                "widget_id": item.get("attributes", {}).get("schneider:widgetId"),
                "title_base": item.get("attributes", {}).get("schneider:titleBase"),
                "widget_settings": item.get("attributes", {}).get(
                    "schneider:widgetSettings"
                ),
                "datapoints": {},  # Will be populated with associated datapoints
            }
        return functions

    async def get_datapoints(self) -> dict[str, dict[str, Any]]:
        """Retrieve all datapoints mapped by datapoint ID."""
        datapoints = {}
        for item in await self._async_get_items("datapoints"):
            dp_id = item.get("id")
            if not dp_id:
                continue

            attr = item.get("attributes", {})
            meta = item.get("meta", {})
            datapoints[dp_id] = {
                "id": dp_id,
                "title": attr.get("title", ""),
                "value": attr.get("value"),
                "value_type": attr.get("valueType", "string"),
                "readable": attr.get("readable", True),
                "writable": attr.get("writable", False),
                "unit": attr.get("unit", ""),
                "minimum": attr.get("minimum"),
                "maximum": attr.get("maximum"),
                "enum": attr.get("enum", []),
                "parent_function_id": attr.get("schneider:parentFunction"),
                "parent_function_name": attr.get("schneider:parentFunctionName"),
                "parent_location_id": attr.get("schneider:parentLocation"),
                "parent_location_name": attr.get("schneider:parentLocationName"),
                "types": meta.get("@type", []),
            }
        return datapoints

    async def _async_mgmt_get(self, path: str) -> dict[str, Any]:
        """GET a management API path and return its `data` object."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}{MGMT_API_BASE}{path}",
                headers={"Accept": "application/json"},
                auth=self._get_auth(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 403):
                    raise WiserKnxAuthError(f"Unauthorized reading {path}")
                if resp.status != 200:
                    raise WiserKnxConnectionError(f"{path} returned HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise _connection_error(f"Request to {path} failed: {err}", err) from err
        return (body or {}).get("data") or {}

    async def async_get_health(self) -> dict[str, Any]:
        """Return controller health values (firmware, uptime, load, memory, storage)."""
        device_info = await self._async_mgmt_get("/custom/deviceInfo")
        status = await self._async_mgmt_get("/flashsys/Status/SystemStatus")
        return parse_health(device_info, status)

    async def async_get_backup(self, kind_path: str, password: str) -> bytes:
        """Download a password-protected configuration backup from the management API."""
        session = await self._get_session()
        url = f"{self.base_url}{MGMT_API_BASE}{kind_path}"
        try:
            async with session.post(
                url,
                json={"data": {"password": password}},
                headers={
                    "Accept": "application/octet-stream, application/json",
                    "Content-Type": "application/json",
                },
                auth=self._get_auth(),
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status in (401, 403):
                    raise WiserKnxAuthError("Unauthorized creating backup")
                if resp.status == 400:
                    raise WiserKnxConnectionError(
                        "Controller rejected the backup request (check the backup password requirements)"
                    )
                if resp.status != 200:
                    raise WiserKnxConnectionError(
                        f"Backup request to {kind_path} returned HTTP {resp.status}"
                    )
                return await resp.read()
        except aiohttp.ClientError as err:
            raise _connection_error(f"Backup request failed: {err}", err) from err

    async def write_datapoint_value(self, datapoint_id: str, value: Any) -> bool:
        """Write value to a datapoint using PUT /datapoints/values."""
        session = await self._get_session()
        auth = self._get_auth()
        headers = self._get_headers()
        timeout = aiohttp.ClientTimeout(total=8)

        url = f"{self.base_url}{self.api_base}/datapoints/values"
        val_str = str(value)
        if isinstance(value, bool):
            val_str = "on" if value else "off"

        payload = {
            "data": [
                {
                    "id": datapoint_id,
                    "type": "datapoint",
                    "attributes": {
                        "value": val_str,
                    },
                }
            ]
        }

        try:
            async with session.put(
                url,
                json=payload,
                headers=headers,
                auth=auth,
                timeout=timeout,
            ) as resp:
                if resp.status in (200, 201, 202, 204):
                    return True
                if resp.status in (401, 403):
                    raise WiserKnxAuthError("Unauthorized writing datapoint value")
                _LOGGER.warning(
                    "Write datapoint %s returned status %s: %s",
                    datapoint_id,
                    resp.status,
                    await resp.text(),
                )
                return False
        except WiserKnxAuthError:
            raise
        except Exception as err:  # noqa: BLE001 - a write must report failure (False), never crash the service call
            _LOGGER.error("Error writing datapoint %s: %s", datapoint_id, err)
            return False
