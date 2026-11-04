"""Tests for stable controller ids and the v1 -> v2 entry migration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.wiser_for_knx import async_migrate_entry
from custom_components.wiser_for_knx.identity import (
    normalize_mac,
    stable_id_from_device_info,
    stable_id_from_legacy,
)


def test_normalize_mac():
    assert normalize_mac("00:0C:C6:AA:BB:CC") == "00:0c:c6:aa:bb:cc"
    assert normalize_mac("000cc6aabbcc") == "00:0c:c6:aa:bb:cc"
    assert normalize_mac("192.168.1.20") is None
    assert normalize_mac(None) is None


def test_stable_id_prefers_mac_over_serial():
    assert stable_id_from_device_info({"serialNumber": "S1", "macAddress": "000CC6AABBCC"}) == "00:0c:c6:aa:bb:cc"
    assert stable_id_from_device_info({"serialNumber": " S1 "}) == "S1"
    assert stable_id_from_device_info({"fwVersion": "3.1.0"}) is None
    assert stable_id_from_device_info(None) is None


def test_legacy_ids():
    assert stable_id_from_legacy("wiser_knx_000cc6aabbcc") == "00:0c:c6:aa:bb:cc"
    assert stable_id_from_legacy("wiser_knx_192.168.1.20") is None
    assert stable_id_from_legacy(None) is None


def _hass(entries):
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = entries
    return hass


def _entry(entry_id, unique_id, version=1):
    return SimpleNamespace(entry_id=entry_id, unique_id=unique_id, version=version)


def test_migrate_ip_based_entry_clears_id_and_keeps_entry_id():
    entry = _entry("e1", "wiser_knx_192.168.1.20")
    hass = _hass([entry])
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(entry, unique_id=None, version=2)


def test_migrate_mac_based_entry_uses_plain_mac():
    entry = _entry("e1", "wiser_knx_000cc6aabbcc")
    hass = _hass([entry])
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, unique_id="00:0c:c6:aa:bb:cc", version=2
    )


def test_migrate_does_not_duplicate_an_existing_id():
    first = _entry("e1", "00:0c:c6:aa:bb:cc", version=2)
    dup = _entry("e2", "wiser_knx_000cc6aabbcc")
    hass = _hass([first, dup])
    assert asyncio.run(async_migrate_entry(hass, dup)) is True
    hass.config_entries.async_update_entry.assert_called_once_with(dup, unique_id=None, version=2)


def test_migrate_refuses_future_version():
    assert asyncio.run(async_migrate_entry(_hass([]), _entry("e1", None, version=3))) is False
