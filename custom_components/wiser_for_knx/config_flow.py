"""Config flow for Wiser for KNX integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SSL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WiserKnxAuthError, WiserKnxClient, WiserKnxConnectionError
from .const import (
    CONF_API_BASE,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class WiserKnxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wiser for KNX."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._discovered_host: str | None = None
        self._discovered_port: int = DEFAULT_PORT
        self._discovered_hostname: str | None = None
        self._api_base: str = "/api/w4knx/3rdparty/v1"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step triggered by user manually adding integration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            ssl = user_input.get(CONF_SSL, DEFAULT_SSL)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            username = user_input.get(CONF_USERNAME, "").strip() or None
            password = user_input.get(CONF_PASSWORD, "")

            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = WiserKnxClient(
                host=host,
                port=port,
                ssl=ssl,
                verify_ssl=verify_ssl,
                username=username,
                password=password,
                session=session,
            )

            try:
                disc = await client.discover_endpoints()
                self._api_base = disc.get("api_base", "/api/w4knx/3rdparty/v1")

                authenticated = await client.authenticate()
                if not authenticated:
                    errors["base"] = "invalid_auth"
                else:
                    await self.async_set_unique_id(f"wiser_knx_{host}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Wiser for KNX ({host})",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_SSL: ssl,
                            CONF_VERIFY_SSL: verify_ssl,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_API_BASE: self._api_base,
                        },
                    )
            except (WiserKnxAuthError,):
                errors["base"] = "invalid_auth"
            except (WiserKnxConnectionError, Exception) as err:
                _LOGGER.exception("Failed to connect to Wiser for KNX: %s", err)
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._discovered_host or ""): str,
                vol.Required(CONF_PORT, default=self._discovered_port or DEFAULT_PORT): int,
                vol.Optional(CONF_SSL, default=DEFAULT_SSL): bool,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: Any
    ) -> FlowResult:
        """Handle discovery via Zeroconf / mDNS."""
        host = str(discovery_info.ip_address)
        hostname = str(discovery_info.hostname or "wiser-knx").rstrip(".")
        port = int(discovery_info.port or DEFAULT_PORT)

        _LOGGER.info("Zeroconf discovered Wiser for KNX at %s (%s)", host, hostname)

        await self.async_set_unique_id(f"wiser_knx_{host}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

        self._discovered_host = host
        self._discovered_port = port
        self._discovered_hostname = hostname

        self.context["title_placeholders"] = {"name": f"Wiser for KNX ({hostname})"}

        return await self.async_step_credentials()

    async def async_step_dhcp(self, discovery_info: Any) -> FlowResult:
        """Handle discovery via DHCP snooping."""
        host = str(discovery_info.ip)
        mac = str(discovery_info.macaddress)

        _LOGGER.info("DHCP discovered Wiser for KNX at %s (MAC: %s)", host, mac)

        await self.async_set_unique_id(f"wiser_knx_{mac}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self.context["title_placeholders"] = {"name": f"Wiser for KNX ({host})"}

        return await self.async_step_credentials()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt user for credentials after discovery."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, self._discovered_port)
            ssl = user_input.get(CONF_SSL, DEFAULT_SSL)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            username = user_input.get(CONF_USERNAME, "").strip() or None
            password = user_input.get(CONF_PASSWORD, "")

            session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
            client = WiserKnxClient(
                host=host,
                port=port,
                ssl=ssl,
                verify_ssl=verify_ssl,
                username=username,
                password=password,
                session=session,
            )

            try:
                disc = await client.discover_endpoints()
                self._api_base = disc.get("api_base", "/api/w4knx/3rdparty/v1")

                authenticated = await client.authenticate()
                if not authenticated:
                    errors["base"] = "invalid_auth"
                else:
                    return self.async_create_entry(
                        title=f"Wiser for KNX ({self._discovered_hostname or host})",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_SSL: ssl,
                            CONF_VERIFY_SSL: verify_ssl,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_API_BASE: self._api_base,
                        },
                    )
            except Exception as err:
                _LOGGER.exception("Connection verification failed: %s", err)
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._discovered_host or ""): str,
                vol.Required(CONF_PORT, default=self._discovered_port or DEFAULT_PORT): int,
                vol.Optional(CONF_SSL, default=DEFAULT_SSL): bool,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "host": self._discovered_host or "",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get options flow handler."""
        return WiserKnxOptionsFlowHandler(config_entry)


class WiserKnxOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Wiser for KNX."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    int, vol.Range(min=2, max=120)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
