"""What the coordinator does with a pushed value, and how it notices push died.

The Home Assistant wiring around this (the webhook, the subscription lifecycle,
the watchdog) is not covered here and cannot be: the suite mocks Home Assistant.
What is covered is the part that decides state - applying a callback, and the
liveness check that sends the integration back to full-speed polling.
"""

import asyncio
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.wiser_for_knx.const import (
    PUSH_BACKSTOP_INTERVAL,
    PUSH_MISS_THRESHOLD,
)
from custom_components.wiser_for_knx.coordinator import WiserKnxDataUpdateCoordinator


def _coordinator(datapoints=None, scan_interval=10):
    client = MagicMock()
    coordinator = WiserKnxDataUpdateCoordinator(
        MagicMock(), client, MagicMock(), update_interval=scan_interval
    )
    coordinator.data = {
        "datapoints": datapoints
        if datapoints is not None
        else {"dp1": {"id": "dp1", "value": "off"}}
    }
    coordinator.async_update_listeners = MagicMock()
    coordinator.update_interval = timedelta(seconds=scan_interval)
    return coordinator


def _push(subscribed=True):
    push = MagicMock()
    push.subscribed = subscribed
    return push


# --- applying a callback ---------------------------------------------------


def test_a_callback_updates_the_value_and_the_entities():
    coordinator = _coordinator()
    assert coordinator.async_apply_push_values([{"id": "dp1", "value": "on"}]) == 1
    assert coordinator.data["datapoints"]["dp1"]["value"] == "on"
    coordinator.async_update_listeners.assert_called_once()


def test_a_callback_for_an_unchanged_value_touches_nothing():
    """Push coalesces, so a repeat of the current value is normal and is not news."""
    coordinator = _coordinator()
    assert coordinator.async_apply_push_values([{"id": "dp1", "value": "off"}]) == 0
    coordinator.async_update_listeners.assert_not_called()


def test_a_callback_never_resets_the_poll_timer():
    """A busy installation must not be able to postpone the backstop poll.

    async_set_updated_data would reschedule the next refresh on every frame,
    which on an active installation means the backstop never runs - and the
    backstop is the only thing that notices delivery has stopped.
    """
    coordinator = _coordinator()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_apply_push_values([{"id": "dp1", "value": "on"}])
    coordinator.async_set_updated_data.assert_not_called()


def test_a_callback_for_an_unknown_datapoint_invents_no_state():
    """Which is also the filter for the two automation-trigger virtuals."""
    coordinator = _coordinator()
    assert (
        coordinator.async_apply_push_values(
            [{"id": "11111111-1111-1111-1111-111111111111", "value": "on"}]
        )
        == 0
    )
    assert "11111111-1111-1111-1111-111111111111" not in coordinator.data["datapoints"]
    coordinator.async_update_listeners.assert_not_called()


def test_a_callback_before_the_first_poll_is_dropped():
    coordinator = _coordinator(datapoints={})
    assert coordinator.async_apply_push_values([{"id": "dp1", "value": "on"}]) == 0


@pytest.mark.parametrize(
    ("pushed", "stored"), [("20", "20"), ("on", "on"), (True, "on"), (False, "off")]
)
def test_a_pushed_value_is_stored_in_the_wire_format(pushed, stored):
    """The frame already speaks engineering units, so only the format is normalised."""
    coordinator = _coordinator()
    coordinator.async_apply_push_values([{"id": "dp1", "value": pushed}])
    assert coordinator.data["datapoints"]["dp1"]["value"] == stored


# --- the cadence ----------------------------------------------------------


def test_the_poll_slows_to_the_backstop_and_comes_back():
    coordinator = _coordinator(scan_interval=10)
    coordinator.async_set_push_cadence(True)
    assert coordinator.update_interval == timedelta(seconds=PUSH_BACKSTOP_INTERVAL)
    coordinator.async_set_push_cadence(False)
    assert coordinator.update_interval == timedelta(seconds=10)


def test_the_poll_is_never_switched_off():
    """Every push failure path lands on a real interval, never on None."""
    coordinator = _coordinator(scan_interval=30)
    for backstop in (True, False, True, False):
        coordinator.async_set_push_cadence(backstop)
        assert coordinator.update_interval is not None
        assert coordinator.update_interval.total_seconds() > 0


# --- noticing that delivery stopped ---------------------------------------


def _poll_with(coordinator, values, push):
    """Run the liveness check for a poll that returned `values`."""
    coordinator.push = push
    coordinator._check_push_delivery(
        {dp_id: {"id": dp_id, "value": value} for dp_id, value in values.items()}
    )


def test_two_changes_with_no_callback_in_one_poll_means_delivery_stopped():
    """The daemon can die with the subscription still listed and every endpoint 200."""
    coordinator = _coordinator(
        datapoints={
            "dp1": {"id": "dp1", "value": "off"},
            "dp2": {"id": "dp2", "value": "off"},
        }
    )
    push = _push()
    _poll_with(coordinator, {"dp1": "on", "dp2": "on"}, push)
    push.async_delivery_stopped.assert_called_once_with(PUSH_MISS_THRESHOLD)


def test_one_change_with_no_callback_is_confirmed_over_a_second_poll():
    """One can be a callback in flight while the poll response was on its way."""
    coordinator = _coordinator()
    push = _push()
    _poll_with(coordinator, {"dp1": "on"}, push)
    push.async_delivery_stopped.assert_not_called()
    coordinator.data["datapoints"]["dp1"]["value"] = "on"
    _poll_with(coordinator, {"dp1": "off"}, push)
    push.async_delivery_stopped.assert_called_once()


def test_a_change_a_callback_reported_is_not_a_miss():
    coordinator = _coordinator(
        datapoints={
            "dp1": {"id": "dp1", "value": "off"},
            "dp2": {"id": "dp2", "value": "off"},
        }
    )
    push = _push()
    coordinator.async_apply_push_values(
        [{"id": "dp1", "value": "on"}, {"id": "dp2", "value": "on"}]
    )
    _poll_with(coordinator, {"dp1": "on", "dp2": "on"}, push)
    push.async_delivery_stopped.assert_not_called()


def test_a_clean_poll_clears_the_pending_single_miss():
    coordinator = _coordinator()
    push = _push()
    _poll_with(coordinator, {"dp1": "on"}, push)
    coordinator.data["datapoints"]["dp1"]["value"] = "on"
    _poll_with(coordinator, {"dp1": "on"}, push)  # nothing changed
    coordinator.data["datapoints"]["dp1"]["value"] = "on"
    _poll_with(coordinator, {"dp1": "off"}, push)  # one miss again, but the first
    push.async_delivery_stopped.assert_not_called()


def test_an_optimistic_write_is_not_mistaken_for_a_missed_callback():
    """The write already patched the local copy, so the poll finds no difference."""
    client = MagicMock()
    client.write_datapoint_value = AsyncMock(return_value=True)
    coordinator = _coordinator()
    coordinator.client = client
    push = _push()
    assert asyncio.run(coordinator.async_write_datapoint("dp1", "on")) is True
    _poll_with(coordinator, {"dp1": "on"}, push)
    push.async_delivery_stopped.assert_not_called()


def test_a_new_datapoint_is_not_a_missed_callback():
    """A function is published before its datapoints, so the set grows on its own."""
    coordinator = _coordinator()
    push = _push()
    _poll_with(coordinator, {"dp1": "off", "dp2": "on", "dp3": "on"}, push)
    push.async_delivery_stopped.assert_not_called()


def test_nothing_is_checked_while_there_is_no_subscription():
    coordinator = _coordinator()
    push = _push(subscribed=False)
    _poll_with(coordinator, {"dp1": "on"}, push)
    push.async_delivery_stopped.assert_not_called()


def test_polling_only_needs_no_push_manager():
    coordinator = _coordinator()
    coordinator.push = None
    coordinator._check_push_delivery({"dp1": {"id": "dp1", "value": "on"}})


def test_the_first_poll_cannot_miss_anything():
    coordinator = _coordinator(datapoints={})
    coordinator.data = None
    push = _push()
    _poll_with(coordinator, {"dp1": "on"}, push)
    push.async_delivery_stopped.assert_not_called()


# --- the poll and a callback racing each other ----------------------------


def test_a_callback_during_a_poll_is_not_rolled_back_by_its_answer():
    """The poll's answer is a snapshot from before the callback arrived.

    Letting it land unchanged would put the old value back until the next poll,
    which with push working is a whole backstop interval away.
    """
    coordinator = _coordinator()
    started = 0.0  # anything the callback's timestamp is newer than
    coordinator.async_apply_push_values([{"id": "dp1", "value": "on"}])
    polled = {"dp1": {"id": "dp1", "value": "off"}}  # the stale snapshot
    coordinator._carry_over_pushed(polled, started)
    assert polled["dp1"]["value"] == "on"


def test_a_callback_from_before_the_poll_does_not_override_its_answer():
    """An older callback must not pin a value the poll has since moved on from."""
    coordinator = _coordinator()
    coordinator.async_apply_push_values([{"id": "dp1", "value": "on"}])
    polled = {"dp1": {"id": "dp1", "value": "off"}}
    coordinator._carry_over_pushed(polled, since=time.monotonic() + 1)
    assert polled["dp1"]["value"] == "off"
