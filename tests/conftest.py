"""Pytest fixtures and lightweight homeassistant mocks for local testing without HA installed."""

import asyncio
import importlib.util
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def retry_sleeps(monkeypatch):
    """Make the client's retry backoff instant and record what it waited for.

    The API client sleeps between its retries of a 5xx. The returned list holds
    the delays it asked for, which is what assertions on the backoff use.

    Requested explicitly, never autouse: this replaces `asyncio.sleep` process
    wide, and the tests that run against a real Home Assistant drive an event
    loop that is entitled to sleep for its own reasons.
    """
    waited: list[float] = []

    async def _sleep(delay):
        waited.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return waited


# If aiohttp is not installed locally, provide mock
if importlib.util.find_spec("aiohttp") is None:
    aiohttp_mock = MagicMock()
    sys.modules["aiohttp"] = aiohttp_mock

# config_flow imports voluptuous; stub it when the local environment lacks it
try:
    import voluptuous  # noqa: F401
except ImportError:
    sys.modules["voluptuous"] = MagicMock()

# If homeassistant is not installed in the local python environment, mock minimal stubs
if importlib.util.find_spec("homeassistant") is None:
    # Tests that need the real HA harness cannot run against these stubs
    collect_ignore = ["test_options_flow_real.py"]
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = MagicMock()
    sys.modules["homeassistant.const"] = MagicMock()
    sys.modules["homeassistant.core"] = MagicMock()
    exceptions_mock = MagicMock()

    class _ConfigEntryAuthFailed(Exception):
        pass

    exceptions_mock.ConfigEntryAuthFailed = _ConfigEntryAuthFailed
    sys.modules["homeassistant.exceptions"] = exceptions_mock
    sys.modules["homeassistant.helpers"] = MagicMock()
    sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()
    sys.modules["homeassistant.helpers.device_registry"] = MagicMock()
    sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
    sys.modules["homeassistant.helpers.entity"] = MagicMock()
    sys.modules["homeassistant.helpers.event"] = MagicMock()
    sys.modules["homeassistant.helpers.selector"] = MagicMock()
    sys.modules["homeassistant.util"] = MagicMock()
    sys.modules["homeassistant.util.dt"] = MagicMock()
    sys.modules["homeassistant.data_entry_flow"] = MagicMock()

    class _MockConfigFlow:
        """Plain base so config flow classes can be subclassed and instantiated in tests."""

        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    _config_entries = sys.modules["homeassistant.config_entries"]
    _config_entries.ConfigFlow = _MockConfigFlow
    _config_entries.OptionsFlow = _MockConfigFlow
    ha_mock.config_entries = (
        _config_entries  # `from homeassistant import config_entries`
    )

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
    sys.modules["homeassistant.components.button"] = MagicMock()
    sys.modules["homeassistant.components.binary_sensor"] = MagicMock()
    sys.modules["homeassistant.components.switch"] = MagicMock()
    sys.modules["homeassistant.components.sensor"] = MagicMock()
    sys.modules["homeassistant.components.cover"] = MagicMock()
    sys.modules["homeassistant.components.climate"] = MagicMock()

    class _MockCoordinatorEntity:
        """Stand-in for CoordinatorEntity: a real class, so platforms can subclass it.

        A MagicMock attribute cannot be used as a base class (metaclass conflict),
        which is why the light and switch entities need this. `available` mirrors
        the real implementation so entity tests exercise their own logic.
        """

        _attr_has_entity_name = False

        def __init__(self, coordinator, *args, **kwargs):
            self.coordinator = coordinator

        def __class_getitem__(cls, item):
            return cls

        @property
        def available(self):
            return bool(self.coordinator.last_update_success)

    update_coord_mock.CoordinatorEntity = _MockCoordinatorEntity
    sys.modules["homeassistant.components.light"].LightEntity = _MockCoordinatorEntity
    sys.modules["homeassistant.components.light"].ATTR_BRIGHTNESS = "brightness"
    sys.modules["homeassistant.components.switch"].SwitchEntity = _MockCoordinatorEntity
