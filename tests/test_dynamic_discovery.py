"""Entities appear as the controller publishes them, and are never removed.

Two measured controller behaviours make this load-bearing:

* a function is served **before** its datapoints - 2-13 s on a quiet
  controller, minutes while several widgets are being edited - so a platform
  that enumerates once at setup creates devices with no entities;
* `GET /datapoints` answers 500 now and then, and permanently while a Danfoss
  floor-heating widget has its device-status object set, so a datapoint missing
  from a poll is "no new information", never a deletion.
"""

from unittest.mock import MagicMock

from custom_components.wiser_for_knx.entity import async_setup_plan_entities
from custom_components.wiser_for_knx.plan import plan_entities


def _dp(dp_id, dpa, dpt, writable=True, **kwargs):
    return {
        "id": dp_id,
        "title": dp_id,
        "types": [dpa, dpt],
        "writable": writable,
        "unit": kwargs.pop("unit", ""),
        "value": kwargs.pop("value", "on"),
        **kwargs,
    }


SWITCH = _dp("sw", "dic:dpa.417.70", "urn:knx:dpt.switch")
POWER = _dp("pw", "dic:dpa.901.51", "urn:knx:dpt.power", False, unit="W", value="41.5")


def _function(*datapoints):
    return {
        "f1": {
            "id": "f1",
            "title": "Socket",
            "types": ["urn:knx:fct.switchingSocket"],
            "datapoints": {dp["id"]: dp for dp in datapoints},
        }
    }


class _Harness:
    """The pieces `async_setup_plan_entities` talks to."""

    def __init__(self, functions):
        self.coordinator = MagicMock()
        self.coordinator.data = {"functions": functions}
        self.coordinator.entity_plan = plan_entities(functions)
        self.listeners = []
        self.coordinator.async_add_listener = self.listeners.append
        self.entry = MagicMock()
        self.entry.async_on_unload = lambda func: func
        self.added = []

    def add_entities(self, entities):
        self.added.extend(entities)

    def poll(self, functions):
        """Replace the coordinator's data and fire the listener, as a poll does."""
        self.coordinator.data = {"functions": functions}
        self.coordinator.entity_plan = plan_entities(functions)
        for listener in self.listeners:
            listener()

    def setup(self, platform):
        async_setup_plan_entities(
            self.coordinator,
            self.entry,
            platform,
            lambda spec: spec["key"],
            self.add_entities,
        )


def test_a_function_without_datapoints_yields_nothing_yet():
    harness = _Harness(_function())
    harness.setup("switch")
    assert harness.added == []


def test_the_entity_appears_once_its_datapoints_attach():
    harness = _Harness(_function())
    harness.setup("switch")
    harness.poll(_function(SWITCH))
    assert harness.added == ["f1"]


def test_a_later_datapoint_adds_its_own_entity():
    harness = _Harness(_function(SWITCH))
    harness.setup("sensor")
    assert harness.added == []
    harness.poll(_function(SWITCH, POWER))
    assert harness.added == ["pw"]


def test_an_entity_is_added_once_however_often_the_poll_repeats():
    harness = _Harness(_function(SWITCH))
    harness.setup("switch")
    for _ in range(3):
        harness.poll(_function(SWITCH))
    assert harness.added == ["f1"]


def test_a_failed_poll_removes_nothing_and_recovery_adds_nothing_twice():
    """A refused poll is no new information: the plan of the last good poll stands.

    The coordinator only replaces its plan after a poll that succeeded, so a
    failure leaves the entities in place (unavailable, because the coordinator
    reports the failure) and the next good poll does not add them again.
    """
    harness = _Harness(_function(SWITCH))
    harness.setup("switch")
    assert harness.added == ["f1"]

    harness.coordinator.data = None  # as an UpdateFailed leaves it
    for listener in harness.listeners:
        listener()
    assert harness.added == ["f1"]

    harness.poll(_function(SWITCH))
    assert harness.added == ["f1"]
