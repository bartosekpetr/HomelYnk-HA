"""Wiser for KNX integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WiserKnxClient, WiserKnxConnectionError
from .backup import WiserKnxBackupManager
from .const import (
    CONF_API_BASE,
    CONF_BACKUP_INTERVAL,
    CONF_BACKUP_KEEP,
    CONF_BACKUP_PASSWORD,
    CONF_CERT_FINGERPRINT,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DATA_INITIAL_BACKUP,
    DEFAULT_BACKUP_INTERVAL,
    DEFAULT_BACKUP_KEEP,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ISSUE_INSECURE_HTTP,
    ISSUE_INSECURE_TLS,
    PLATFORMS,
    SERVICE_CREATE_BACKUP,
)
from .coordinator import WiserKnxDataUpdateCoordinator, WiserKnxHealthCoordinator
from .entity import controller_device_info
from .identity import stable_id_from_legacy

_LOGGER = logging.getLogger(__name__)

# Domains this integration used to provide; their entities are removed on setup
_REMOVED_DOMAINS = {"binary_sensor", "cover", "climate"}
# Unique-id suffixes of the sensors this integration still provides
_SENSOR_SUFFIXES = (
    "_last_backup",
    "_firmware",
    "_uptime",
    "_load_1m",
    "_memory_used_percent",
    "_storage_used_percent",
)


def _remove_unsupported_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities created by earlier versions for no longer supported device types."""
    registry = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        is_ours = ent.unique_id.endswith(_SENSOR_SUFFIXES)
        if ent.domain in _REMOVED_DOMAINS or (ent.domain == "sensor" and not is_ours):
            registry.async_remove(ent.entity_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Upgrade config entries: v1 -> v2 stable unique ids, v2 -> v3 explicit TLS setting.

    Entities and devices are keyed by the config entry id, so they are untouched. A legacy
    MAC-based id is rewritten to the plain MAC; an IP-based id is cleared and re-learned from
    the controller (or from discovery) once it is reachable.
    """
    if entry.version > 3:
        return False
    if entry.version == 1:
        new_id = stable_id_from_legacy(entry.unique_id)
        if new_id and any(
            other.unique_id == new_id
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ):
            new_id = None
        hass.config_entries.async_update_entry(entry, unique_id=new_id, version=2)
        _LOGGER.debug("Migrated %s to version 2 (unique id %s)", entry.entry_id, new_id)
    if entry.version == 2:
        # The default for a missing verify_ssl changed from False to True. Pin the value the
        # entry has always effectively used so a working self-signed install keeps working;
        # setup then raises a repair issue asking the user to move to a verified setup.
        if CONF_VERIFY_SSL not in entry.data:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_VERIFY_SSL: False}, version=3
            )
        else:
            hass.config_entries.async_update_entry(entry, version=3)
        _LOGGER.debug("Migrated %s to version 3 (explicit verify_ssl)", entry.entry_id)
    return True


def _sync_transport_issues(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    ssl: bool,
    verify_ssl: bool,
    fingerprint: str | None,
) -> None:
    """Raise or clear the repair issue for the entry's transport.

    The two issues are mutually exclusive: the TLS one needs ssl on, the HTTP one needs it
    off, so at most one is ever active.
    """
    tls_id = ISSUE_INSECURE_TLS.format(entry_id=entry_id)
    http_id = ISSUE_INSECURE_HTTP.format(entry_id=entry_id)
    if ssl and not verify_ssl and not fingerprint:
        ir.async_create_issue(
            hass,
            DOMAIN,
            tls_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="insecure_tls",
            translation_placeholders={"host": host},
            learn_more_url="https://github.com/bartosekpetr/HomelYnk-HA#tls-certificate-verification",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, tls_id)
    if not ssl:
        ir.async_create_issue(
            hass,
            DOMAIN,
            http_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="insecure_http",
            translation_placeholders={"host": host},
            learn_more_url="https://github.com/bartosekpetr/HomelYnk-HA#tls-certificate-verification",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, http_id)


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

    fingerprint = entry.data.get(CONF_CERT_FINGERPRINT)
    # A pinned certificate needs its own connector, which the client builds itself; otherwise
    # the shared HA session already carries the right verify/no-verify TLS context.
    session = (
        None if fingerprint else async_get_clientsession(hass, verify_ssl=verify_ssl)
    )
    client = WiserKnxClient(
        host=host,
        port=port,
        ssl=ssl,
        verify_ssl=verify_ssl,
        fingerprint=fingerprint,
        username=username,
        password=password,
        session=session,
    )

    _sync_transport_issues(hass, entry.entry_id, host, ssl, verify_ssl, fingerprint)

    if entry.data.get(CONF_API_BASE):
        client.api_base = entry.data[CONF_API_BASE]
    else:
        try:
            disc = await client.discover_endpoints()
            client.api_base = disc.get("api_base", "/api/w4knx/3rdparty/v1")
        except WiserKnxConnectionError as err:
            _LOGGER.warning("Endpoint auto-discovery encountered an issue: %s", err)

    coordinator = WiserKnxDataUpdateCoordinator(
        hass=hass,
        client=client,
        config_entry=entry,
        update_interval=scan_interval,
    )

    # Raises ConfigEntryAuthFailed (starts reauth) or ConfigEntryNotReady (retries with backoff)
    await coordinator.async_config_entry_first_refresh()

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

    # Health is best effort: a failure only makes the health sensors unavailable
    coordinator.health = WiserKnxHealthCoordinator(hass, client, entry)
    await coordinator.health.async_refresh()
    device_id = (coordinator.health.data or {}).get("device_id")
    if (
        device_id
        and entry.unique_id is None
        and not any(
            other.unique_id == device_id
            for other in hass.config_entries.async_entries(DOMAIN)
        )
    ):
        hass.config_entries.async_update_entry(entry, unique_id=device_id)
    if coordinator.health.data:
        controller_extra = {
            "sw_version": coordinator.health.data.get("firmware"),
            "hw_version": coordinator.health.data.get("hardware"),
        }
    else:
        controller_extra = {}

    # Register the controller itself so its entities and the function devices attach to it
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **controller_device_info(coordinator, entry.entry_id),
        **controller_extra,
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

    _remove_unsupported_entities(hass, entry)

    pending = hass.data.get(DATA_INITIAL_BACKUP, set())
    # The config flow keys the request by the stable id, or by host when none is known yet
    pending_key = next((k for k in (entry.unique_id, host) if k in pending), None)
    if backup_manager.configured and pending_key is not None:
        pending.discard(pending_key)

        async def _initial_backup() -> None:
            for attempt in (1, 2):
                try:
                    await backup_manager.async_create_backup()
                    return
                except HomeAssistantError as err:
                    _LOGGER.warning(
                        "Initial controller backup attempt %s failed: %s", attempt, err
                    )
                    if attempt == 1:
                        await asyncio.sleep(60)

        entry.async_create_background_task(
            hass, _initial_backup(), "wiser_initial_backup"
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WiserKnxDataUpdateCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id, None
        )
        if coordinator and coordinator.backup_manager:
            coordinator.backup_manager.async_stop()
        if coordinator and coordinator.client:
            await coordinator.client.close()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_CREATE_BACKUP)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the insecure-transport repair issues when their entry is deleted."""
    for template in (ISSUE_INSECURE_TLS, ISSUE_INSECURE_HTTP):
        ir.async_delete_issue(hass, DOMAIN, template.format(entry_id=entry.entry_id))


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
