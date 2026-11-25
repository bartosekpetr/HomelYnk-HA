"""DataUpdateCoordinator for Wiser for KNX IoT 3rd Party API."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    PUSH_BACKSTOP_INTERVAL,
    PUSH_MISS_THRESHOLD,
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
        # The push manager, attached by async_setup_entry. None means this entry
        # polls and nothing else, which is also every failure path's destination.
        self.push: Any = None
        # The configured scan interval. The poll slows to PUSH_BACKSTOP_INTERVAL
        # while callbacks are arriving and comes back to this the moment they are
        # not, so the fallback cadence has to survive the switch.
        self._poll_interval = update_interval
        # datapoint id -> monotonic time a callback last reported it
        self._push_seen: dict[str, float] = {}
        self._last_poll_at = 0.0
        # Consecutive polls that found a value changed with no callback for it
        self._push_miss_polls = 0
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

    @callback
    def async_apply_push_values(self, values: list[dict[str, Any]]) -> int:
        """Apply datapoint values delivered by a callback; return how many changed.

        A callback is a **state notification, not an event**: changes to one
        datapoint closer together than about 0.8 s are coalesced and only the
        latest is delivered (8 transitions 0.4 s apart arrived as 4). So each
        value is applied as "this is the current value" and nothing here counts
        edges or reconstructs a sequence.

        The value needs no conversion: it arrives as a string in the same
        engineering units as `GET /datapoints`, so the one decoder in
        `datapoints.py` serves both paths.

        A datapoint this poll has never seen is ignored. That is also the filter
        the measurement asks for - a subscription silently includes the two
        automation-trigger virtuals - and it keeps a frame from inventing state
        for an id the entity graph does not know.
        """
        datapoints = (self.data or {}).get("datapoints")
        if not datapoints:
            return 0
        now = time.monotonic()
        changed = 0
        for item in values:
            dp_id = item.get("id")
            datapoint = datapoints.get(dp_id)
            if datapoint is None:
                continue
            self._push_seen[dp_id] = now
            value = format_datapoint_value(item.get("value"))
            if datapoint.get("value") != value:
                datapoint["value"] = value
                changed += 1
        if changed:
            # Deliberately not async_set_updated_data: that would reset the poll
            # timer on every callback and a busy installation would postpone the
            # backstop poll for ever. Patch and notify, as the optimistic write
            # path does.
            self.async_update_listeners()
        return changed

    def _carry_over_pushed(
        self, datapoints: dict[str, dict[str, Any]], since: float
    ) -> None:
        """Keep values a callback delivered while this poll was still in flight.

        The poll's answer is a snapshot taken before that callback arrived, so
        letting it land unchanged would roll the entity back to the old value
        until the next poll - which, with push working, is a whole backstop
        interval away.
        """
        held = (self.data or {}).get("datapoints") or {}
        for dp_id, seen_at in self._push_seen.items():
            if seen_at < since:
                continue
            pushed = held.get(dp_id)
            polled = datapoints.get(dp_id)
            if pushed is None or polled is None:
                continue
            polled["value"] = pushed.get("value")

    def _push_missed(self, datapoints: dict[str, dict[str, Any]]) -> list[str]:
        """Datapoints whose value changed since the last poll with no callback for it.

        This is the only liveness signal there is. Nothing in the API
        distinguishes "subscribed and quiet" from "subscribed and dead": the
        record stays listed and every endpoint keeps answering 200 while the
        delivery daemon is gone. So the backstop poll doubles as the probe, and a
        change it finds that no callback reported is what gives the daemon away.

        A value this integration wrote itself is already in the local copy, so an
        optimistic write cannot be mistaken for a missed callback.
        """
        previous = (self.data or {}).get("datapoints") or {}
        if not previous:
            return []
        missed = []
        for dp_id, datapoint in datapoints.items():
            before = previous.get(dp_id)
            if before is None or datapoint.get("value") == before.get("value"):
                continue
            if self._push_seen.get(dp_id, -1.0) >= self._last_poll_at:
                continue
            missed.append(dp_id)
        return missed

    def _check_push_delivery(self, datapoints: dict[str, dict[str, Any]]) -> None:
        """Tell the push manager when a poll proves delivery has stopped."""
        if self.push is None or not self.push.subscribed:
            return
        missed = self._push_missed(datapoints)
        if not missed:
            self._push_miss_polls = 0
            return
        self._push_miss_polls += 1
        # One missed datapoint can be the race between a poll response and a
        # callback still in flight, so one is confirmed over a second poll.
        # Several in one poll is delivery having stopped.
        if len(missed) >= PUSH_MISS_THRESHOLD or self._push_miss_polls > 1:
            self._push_miss_polls = 0
            self.push.async_delivery_stopped(len(missed))

    @callback
    def async_set_push_cadence(self, backstop: bool) -> None:
        """Slow the poll to the backstop, or put it back on the configured interval.

        The poll is never switched off. Push fails silent, nothing on the
        controller restarts the daemon that delivers it, and a reboot is not a
        reliable fix either, so the only safe destination for every failure path
        is the polling this integration has always done.
        """
        wanted = timedelta(
            seconds=PUSH_BACKSTOP_INTERVAL if backstop else self._poll_interval
        )
        if self.update_interval == wanted:
            return
        _LOGGER.debug(
            "Polling every %s s (%s)",
            int(wanted.total_seconds()),
            "push is delivering" if backstop else "push is not delivering",
        )
        self.update_interval = wanted

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
            started = time.monotonic()
            datapoints = await self.client.get_datapoints()
            self._server_errors = 0
            self._carry_over_pushed(datapoints, started)
            self._check_push_delivery(datapoints)
            self._last_poll_at = time.monotonic()
            # Ids the controller no longer exports, so the map cannot grow for ever
            self._push_seen = {
                dp_id: at
                for dp_id, at in self._push_seen.items()
                if dp_id in datapoints
            }
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
            if self.push is not None:
                # A function is published before its datapoints, so the exported
                # set grows after setup. Whatever appeared since the last
                # subscribe has to be added to it or those entities would only
                # ever move on a backstop poll.
                self.push.async_note_datapoints(set(datapoints))
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
