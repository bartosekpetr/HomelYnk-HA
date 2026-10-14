"""Pytest fixtures and lightweight homeassistant mocks for local testing without HA installed."""

import sys
from unittest.mock import MagicMock

# If aiohttp is not installed locally, provide mock
if "aiohttp" not in sys.modules:
    aiohttp_mock = MagicMock()
    sys.modules["aiohttp"] = aiohttp_mock

# If homeassistant is not installed in the local python environment, mock minimal stubs
if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = MagicMock()
    sys.modules["homeassistant.const"] = MagicMock()
    sys.modules["homeassistant.core"] = MagicMock()
    sys.modules["homeassistant.exceptions"] = MagicMock()
    sys.modules["homeassistant.helpers"] = MagicMock()
    sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()
    sys.modules["homeassistant.helpers.device_registry"] = MagicMock()
    sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()

    class _BaseMockCoordinator:
        def __init__(self, *args, **kwargs):
            self.data = {}

        def __class_getitem__(cls, item):
            return cls

    update_coord_mock = MagicMock()
    update_coord_mock.DataUpdateCoordinator = _BaseMockCoordinator
    update_coord_mock.UpdateFailed = Exception
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coord_mock

    sys.modules["homeassistant.components"] = MagicMock()
    sys.modules["homeassistant.components.light"] = MagicMock()
    sys.modules["homeassistant.components.switch"] = MagicMock()
    sys.modules["homeassistant.components.sensor"] = MagicMock()
    sys.modules["homeassistant.components.cover"] = MagicMock()
    sys.modules["homeassistant.components.climate"] = MagicMock()
