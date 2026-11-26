"""Push: the controller's HTTP callback channel wired into Home Assistant.

The controller delivers a datapoint's new value by POSTing to a URL registered
with `POST /subscribe`. This module owns that subscription's whole life - the
webhook Home Assistant answers on, the signing secret, re-asserting the
subscription, noticing that delivery has stopped, and deleting the record on
unload. The pure parts (signature, frame decode, body building) are in
`push_utils.py` and are unit-tested; everything in here needs a running Home
Assistant and is therefore **not** covered by this repository's test suite.

Three measurements shape the whole design (`docs/controller-api.md` §3b):

* 🔴 **Push fails silent and does not self-heal.** The REST surface is
  nginx-embedded Lua; delivery is a separate daemon. Kill the daemon and the
  subscription stays listed, every endpoint keeps answering 200, and nothing on
  the controller restarts it. So the poll never goes away: it slows to a backstop
  while callbacks arrive and comes straight back to the configured interval when
  they stop. Every failure path in here ends in the polling this integration has
  always done, never in stale or unavailable entities.
* 🔴 **A 200 is not evidence that push is flowing, even on a healthy
  controller.** Measured across a reboot: the REST surface answers again at 25 s
  and the first callback lands at 39.6 s, so there is a window in which every
  endpoint answers, the subscription is listed and nothing is delivered. Nothing
  in here reads an accepted subscription as delivery - the cadence only slows
  when a callback has actually arrived.
* 🔴 **A callback is a state notification, not an event.** Sub-second, but
  changes closer than ~0.8 s to one datapoint are coalesced to the latest value.
  Nothing here counts edges.
* 🔴 **A valid signature authorises nothing beyond "this value is now X".** The
  secret is kept in plaintext in the controller's Redis beside the callback URL,
  so it is tamper-evidence on an unauthenticated endpoint, not proof of origin.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import WiserKnxClient, WiserKnxConnectionError
from .const import (
    DOMAIN,
    PUSH_RESUBSCRIBE_DEBOUNCE,
    PUSH_RETRY_INTERVAL,
    PUSH_RETRY_MAX_INTERVAL,
    PUSH_STATUS_DEGRADED,
    PUSH_STATUS_LIVE,
    PUSH_STATUS_OFF,
    PUSH_STATUS_PENDING,
    PUSH_STATUS_UNAVAILABLE,
    PUSH_SUBSCRIBE_CHUNK,
)
from .push_utils import (
    MAX_CALLBACK_BODY,
    callback_path_matches,
    chunked,
    generate_secret,
    parse_callback_body,
    split_callback_url,
    verify_callback_signature,
)

if TYPE_CHECKING:
    from aiohttp.web import Request

    from .coordinator import WiserKnxDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Header names the delivery daemon sends
SIGNATURE_HEADER = "X-Callback-Signature"
DATE_HEADER = "Date"


def webhook_id_for_entry(entry_id: str) -> str:
    """Return this entry's webhook id.

    Derived from the config entry id rather than stored, so it is stable across
    restarts (a subscription left behind by a previous run is recognisable as
    ours) and unique per entry (one entry can never delete another's
    subscription), while nothing extra has to be persisted.

    The id is not a secret and is not treated as one: the endpoint accepts a
    frame only if it carries a valid `X-Callback-Signature`, so knowing the URL
    buys nothing.
    """
    return hashlib.sha256(f"{DOMAIN}:{entry_id}".encode()).hexdigest()[:32]


class WiserKnxPushManager:
    """Owns the push subscription, the callback endpoint and the fallback to polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: WiserKnxClient,
        entry: ConfigEntry,
        coordinator: WiserKnxDataUpdateCoordinator,
        enabled: bool = True,
    ) -> None:
        """Initialize the manager; nothing is registered until async_start."""
        self.hass = hass
        self.client = client
        self.entry = entry
        self.coordinator = coordinator
        self.enabled = enabled
        self.webhook_id = webhook_id_for_entry(entry.entry_id)

        self._path: str | None = None
        self._authority = ""
        self._secret: str | None = None
        self._subscription_ids: list[str] = []
        self._subscribed: set[str] = set()
        self._wanted: set[str] = set()
        self._registered = False

        self._status = PUSH_STATUS_OFF if not enabled else PUSH_STATUS_UNAVAILABLE
        self._reason: str | None = None
        self._frames = 0
        self._rejected = 0
        self._stops = 0
        self._last_frame: float | None = None
        self._last_frame_at: Any = None
        self._retry_delay = PUSH_RETRY_INTERVAL
        self._cancel_retry: Callable[[], None] | None = None
        self._reassert_after = 0.0
        self._asserting = False
        self._listeners: list[Callable[[], None]] = []

    # --- state the diagnostic sensor reads -------------------------------

    @property
    def status(self) -> str:
        """Return `off`, `unavailable`, `pending`, `live` or `degraded`."""
        return self._status

    @property
    def subscribed(self) -> bool:
        """Return True while the controller holds a subscription for this entry."""
        return bool(self._subscription_ids)

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return what the diagnostic sensor shows.

        The signing secret is not in here, and must never be: this ends up in
        the entity's attributes and in any diagnostics payload a user attaches
        to a bug report. The callback **path** is reported but not the host, so
        a shared payload does not carry the user's LAN address.
        """
        attrs: dict[str, Any] = {
            "datapoints_subscribed": len(self._subscribed),
            "callbacks_received": self._frames,
            "callbacks_rejected": self._rejected,
            "delivery_stops": self._stops,
        }
        if self._reason:
            attrs["reason"] = self._reason
        if self._path:
            attrs["callback_path"] = self._path
        if self._last_frame is not None:
            attrs["seconds_since_callback"] = int(time.monotonic() - self._last_frame)
        return attrs

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for status changes; returns the unsubscriber."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _set_status(self, status: str, reason: str | None = None) -> None:
        """Record the status, logging only when it actually changes."""
        if status == self._status and reason == self._reason:
            return
        self._status = status
        self._reason = reason
        if status == PUSH_STATUS_LIVE:
            _LOGGER.info(
                "The controller is pushing datapoint values; polling slows to the backstop"
            )
        elif status == PUSH_STATUS_DEGRADED:
            _LOGGER.warning(
                "The controller stopped delivering datapoint callbacks (%s), so "
                "polling is back at the configured interval and the subscription "
                "will be re-asserted. Nothing on the controller restarts its "
                "delivery daemon; see docs/controller-api.md",
                reason,
            )
        elif status == PUSH_STATUS_UNAVAILABLE:
            _LOGGER.warning(
                "Push could not be set up (%s); the integration keeps polling at "
                "the configured interval instead",
                reason,
            )
        self._notify()

    # --- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Register the callback endpoint and subscribe, or fall back to polling."""
        if not self.enabled:
            self._set_status(PUSH_STATUS_OFF)
            self.coordinator.async_set_push_cadence(False)
            return
        self._wanted = set((self.coordinator.data or {}).get("datapoints") or {})
        await self._async_assert()

    async def async_stop(self) -> None:
        """Unregister the endpoint and delete the subscription.

        A record left behind makes the controller POST at a dead listener for
        ever, so this runs on unload and on reload. Nothing in here is allowed
        to raise: a controller that cannot be reached must not block an unload.
        """
        self._cancel_pending_retry()
        if self._registered:
            try:
                webhook.async_unregister(self.hass, self.webhook_id)
            except (ValueError, KeyError) as err:  # already gone
                _LOGGER.debug("Webhook was not registered: %s", err)
            self._registered = False
        await self._async_drop_subscriptions(reconcile=False)
        self._secret = None
        # Set directly rather than through _set_status: an unload is not a
        # failure and has no business logging a warning about one.
        self._status = PUSH_STATUS_OFF if not self.enabled else PUSH_STATUS_UNAVAILABLE
        self._reason = None if not self.enabled else "unloaded"
        self._notify()

    # --- the callback endpoint -------------------------------------------

    async def _async_handle_callback(
        self, hass: HomeAssistant, webhook_id: str, request: Request
    ) -> None:
        """Verify, decode and apply one callback.

        Always answers 200, whatever happens. What the delivery daemon does with
        a non-200 is not measured, and a frame this integration refuses is its
        own problem to report (the diagnostic sensor counts them), not a reason
        to provoke unmeasured retry behaviour on the controller.
        """
        body = await self._async_read_body(request)
        if body is None:
            return
        if not verify_callback_signature(
            self._secret,
            request.headers.get(SIGNATURE_HEADER),
            self._path or "/",
            self._authority,
            request.headers.get(DATE_HEADER),
            body,
        ):
            self._reject("signature")
            return
        # A valid signature says the frame was not altered on the way here. It
        # does not say who sent it, so it authorises exactly one thing: setting
        # the value of a datapoint this entry subscribed to.
        values = [
            item for item in parse_callback_body(body) if item["id"] in self._subscribed
        ]
        if not values:
            self._reject("no known datapoint")
            return
        self._frames += 1
        self._last_frame = time.monotonic()
        self.coordinator.async_apply_push_values(values)
        if self._status != PUSH_STATUS_LIVE:
            self._set_status(PUSH_STATUS_LIVE)
            self._retry_delay = PUSH_RETRY_INTERVAL
            self._cancel_pending_retry()
        # Delivery is proven for now, so the poll becomes the slow backstop.
        self.coordinator.async_set_push_cadence(True)

    async def _async_read_body(self, request: Request) -> bytes | None:
        """Return the request body, or None if it is too large or unreadable.

        The endpoint cannot require Home Assistant's own auth - the controller
        speaks HTTP Basic and nothing else - and the signature can only be
        checked once the whole body is buffered, so the size is bounded first.
        """
        length = request.content_length
        if length is not None and length > MAX_CALLBACK_BODY:
            self._reject("oversized")
            return None
        try:
            body = await request.read()
        except Exception as err:  # noqa: BLE001 - a broken request is just dropped
            _LOGGER.debug("Could not read a callback body: %s", err)
            self._reject("unreadable")
            return None
        if len(body) > MAX_CALLBACK_BODY:
            self._reject("oversized")
            return None
        return body

    def _reject(self, why: str) -> None:
        """Count a dropped frame; the first one is worth a warning, the rest are not."""
        self._rejected += 1
        log = _LOGGER.warning if self._rejected == 1 else _LOGGER.debug
        log(
            "Dropped a datapoint callback (%s); it has not changed any entity state",
            why,
        )
        self._notify()

    # --- the subscription ------------------------------------------------

    @callback
    def async_note_datapoints(self, datapoint_ids: set[str]) -> None:
        """Take the exported datapoint set from a poll and re-subscribe if it grew.

        A function is published before its datapoints and the export tracks
        widgets being added, so the set changes while the entry is running.
        Without this, a datapoint that appeared after setup would only ever move
        on a backstop poll.
        """
        self._wanted = datapoint_ids
        if not self.enabled or not self.subscribed:
            return  # a retry already owns the next attempt
        if datapoint_ids == self._subscribed:
            return
        if time.monotonic() < self._reassert_after:
            return
        _LOGGER.debug(
            "The controller now exports %d datapoints (subscribed to %d); "
            "re-asserting the subscription",
            len(datapoint_ids),
            len(self._subscribed),
        )
        self._schedule_retry(0)

    @callback
    def async_delivery_stopped(self, missed: int) -> None:
        """A poll found values that no callback reported: delivery has stopped."""
        self._stops += 1
        self._set_status(PUSH_STATUS_DEGRADED, f"{missed} missed")
        self.coordinator.async_set_push_cadence(False)
        self._schedule_retry(PUSH_RETRY_INTERVAL)

    def _resolve_url(self) -> str | None:
        """Return the callback URL to register, or None if there is no usable one.

        The internal URL is preferred and the cloud URL excluded: the controller
        is on the same network, and routing a house's datapoint values through a
        remote endpoint would be absurd. A plain `http://` URL is fine - this
        firmware accepts and honours one against its own HTTPS-only spec - at
        the price of values and signature crossing the LAN in clear text.
        """
        self._path = webhook.async_generate_path(self.webhook_id)
        for internal, external in ((True, False), (False, True)):
            try:
                base = get_url(
                    self.hass,
                    allow_internal=internal,
                    allow_external=external,
                    allow_cloud=False,
                    allow_ip=True,
                    require_ssl=False,
                    require_standard_port=False,
                )
            except NoURLAvailableError:
                continue
            url = f"{base}{self._path}"
            _, self._authority = split_callback_url(url)
            return url
        return None

    def _register_webhook(self) -> bool:
        """Register the callback endpoint; True when it is in place.

        `local_only` is on: the controller sits on the same network as Home
        Assistant, and the endpoint cannot use Home Assistant's authentication,
        so a second gate in front of the signature is worth having.
        """
        if self._registered:
            return True
        try:
            webhook.async_register(
                self.hass,
                DOMAIN,
                "Wiser for KNX datapoint callback",
                self.webhook_id,
                self._async_handle_callback,
                local_only=True,
                allowed_methods=["POST"],
            )
        except ValueError as err:  # already registered by a previous setup
            _LOGGER.debug("Webhook already registered: %s", err)
        self._registered = True
        return True

    async def _async_subscribe(
        self, ids: list[str], url: str, secret: str
    ) -> list[str]:
        """Subscribe to `ids`, in one body if the controller takes it.

        No cap on datapoints per subscribe body has ever been measured, so the
        whole set goes in one request and batching is the *fallback*, not a
        prediction about a limit that may not exist.
        """
        try:
            return [await self.client.async_subscribe_datapoints(ids, url, secret)]
        except WiserKnxConnectionError:
            if len(ids) <= PUSH_SUBSCRIBE_CHUNK:
                raise
            _LOGGER.debug(
                "The controller refused a subscription for %d datapoints; "
                "retrying in batches of %d",
                len(ids),
                PUSH_SUBSCRIBE_CHUNK,
            )
        subscription_ids = []
        for batch in chunked(ids, PUSH_SUBSCRIBE_CHUNK):
            subscription_ids.append(
                await self.client.async_subscribe_datapoints(batch, url, secret)
            )
        return subscription_ids

    async def _async_drop_subscriptions(self, reconcile: bool = True) -> None:
        """Delete this entry's subscriptions, and any orphan pointing at our path.

        An orphan is a record from a previous run of this entry that was never
        deleted - Home Assistant was killed, or the controller was unreachable
        at unload. It is matched by callback path, which is derived from the
        entry id, so this can never delete a subscription belonging to anything
        else. A record whose URL the firmware does not report is left alone
        rather than deleted on a guess.
        """
        for subscription_id in list(self._subscription_ids):
            try:
                await self.client.async_delete_subscription(subscription_id)
            except Exception as err:  # noqa: BLE001 - best effort, never blocks
                _LOGGER.debug(
                    "Could not delete push subscription %s: %s", subscription_id, err
                )
        self._subscription_ids = []
        self._subscribed = set()
        if not reconcile or not self._path:
            return
        try:
            listed = await self.client.async_list_subscriptions()
        except Exception as err:  # noqa: BLE001 - reconciliation is best effort
            _LOGGER.debug("Could not list push subscriptions: %s", err)
            return
        for subscription in listed:
            if not callback_path_matches(subscription, self._path):
                continue
            orphan = subscription.get("id")
            if not orphan:
                continue
            _LOGGER.debug("Deleting an orphaned push subscription (%s)", orphan)
            try:
                await self.client.async_delete_subscription(orphan)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Could not delete subscription %s: %s", orphan, err)

    async def _async_assert(self) -> None:
        """Establish the subscription from scratch, with a fresh secret.

        Re-asserting always deletes first and creates afterwards: whether the
        controller replaces or duplicates a subscription for the same URL is not
        measured, and this depends on neither answer.
        """
        if self._asserting:
            return
        self._asserting = True
        try:
            self._cancel_pending_retry()
            url = self._resolve_url()
            if url is None:
                self._set_status(
                    PUSH_STATUS_UNAVAILABLE, "no reachable Home Assistant URL"
                )
                self.coordinator.async_set_push_cadence(False)
                self._schedule_retry()
                return
            self._register_webhook()
            self._secret = None  # nothing is accepted while there is no subscription
            await self._async_drop_subscriptions()
            ids = sorted(self._wanted)
            if not ids:
                self._set_status(PUSH_STATUS_UNAVAILABLE, "no datapoints exported yet")
                self.coordinator.async_set_push_cadence(False)
                self._schedule_retry()
                return
            secret = generate_secret()
            try:
                subscription_ids = await self._async_subscribe(ids, url, secret)
            except Exception as err:  # noqa: BLE001 - every failure means "keep polling"
                self._set_status(PUSH_STATUS_UNAVAILABLE, f"{type(err).__name__}")
                _LOGGER.debug("Push subscription failed: %s", err)
                self.coordinator.async_set_push_cadence(False)
                self._schedule_retry()
                return
            self._secret = secret
            self._subscription_ids = subscription_ids
            self._subscribed = set(ids)
            self._reassert_after = time.monotonic() + PUSH_RESUBSCRIBE_DEBOUNCE
            self._retry_delay = PUSH_RETRY_INTERVAL
            # Not live yet: the subscription record proves nothing about
            # delivery. Polling stays at the configured interval until a
            # callback actually arrives, so being wrong here costs nothing.
            self._set_status(PUSH_STATUS_PENDING)
            self.coordinator.async_set_push_cadence(False)
            _LOGGER.debug(
                "Subscribed to %d datapoints; callbacks will arrive on %s",
                len(ids),
                self._path,
            )
            # A subscription survives a *clean* controller reboot (measured), but
            # it is a cache entry in the controller's Redis that reaches flash
            # only every 30 minutes, so a power cut can take a recent one with
            # it. An installation can also be quiet for hours, so there is no
            # callback to wait for. Hence a slow beat rather than trusting
            # `GET /subscriptions`, which would list a record either way.
            self._schedule_retry(PUSH_RETRY_MAX_INTERVAL)
        finally:
            self._asserting = False

    def _cancel_pending_retry(self) -> None:
        if self._cancel_retry is not None:
            self._cancel_retry()
            self._cancel_retry = None

    def _schedule_retry(self, delay: float | None = None) -> None:
        """Re-assert the subscription later; backs off when no delay is given."""
        self._cancel_pending_retry()
        if delay is None:
            delay = self._retry_delay
            self._retry_delay = min(self._retry_delay * 2, PUSH_RETRY_MAX_INTERVAL)

        @callback
        def _fire(_now: Any) -> None:
            self._cancel_retry = None
            self.entry.async_create_background_task(
                self.hass, self._async_assert(), f"{DOMAIN}_push_subscribe"
            )

        self._cancel_retry = async_call_later(self.hass, delay, _fire)
