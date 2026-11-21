"""DataUpdateCoordinator for Wiser for KNX IoT 3rd Party API."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WiserKnxAuthError,
    WiserKnxCertificateError,
    WiserKnxClient,
    WiserKnxConnectionError,
    WiserKnxServerError,
    format_datapoint_value,
)
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVER_ERROR_HINT_AFTER,
    STATIC_MAX_AGE,
    STATIC_REFRESH_INTERVAL,
    STATIC_RETRY_INTERVAL,
)
from .plan import plan_entities
from .widgets import classify_function

_LOGGER = logging.getLogger(__name__)


class WiserKnxHealthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls controller health (firmware, uptime, load, memory, storage) every few minutes."""

    def __init__(
        self, hass: HomeAssistant, client: WiserKnxClient, config_entry: ConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_health",
            update_interval=timedelta(minutes=5),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_health()
        except Exception as err:
            raise UpdateFailed(f"Error reading controller health: {err}") from err


class WiserKnxDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching KNX IoT data (locations, functions, datapoints) from Wiser."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: WiserKnxClient,
        config_entry: ConfigEntry,
        update_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.backup_manager = None
        self.health: WiserKnxHealthCoordinator | None = None
        # {platform: [entity spec]} for the data of the last successful poll. Computed
        # once per poll here rather than once per platform, because every platform
        # listens for new entities (a function is published before its datapoints).
        self.entity_plan: dict[str, list[dict[str, Any]]] = {}
        # Cache of the slow-changing layer: (locations, functions) as fetched, never mutated.
        self._static: tuple[dict[str, Any], dict[str, Any]] | None = None
        self._static_fetched_at = 0.0  # monotonic time of the last successful fetch
        self._static_next_attempt = 0.0  # monotonic time the next fetch is due
        self._static_failing = False
        # Ids referenced by datapoints that the last static fetch did not know about
        self._unresolved_refs: set[str] = set()
        # Consecutive polls the controller answered with 5xx, for the one-off log hint
        self._server_errors = 0
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_refresh_static(self) -> None:
        """Fetch locations and functions into the cache (raises WiserKnx* errors)."""
        locations = await self.client.get_locations()
        functions = await self.client.get_functions()
        self._static = (locations, functions)
        self._static_fetched_at = time.monotonic()
        self._static_next_attempt = self._static_fetched_at + STATIC_REFRESH_INTERVAL
        if self._static_failing:
            _LOGGER.info(
                "Locations and functions refreshed again after earlier failures"
            )
        self._static_failing = False

    def _unknown_refs(self, datapoints: dict[str, dict[str, Any]]) -> set[str]:
        """Return function/location ids used by datapoints but missing from the cache."""
        locations, functions = self._static or ({}, {})
        unknown: set[str] = set()
        for dp in datapoints.values():
            func_id = dp.get("parent_function_id")
            if func_id and func_id not in functions:
                unknown.add(func_id)
            loc_id = dp.get("parent_location_id")
            if loc_id and loc_id not in locations:
                unknown.add(loc_id)
        return unknown

    async def _async_ensure_static(self, datapoints: dict[str, dict[str, Any]]) -> None:
        """Refresh a warm static cache when it is due or visibly out of date."""
        now = time.monotonic()
        due = now >= self._static_next_attempt
        # Datapoints naming a function/location we do not have mean the controller was
        # reconfigured. Only ids not already unresolved after the previous fetch count, so
        # an orphan datapoint costs one refresh, not one per poll.
        stale_hint = bool(self._unknown_refs(datapoints) - self._unresolved_refs)
        if not (due or stale_hint):
            return
        try:
            await self._async_refresh_static()
        except WiserKnxConnectionError as err:
            # The datapoint poll just succeeded, so the controller is reachable; only the
            # structure refresh failed. Keep serving the cache, retry soon, and give up
            # on the cache once it is too old. Auth/certificate errors are not caught here.
            age = now - self._static_fetched_at
            if age > STATIC_MAX_AGE:
                raise UpdateFailed(
                    f"Locations and functions could not be refreshed for {int(age)} s: {err}"
                ) from err
            log = _LOGGER.debug if self._static_failing else _LOGGER.warning
            log(
                "Could not refresh locations and functions (%s); using data fetched "
                "%d s ago and retrying in %d s",
                err,
                int(age),
                STATIC_RETRY_INTERVAL,
            )
            self._static_failing = True
            self._static_next_attempt = now + STATIC_RETRY_INTERVAL
        self._unresolved_refs = self._unknown_refs(datapoints)

    async def async_refresh_structure(self) -> None:
        """Refetch locations and functions on the next cycle, run now (on demand)."""
        self._static_next_attempt = 0.0
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch datapoints every cycle; locations and functions on a slow cadence."""
        try:
            cold = self._static is None
            if cold:
                # Cold start keeps the original order (locations, functions, datapoints)
                # and any error propagates, so setup fails rather than starting half-blind.
                await self._async_refresh_static()
            datapoints = await self.client.get_datapoints()
            self._server_errors = 0
            if cold:
                self._unresolved_refs = self._unknown_refs(datapoints)
            else:
                await self._async_ensure_static(datapoints)
            locations, cached_functions = self._static
            # Fresh per-cycle copies: datapoints and location ids are attached below and
            # must never leak into (or out of) the cache.
            functions = {
                func_id: {**func, "datapoints": {}}
                for func_id, func in cached_functions.items()
            }

            # Associate datapoints to functions and locations
            for dp_id, dp in datapoints.items():
                p_func_id = dp.get("parent_function_id")
                if p_func_id and p_func_id in functions:
                    functions[p_func_id]["datapoints"][dp_id] = dp

                p_loc_id = dp.get("parent_location_id")
                if (
                    p_loc_id
                    and p_func_id
                    and p_func_id in functions
                    and not functions[p_func_id].get("location_id")
                ):
                    functions[p_func_id]["location_id"] = p_loc_id

            self.entity_plan = plan_entities(functions)
            return {
                "locations": locations,
                "functions": functions,
                "datapoints": datapoints,
            }
        except WiserKnxAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication error communicating with Wiser: {err}"
            ) from err
        except WiserKnxCertificateError as err:
            # Certificate rotated or replaced (or someone is impersonating the controller):
            # start reauth so the user decides, never re-trust automatically.
            raise ConfigEntryAuthFailed(
                f"TLS certificate of the controller is not trusted: {err}"
            ) from err
        except WiserKnxServerError as err:
            # The controller is reachable but cannot answer. The retries in the client
            # are already used up at this point, so this is a longer outage.
            self._server_errors += 1
            if self._server_errors == SERVER_ERROR_HINT_AFTER and "datapoints" in str(
                err
            ):
                _LOGGER.warning(
                    "The controller has refused to list its datapoints %d times in a "
                    "row (%s), so all entities stay unavailable until it answers "
                    "again. Usually it is recomputing which group objects to export; "
                    "it is permanent while a Wiser Touch Danfoss thermostat (floor "
                    "heating) widget has its device status object configured, which "
                    "makes this endpoint fail for as long as the widget exists. See "
                    "docs/controller-api.md",
                    self._server_errors,
                    err,
                )
            raise UpdateFailed(
                f"Error fetching data from Wiser for KNX: {err}"
            ) from err
        except WiserKnxConnectionError as err:
            raise UpdateFailed(
                f"Error fetching data from Wiser for KNX: {err}"
            ) from err

    def _enum_member(self, datapoint_id: str, value: Any) -> Any:
        """Return `value` as the datapoint's own enum member, where it has an enum.

        The controller answers 202 to any well-formed write and then silently
        discards a value that is not a member of `attributes.enum` verbatim: on
        the same writable switch datapoint `on` produces a KNX telegram while
        `1` and `true` produce nothing at all. A value that differs from the
        published member only in spelling is therefore replaced by that member,
        and one that matches no member is logged, because nothing else will
        report it.
        """
        datapoint = (self.data or {}).get("datapoints", {}).get(datapoint_id) or {}
        members = [m for m in (datapoint.get("enum") or []) if isinstance(m, str)]
        if not members:
            return value
        wanted = format_datapoint_value(value).casefold()
        for member in members:
            if member.casefold() == wanted:
                return member
        _LOGGER.warning(
            "Datapoint %s accepts only %s, so the controller will accept and then "
            "discard the value %s",
            datapoint_id,
            ", ".join(repr(m) for m in members),
            repr(format_datapoint_value(value)),
        )
        return value

    async def async_write_datapoint(self, datapoint_id: str, value: Any) -> bool:
        """Write value to datapoint and optimistically update local state."""
        value = self._enum_member(datapoint_id, value)
        success = await self.client.write_datapoint_value(datapoint_id, value)
        if success and self.data and "datapoints" in self.data:
            if datapoint_id in self.data["datapoints"]:
                self.data["datapoints"][datapoint_id]["value"] = format_datapoint_value(
                    value
                )
                self.async_update_listeners()
        return success

    @staticmethod
    def classify_function(func_dict: dict[str, Any]) -> str:
        """Classify a function into a Home Assistant platform category."""
        return classify_function(func_dict)
