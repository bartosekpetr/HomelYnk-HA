"""Pytest fixtures and lightweight homeassistant mocks for local testing without HA installed."""

import asyncio
import enum
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
    const_mock = MagicMock()
    # Service call kwargs are keyed by these, so they have to be the real strings
    const_mock.ATTR_TEMPERATURE = "temperature"
    sys.modules["homeassistant.const"] = const_mock
    core_mock = MagicMock()
    # @callback must return the function, not a MagicMock wrapping it
    core_mock.callback = lambda func: func
    sys.modules["homeassistant.core"] = core_mock
    exceptions_mock = MagicMock()

    class _ConfigEntryAuthFailed(Exception):
        pass

    class _HomeAssistantError(Exception):
        pass

    exceptions_mock.ConfigEntryAuthFailed = _ConfigEntryAuthFailed
    # Real class, not a MagicMock: backup.py raises it and tests assert on it.
    exceptions_mock.HomeAssistantError = _HomeAssistantError
    sys.modules["homeassistant.exceptions"] = exceptions_mock
    sys.modules["homeassistant.helpers"] = MagicMock()
    sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()
    sys.modules["homeassistant.helpers.device_registry"] = MagicMock()
    sys.modules["homeassistant.helpers.entity_registry"] = MagicMock()
    sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
    sys.modules["homeassistant.helpers.entity"] = MagicMock()
    sys.modules["homeassistant.helpers.event"] = MagicMock()
    sys.modules["homeassistant.helpers.selector"] = MagicMock()
    network_mock = MagicMock()

    class _NoURLAvailableError(Exception):
        """Real class, not a MagicMock: push.py catches it when no URL is usable."""

    network_mock.NoURLAvailableError = _NoURLAvailableError
    sys.modules["homeassistant.helpers.network"] = network_mock
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
    for _component in (
        "light",
        "button",
        "binary_sensor",
        "switch",
        "sensor",
        "cover",
        "climate",
        "lock",
        "select",
        "number",
        "webhook",
    ):
        sys.modules[f"homeassistant.components.{_component}"] = MagicMock()

    class _MockEntity:
        """Stand-in for `homeassistant.helpers.entity.Entity`.

        A MagicMock attribute cannot be used as a base class (metaclass
        conflict), so the entity classes need real ones. Home Assistant's
        CoordinatorEntity and the platform entities are *siblings* under Entity,
        and the integration's entities inherit from one of each - so they have
        to be siblings here too, or the MRO cannot be built.
        """

        _attr_has_entity_name = False

        def __class_getitem__(cls, item):
            return cls

        def async_on_remove(self, func):
            return func

        def async_write_ha_state(self):
            return None

    class _MockPlatformEntity(_MockEntity):
        """Stand-in for LightEntity, SensorEntity, CoverEntity and the rest.

        `options` is here because the real `SensorEntity` has it: it returns
        `_attr_options`, and an entity that sets the attribute and reads the
        property is the ordinary Home Assistant pattern. Without it a test that
        reads `sensor.options` passes in CI, against the real package, and fails
        on a machine where `homeassistant` is not importable - the local/CI trap
        of AGENTS.md §5 pointing the other way for once.
        """

        @property
        def options(self):
            return getattr(self, "_attr_options", None)

    class _MockCoordinatorEntity(_MockEntity):
        """Stand-in for CoordinatorEntity.

        `available` mirrors the real implementation so entity tests exercise
        their own logic.
        """

        def __init__(self, coordinator, *args, **kwargs):
            self.coordinator = coordinator

        @property
        def available(self):
            return bool(self.coordinator.last_update_success)

    update_coord_mock.CoordinatorEntity = _MockCoordinatorEntity

    class _MockClimateEntity(_MockPlatformEntity):
        """Climate's defaults for the limits an entity may fall back to."""

        @property
        def min_temp(self):
            return 7

        @property
        def max_temp(self):
            return 35

    # The feature flags and HVAC modes are real enums, so platform tests can assert
    # on what a function's datapoints ended up supporting. Values match Home
    # Assistant's own.
    class _CoverEntityFeature(enum.IntFlag):
        OPEN = 1
        CLOSE = 2
        SET_POSITION = 4
        STOP = 8
        OPEN_TILT = 16
        CLOSE_TILT = 32
        STOP_TILT = 64
        SET_TILT_POSITION = 128

    class _ClimateEntityFeature(enum.IntFlag):
        TARGET_TEMPERATURE = 1
        TARGET_TEMPERATURE_RANGE = 2
        TARGET_HUMIDITY = 4
        FAN_MODE = 8
        PRESET_MODE = 16
        SWING_MODE = 32
        TURN_OFF = 128
        TURN_ON = 256

    class _HVACMode(enum.StrEnum):
        OFF = "off"
        HEAT = "heat"
        COOL = "cool"
        HEAT_COOL = "heat_cool"
        AUTO = "auto"
        DRY = "dry"
        FAN_ONLY = "fan_only"

    light_mock = sys.modules["homeassistant.components.light"]
    light_mock.LightEntity = _MockPlatformEntity
    light_mock.ATTR_BRIGHTNESS = "brightness"
    light_mock.ATTR_RGB_COLOR = "rgb_color"
    light_mock.ATTR_RGBW_COLOR = "rgbw_color"
    sys.modules["homeassistant.components.switch"].SwitchEntity = _MockPlatformEntity
    sys.modules["homeassistant.components.cover"].CoverEntity = _MockPlatformEntity
    sys.modules[
        "homeassistant.components.cover"
    ].CoverEntityFeature = _CoverEntityFeature
    climate_mock = sys.modules["homeassistant.components.climate"]
    climate_mock.ClimateEntity = _MockClimateEntity
    climate_mock.ClimateEntityFeature = _ClimateEntityFeature
    climate_mock.HVACMode = _HVACMode
    sys.modules["homeassistant.components.lock"].LockEntity = _MockPlatformEntity
    sys.modules["homeassistant.components.select"].SelectEntity = _MockPlatformEntity
    sys.modules["homeassistant.components.number"].NumberEntity = _MockPlatformEntity
    sys.modules["homeassistant.components.button"].ButtonEntity = _MockPlatformEntity
    sys.modules["homeassistant.components.sensor"].SensorEntity = _MockPlatformEntity
    sys.modules[
        "homeassistant.components.binary_sensor"
    ].BinarySensorEntity = _MockPlatformEntity
