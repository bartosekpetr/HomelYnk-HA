"""Options flow driven through real Home Assistant (not collected in the mock environment)."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wiser_for_knx.const import DOMAIN


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    return


def _defaults(result):
    return {
        str(k): k.default() for k in result["data_schema"].schema if callable(k.default)
    }


def _entry(hass, port, ssl):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={
            "host": "h",
            "port": port,
            "ssl": ssl,
            "verify_ssl": True,
            "username": "u",
            "password": "p",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_port_prefilled_and_unchanged_save_keeps_entry(hass):
    entry = _entry(hass, 80, False)
    before = dict(entry.data)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = _defaults(result)
    assert schema["port"] == 80
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=schema
    )
    assert result["type"] == "create_entry"
    assert dict(entry.data) == before


async def test_untick_plain_http_moves_default_port_and_range_is_checked(hass):
    entry = _entry(hass, 80, False)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad = _defaults(result)
    bad["port"] = 70000
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=bad
    )
    assert result["type"] == "form"
    assert result["errors"] == {"port": "invalid_port"}
    good = {**bad, "port": 80, "plain_http": False}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=good
    )
    assert result["type"] == "create_entry"
    assert entry.data["port"] == 443
    assert entry.data["ssl"] is True
