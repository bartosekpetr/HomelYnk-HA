"""Config flow for Wiser for KNX integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import WiserKnxAuthError, WiserKnxClient, WiserKnxConnectionError
from .backup_utils import is_valid_backup_password
from .const import (
    CONF_API_BASE,
    CONF_BACKUP_INTERVAL,
    CONF_BACKUP_KEEP,
    CONF_BACKUP_NOW,
    CONF_BACKUP_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DATA_INITIAL_BACKUP,
    DEFAULT_BACKUP_INTERVAL,
    DEFAULT_API_BASE,
    DEFAULT_BACKUP_KEEP,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .identity import normalize_mac, stable_id_from_device_info

_LOGGER = logging.getLogger(__name__)


class WiserKnxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wiser for KNX."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize config flow."""
        self._discovered_host: str | None = None
        self._discovered_port: int = DEFAULT_PORT
        self._discovered_ssl: bool = DEFAULT_SSL
        self._discovered_hostname: str | None = None
        self._api_base: str = DEFAULT_API_BASE
        self._entry_title: str = ""
        self._entry_data: dict[str, Any] = {}

    async def async_step_backup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure controller backups right after the connection was verified."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input.get(CONF_BACKUP_PASSWORD) or ""
            now = user_input.get(CONF_BACKUP_NOW, False)
            if (password or now) and not is_valid_backup_password(password):
                errors[CONF_BACKUP_PASSWORD] = "invalid_backup_password"
            else:
                options: dict[str, Any] = {
                    CONF_BACKUP_INTERVAL: user_input.get(
                        CONF_BACKUP_INTERVAL, DEFAULT_BACKUP_INTERVAL
                    ),
                    CONF_BACKUP_KEEP: user_input.get(
                        CONF_BACKUP_KEEP, DEFAULT_BACKUP_KEEP
                    ),
                }
                if password:
                    options[CONF_BACKUP_PASSWORD] = password
                    if now:
                        self.hass.data.setdefault(DATA_INITIAL_BACKUP, set()).add(
                            self.unique_id or self._entry_data[CONF_HOST]
                        )
                return self.async_create_entry(
                    title=self._entry_title, data=self._entry_data, options=options
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_BACKUP_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_BACKUP_INTERVAL, default=DEFAULT_BACKUP_INTERVAL
                ): vol.All(int, vol.Range(min=0, max=720)),
                vol.Optional(CONF_BACKUP_KEEP, default=DEFAULT_BACKUP_KEEP): vol.All(
                    int, vol.Range(min=1, max=100)
                ),
                vol.Optional(CONF_BACKUP_NOW, default=True): bool,
            }
        )
        return self.async_show_form(step_id="backup", data_schema=schema, errors=errors)

    def _client(
        self,
        host: str,
        port: int,
        ssl: bool,
        verify_ssl: bool,
        username: str | None = None,
        password: str = "",
    ) -> WiserKnxClient:
        return WiserKnxClient(
            host=host,
            port=port,
            ssl=ssl,
            verify_ssl=verify_ssl,
            username=username,
            password=password,
            session=async_get_clientsession(self.hass, verify_ssl=verify_ssl),
        )

    def _adopt_legacy_entry(self, host: str, unique_id: str | None) -> None:
        """Abort if an entry for this host exists; give it the stable id if it has none yet."""
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_HOST) != host:
                continue
            if unique_id and entry.unique_id is None:
                self.hass.config_entries.async_update_entry(entry, unique_id=unique_id)
            raise AbortFlow("already_configured")

    async def _async_probe_discovered(
        self, host: str, port: int
    ) -> tuple[int, bool] | None:
        """Find the (port, ssl) at which `host` answers /.well-known/knx, or None."""
        candidates = [(port, port != 80), (DEFAULT_PORT, True), (80, False)]
        for cand_port, cand_ssl in dict.fromkeys(candidates):
            client = self._client(host, cand_port, cand_ssl, DEFAULT_VERIFY_SSL)
            if await client.probe() is not None:
                return cand_port, cand_ssl
        return None

    async def _async_try_connect(self, user_input: dict[str, Any]) -> str | None:
        """Connect and authenticate; fill `_entry_data`. Return an error key or None."""
        host = user_input[CONF_HOST].strip()
        port = user_input.get(CONF_PORT, DEFAULT_PORT)
        ssl = user_input.get(CONF_SSL, DEFAULT_SSL)
        verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        username = user_input.get(CONF_USERNAME, "").strip() or None
        password = user_input.get(CONF_PASSWORD, "")
        client = self._client(host, port, ssl, verify_ssl, username, password)

        try:
            disc = await client.discover_endpoints()
            api_base = disc.get("api_base", DEFAULT_API_BASE)
            if not await client.authenticate():
                return "invalid_auth"
            try:
                device_id = stable_id_from_device_info(
                    await client.async_get_device_info()
                )
            except (WiserKnxAuthError, WiserKnxConnectionError) as err:
                _LOGGER.debug("deviceInfo not available: %s", err)
                device_id = None
        except WiserKnxAuthError:
            return "invalid_auth"
        except WiserKnxConnectionError as err:
            _LOGGER.debug(
                "Cannot connect to Wiser for KNX at %s: %s", host, err, exc_info=True
            )
            return "cannot_connect"
        except Exception:  # noqa: BLE001 - last resort so the form never crashes
            _LOGGER.exception(
                "Unexpected error connecting to Wiser for KNX at %s", host
            )
            return "unknown"

        # Prefer the id reported by the controller; keep the discovery id otherwise
        if device_id and device_id != self.unique_id:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._api_base = api_base
        self._entry_data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_SSL: ssl,
            CONF_VERIFY_SSL: verify_ssl,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_API_BASE: api_base,
        }
        return None

    def _credentials_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._discovered_host or ""): str,
                vol.Required(
                    CONF_PORT, default=self._discovered_port or DEFAULT_PORT
                ): int,
                vol.Optional(CONF_SSL, default=self._discovered_ssl): bool,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step triggered by user manually adding integration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            # Duplicate hosts are rejected before any request reaches the controller
            self._async_abort_entries_match({CONF_HOST: host})
            error = await self._async_try_connect(user_input)
            if error is None:
                self._entry_title = f"Wiser for KNX ({host})"
                return await self.async_step_backup()
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=self._credentials_schema(), errors=errors
        )

    async def async_step_zeroconf(self, discovery_info: Any) -> FlowResult:
        """Handle discovery via Zeroconf / mDNS."""
        host = str(discovery_info.ip_address)
        hostname = str(discovery_info.hostname or "wiser-knx").rstrip(".")
        port = int(discovery_info.port or DEFAULT_PORT)
        props = discovery_info.properties or {}
        mac = next(
            (m for m in (normalize_mac(props.get(k)) for k in ("mac", "MAC")) if m),
            None,
        )

        _LOGGER.debug("Zeroconf candidate %s (%s), port %s", host, hostname, port)

        self._adopt_legacy_entry(host, mac)
        if mac:
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # An mDNS name/port is only a hint: confirm a KNX IoT endpoint before prompting
        found = await self._async_probe_discovered(host, port)
        if found is None:
            return self.async_abort(reason="not_wiser_knx")

        self._discovered_host = host
        self._discovered_port, self._discovered_ssl = found
        self._discovered_hostname = hostname
        self.context["title_placeholders"] = {"name": f"Wiser for KNX ({hostname})"}

        return await self.async_step_credentials()

    async def async_step_dhcp(self, discovery_info: Any) -> FlowResult:
        """Handle discovery via DHCP snooping."""
        host = str(discovery_info.ip)
        mac = normalize_mac(str(discovery_info.macaddress))
        if mac is None:
            return self.async_abort(reason="not_wiser_knx")

        _LOGGER.debug("DHCP candidate %s (MAC: %s)", host, mac)

        self._adopt_legacy_entry(host, mac)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # The OUIs cover a vendor's whole range, so confirm it is a KNX IoT controller
        found = await self._async_probe_discovered(host, DEFAULT_PORT)
        if found is None:
            return self.async_abort(reason="not_wiser_knx")

        self._discovered_host = host
        self._discovered_port, self._discovered_ssl = found
        self.context["title_placeholders"] = {"name": f"Wiser for KNX ({host})"}

        return await self.async_step_credentials()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt user for credentials after discovery."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            error = await self._async_try_connect(user_input)
            if error is None:
                self._entry_title = (
                    f"Wiser for KNX ({self._discovered_hostname or host})"
                )
                return await self.async_step_backup()
            errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=self._credentials_schema(),
            errors=errors,
            description_placeholders={
                "host": self._discovered_host or "",
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Start reauthentication after the controller rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for new credentials and verify them against the controller."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "").strip() or None
            password = user_input.get(CONF_PASSWORD, "")
            verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

            client = WiserKnxClient(
                host=entry.data[CONF_HOST],
                port=entry.data.get(CONF_PORT, DEFAULT_PORT),
                ssl=entry.data.get(CONF_SSL, DEFAULT_SSL),
                verify_ssl=verify_ssl,
                username=username,
                password=password,
                session=async_get_clientsession(self.hass, verify_ssl=verify_ssl),
            )
            if entry.data.get(CONF_API_BASE):
                client.api_base = entry.data[CONF_API_BASE]

            try:
                authenticated = await client.authenticate()
            except WiserKnxAuthError:
                errors["base"] = "invalid_auth"
            except WiserKnxConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if authenticated:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_USERNAME: username, CONF_PASSWORD: password},
                    )
                errors["base"] = "invalid_auth"

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_USERNAME,
                    default=entry.data.get(CONF_USERNAME) or DEFAULT_USERNAME,
                ): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get options flow handler."""
        return WiserKnxOptionsFlowHandler()


class WiserKnxOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Wiser for KNX.

    self.config_entry is provided by the base class (HA 2024.12+).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            errors: dict[str, str] = {}
            password = user_input.get(
                CONF_BACKUP_PASSWORD
            ) or self.config_entry.options.get(CONF_BACKUP_PASSWORD)
            if user_input.get(CONF_BACKUP_PASSWORD) and not is_valid_backup_password(
                password
            ):
                errors[CONF_BACKUP_PASSWORD] = "invalid_backup_password"
            if not errors:
                data = {**user_input}
                if password:
                    data[CONF_BACKUP_PASSWORD] = password
                return self.async_create_entry(title="", data=data)
            return self._show_form(errors)

        return self._show_form({})

    def _show_form(self, errors: dict[str, str]) -> FlowResult:
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=2, max=120)),
                vol.Optional(CONF_BACKUP_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_BACKUP_INTERVAL,
                    default=options.get(CONF_BACKUP_INTERVAL, DEFAULT_BACKUP_INTERVAL),
                ): vol.All(int, vol.Range(min=0, max=720)),
                vol.Optional(
                    CONF_BACKUP_KEEP,
                    default=options.get(CONF_BACKUP_KEEP, DEFAULT_BACKUP_KEEP),
                ): vol.All(int, vol.Range(min=1, max=100)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "backup_set": "yes" if options.get(CONF_BACKUP_PASSWORD) else "no",
            },
        )
