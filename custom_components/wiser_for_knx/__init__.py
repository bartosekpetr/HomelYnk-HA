"""Wiser for KNX integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_SSL, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WiserKnxClient
from .backup import WiserKnxBackupManager
from .const import (
    CONF_API_BASE,
    CONF_BACKUP_INTERVAL,
    CONF_BACKUP_KEEP,
    CONF_BACKUP_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_BACKUP_INTERVAL,
    DEFAULT_BACKUP_KEEP,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
    SERVICE_CREATE_BACKUP,
)
from .coordinator import WiserKnxDataUpdateCoordinator
from .entity import controller_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Wiser for KNX from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    ssl = entry.data.get(CONF_SSL, DEFAULT_SSL)
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = WiserKnxClient(
        host=host,
        port=port,
        ssl=ssl,
        verify_ssl=verify_ssl,
        username=username,
        password=password,
        session=session,
    )

    if entry.data.get(CONF_API_BASE):
        client.api_base = entry.data[CONF_API_BASE]
    else:
        try:
            disc = await client.discover_endpoints()
            client.api_base = disc.get("api_base", "/api/w4knx/3rdparty/v1")
        except Exception as err:
            _LOGGER.warning("Endpoint auto-discovery encountered an issue: %s", err)

    coordinator = WiserKnxDataUpdateCoordinator(
        hass=hass,
        client=client,
        update_interval=scan_interval,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Failed to connect or fetch initial objects from Wiser for KNX: %s", err)
        raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    backup_manager = WiserKnxBackupManager(
        hass=hass,
        client=client,
        password=entry.options.get(CONF_BACKUP_PASSWORD),
        interval_hours=entry.options.get(CONF_BACKUP_INTERVAL, DEFAULT_BACKUP_INTERVAL),
        keep=entry.options.get(CONF_BACKUP_KEEP, DEFAULT_BACKUP_KEEP),
    )
    coordinator.backup_manager = backup_manager
    await backup_manager.async_start()

    # Register the controller itself so its entities and the function devices attach to it
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **controller_device_info(coordinator, entry.entry_id),
    )

    if not hass.services.has_service(DOMAIN, SERVICE_CREATE_BACKUP):

        async def _create_backup(call: ServiceCall) -> None:
            managers = [
                c.backup_manager
                for c in hass.data.get(DOMAIN, {}).values()
                if hasattr(c, "backup_manager")
            ]
            for manager in managers:
                await manager.async_create_backup()

        hass.services.async_register(DOMAIN, SERVICE_CREATE_BACKUP, _create_backup)

    # Forward setup to all entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator and coordinator.backup_manager:
            coordinator.backup_manager.async_stop()
        if coordinator and coordinator.client:
            await coordinator.client.close()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_CREATE_BACKUP)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
