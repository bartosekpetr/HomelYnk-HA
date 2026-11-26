"""The diagnostics payload: what it reports, and what it must never carry.

The payload is the evidence this project has never had - no entity list has ever
been taken from a running Home Assistant - so these tests pin the two things
that make it worth asking for: the decisions are reported next to their result
(a function's category, whether its composite was viable, every datapoint's
archetype and role), and nothing identifying leaves with it.

Only the pure half is exercised here; `diagnostics.py` reads the two registries
and the suite mocks Home Assistant, so that half has to be seen in a real one.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.wiser_for_knx.diagnostics_utils import (
    REDACTED,
    build_diagnostics,
    entity_review,
    function_rows,
    redact,
)


def _dp(dp_id, dpa, dpt, writable=False, **kwargs):
    return {
        "id": dp_id,
        "title": kwargs.pop("title", dp_id),
        "types": [dpa, dpt],
        "writable": writable,
        "unit": kwargs.pop("unit", ""),
        "value": kwargs.pop("value", None),
        **kwargs,
    }


def _func(func_id, types, *datapoints, title=None):
    return {
        func_id: {
            "id": func_id,
            "title": title or func_id,
            "types": types,
            "datapoints": {dp["id"]: dp for dp in datapoints},
        }
    }


_DIMMER = _func(
    "f1",
    ["urn:knx:fct.dimming"],
    _dp("sw", "dic:dpa.418.61", "urn:knx:dpt.switch", True, value="on"),
    _dp("br", "dic:dpa.418.63", "urn:knx:dpt.scaling", True, unit="%", value="50"),
    title="Kitchen ceiling",
)

# A light whose dimmer slot is read-only: the category promises a light and the
# datapoints cannot drive one, so the function degrades to loose entities. This
# is the shape that looks wrong on the device page while working as designed.
_DEGRADED = _func(
    "f2",
    ["urn:knx:fct.dimming"],
    _dp("ro", "dic:dpa.418.63", "urn:knx:dpt.scaling", False, unit="%", value="50"),
)


def _payload(functions, **kwargs):
    datapoints = {
        dp_id: dp
        for func in functions.values()
        for dp_id, dp in func["datapoints"].items()
    }
    return build_diagnostics(
        entry=kwargs.pop(
            "entry",
            {
                "version": 1,
                "source": "user",
                "unique_id": "001122334455",
                "data": {
                    "host": "192.168.1.x",
                    "username": "admin",
                    "password": "s3cr3t",
                },
                "options": {"backup_password": "Backup123", "push": True},
            },
        ),
        controller=kwargs.pop("controller", {"push": {"status": "live"}}),
        functions=functions,
        datapoints=datapoints,
        plan=kwargs.pop("plan", {"light": [{"key": "f1"}]}),
        entities=kwargs.pop("entities", []),
        devices=kwargs.pop("devices", []),
    )


def test_a_viable_composite_reports_its_datapoints_as_consumed():
    row = function_rows(_DIMMER)[0]
    assert row["category"] == "light"
    assert row["composite_platform"] == "light"
    assert row["composite_viable"] is True
    assert [dp["consumed_by_composite"] for dp in row["datapoints"]] == [True, True]
    assert [dp["role"] for dp in row["datapoints"]] == ["brightness", "switch"]
    assert [dp["dpa"] for dp in row["datapoints"]] == [
        "dic:dpa.418.63",
        "dic:dpa.418.61",
    ]


def test_a_function_that_could_not_become_its_composite_is_called_out():
    """The first thing to check against a report of a light that is not a light."""
    payload = _payload({**_DIMMER, **_DEGRADED})
    degraded = payload["review"]["composite_not_viable"]
    assert [item["function_id"] for item in degraded] == ["f2"]
    assert degraded[0]["category"] == "light"
    assert degraded[0]["roles"] == ["brightness"]
    # Nothing writable is why it degraded, and that is the line to read
    assert degraded[0]["writable_roles"] == []
    # The datapoint still becomes an entity; it is a sensor, not a light
    row = next(row for row in payload["functions"] if row["id"] == "f2")
    assert row["datapoints"][0]["platform"] == "sensor"


def test_a_datapoint_without_a_title_is_reported_as_named_by_its_role():
    """A missing group object name is what puts a role or a raw id on an entity."""
    functions = _func(
        "f3",
        ["urn:knx:fct.switchingSocket"],
        _dp(
            "pw",
            "dic:dpa.901.51",
            "urn:knx:dpt.power",
            unit="W",
            value="41.5",
            title="",
        ),
    )
    payload = _payload(functions)
    assert payload["review"]["datapoints_without_title"] == [
        {"datapoint_id": "pw", "named_by": "role"}
    ]


def test_an_archetype_with_no_measured_role_is_listed_for_measurement():
    functions = _func(
        "f4",
        ["urn:knx:fct.switching"],
        _dp("odd", "dic:dpa.999.99", "urn:knx:dpt.value2Count", value="7"),
    )
    payload = _payload(functions)
    assert payload["review"]["datapoints_without_role"] == [
        {
            "datapoint_id": "odd",
            "dpa": "dic:dpa.999.99",
            "dpt": "urn:knx:dpt.value2Count",
        }
    ]


def test_the_export_counts_distinguish_writable_and_orphan_datapoints():
    functions = _func(
        "f5",
        ["urn:knx:fct.switchingSocket"],
        _dp("sw", "dic:dpa.417.70", "urn:knx:dpt.switch", True, value="on"),
        _dp("pw", "dic:dpa.901.51", "urn:knx:dpt.power", unit="W", value="41.5"),
    )
    datapoints = dict(functions["f5"]["datapoints"])
    # A datapoint naming a function the structure cache does not know: the export
    # moved since the last structure refresh, which is a normal controller state.
    datapoints["ghost"] = _dp(
        "ghost", "dic:dpa.417.70", "urn:knx:dpt.switch", parent_function_id="gone"
    )
    payload = build_diagnostics(
        entry={},
        controller={},
        functions=functions,
        datapoints=datapoints,
        plan={"switch": [{"key": "f5"}], "sensor": [{"key": "pw"}]},
        entities=[],
        devices=[],
    )
    assert payload["export"] == {
        "functions": 1,
        "datapoints": 3,
        "writable_datapoints": 1,
        "orphan_datapoints": 1,
    }
    assert payload["plan"] == {"counts": {"sensor": 1, "switch": 1}, "total": 2}


def test_unavailable_unknown_and_disambiguated_entities_are_ranked_first():
    entities = [
        {"entity_id": "light.kitchen", "name": "Kitchen", "state": "on"},
        {"entity_id": "sensor.power", "original_name": "Power", "state": "unavailable"},
        {"entity_id": "sensor.setpoint", "original_name": "Setpoint", "state": None},
        {"entity_id": "sensor.nameless", "state": "unknown"},
        {"entity_id": "switch.fan_2", "original_name": "Fan", "state": "off"},
        # A legitimate name that ends in a digit is not a disambiguated id
        {"entity_id": "light.hall_2", "original_name": "Hall 2", "state": "on"},
        {
            "entity_id": "button.scene_1",
            "original_name": "Scene",
            "state": "unknown",
            "disabled_by": "user",
        },
    ]
    review = entity_review(entities)
    assert review["unavailable"] == ["sensor.power"]
    assert review["unknown_or_no_state"] == [
        "sensor.setpoint",
        "sensor.nameless",
        "button.scene_1",
    ]
    assert review["unnamed"] == ["sensor.nameless"]
    assert review["numeric_suffix"] == ["switch.fan_2", "button.scene_1"]
    assert review["disabled"] == ["button.scene_1"]


def test_an_entity_row_keeps_the_id_tail_of_its_unique_id_and_its_device():
    payload = _payload(
        _DIMMER,
        entities=[
            {
                "entity_id": "light.kitchen_ceiling",
                "unique_id": "wiser_for_knx_01JABCDEF_f1",
                "original_name": None,
                "device_id": "ha_device_1",
                "state": "on",
            }
        ],
    )
    row = payload["entities"][0]
    # The entry id in the middle changes on a re-add and is noise; the tail ties
    # the entity back to the function or datapoint it came from.
    assert row["unique_id_suffix"] == "f1"
    assert row["device"] == "ha_device_1"
    assert row["has_custom_name"] is False
    assert payload["registry"]["by_domain"] == {"light": 1}


def test_nothing_identifying_leaves_with_the_payload():
    payload = _payload(_DIMMER)
    assert payload["entry"]["data"]["password"] == REDACTED
    assert payload["entry"]["data"]["username"] == REDACTED
    assert payload["entry"]["data"]["host"] == REDACTED
    assert payload["entry"]["options"]["backup_password"] == REDACTED
    # The MAC or serial the stable unique id is derived from
    assert payload["entry"]["unique_id"] == REDACTED
    # The option that is not a secret survives, or the file answers nothing
    assert payload["entry"]["options"]["push"] is True


def test_the_controller_identity_and_the_callback_path_are_redacted_at_depth():
    payload = _payload(
        _DIMMER,
        controller={
            "health": {"device_id": "001122334455", "firmware": "3.1.0"},
            "push": {"status": "live", "callback_path": "/api/webhook/abc123"},
        },
    )
    assert payload["controller"]["health"]["device_id"] == REDACTED
    assert payload["controller"]["health"]["firmware"] == "3.1.0"
    assert payload["controller"]["push"]["callback_path"] == REDACTED


def test_redaction_leaves_a_missing_value_missing():
    """An absent optional stays None, so a reader can tell it apart from a secret."""
    assert redact({"password": None, "host": None}) == {"password": None, "host": None}


class _FakeRegistryEntity:
    """A registry row as Home Assistant hands it over."""

    def __init__(self, entity_id, unique_id, original_name, category=None):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.name = None
        self.original_name = original_name
        self.device_id = "ha_device_1"
        # Registry fields arrive as enums or as strings depending on the field,
        # which is why the payload asks for `.value` and falls back to the value.
        self.entity_category = category
        self.disabled_by = None
        self.hidden_by = None


class _FakeEnum:
    def __init__(self, value):
        self.value = value


async def test_the_whole_payload_is_assembled_from_a_coordinator(monkeypatch):
    """Exercise the glue: registry rows in, one redacted payload out.

    Home Assistant itself is mocked here, so this pins the shapes and the
    redaction, not the registration of the diagnostics platform or the real
    registries - those have to be seen in a running Home Assistant.
    """
    from custom_components.wiser_for_knx import diagnostics

    coordinator = MagicMock()
    coordinator.data = {
        "functions": _DIMMER,
        "datapoints": dict(_DIMMER["f1"]["datapoints"]),
    }
    coordinator.entity_plan = {"light": [{"key": "f1"}]}
    coordinator.last_update_success = True
    coordinator.update_interval = timedelta(seconds=300)
    coordinator.server_errors = 0
    coordinator.structure_age = 42
    coordinator.health.data = {"device_id": "001122334455", "firmware": "3.1.0"}
    coordinator.push.status = "live"
    coordinator.push.diagnostics = {
        "callbacks_received": 7,
        "callback_path": "/api/webhook/abc123",
    }
    coordinator.backup_manager.configured = True
    coordinator.backup_manager.last_backup = None
    coordinator.backup_manager.last_error = None

    entry = MagicMock()
    entry.entry_id = "01JABCDEF"
    entry.version = 1
    entry.source = "user"
    entry.unique_id = "001122334455"
    entry.data = {"host": "192.168.1.x", "username": "admin", "password": "s3cr3t"}
    entry.options = {"push": True}

    hass = MagicMock()
    hass.data = {"wiser_for_knx": {entry.entry_id: coordinator}}
    hass.states.get.return_value = SimpleNamespace(state="on")

    monkeypatch.setattr(
        diagnostics.er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [
            _FakeRegistryEntity(
                "light.kitchen_ceiling", "wiser_for_knx_01JABCDEF_f1", "Kitchen ceiling"
            ),
            _FakeRegistryEntity(
                "sensor.push",
                "wiser_for_knx_01JABCDEF_push",
                "Push",
                category=_FakeEnum("diagnostic"),
            ),
        ],
    )
    monkeypatch.setattr(
        diagnostics.dr,
        "async_entries_for_config_entry",
        lambda registry, entry_id: [
            SimpleNamespace(
                id="ha_device_1",
                name="Kitchen ceiling",
                name_by_user=None,
                model="fct.dimming",
                area_id="kitchen",
                via_device_id="ha_controller",
            )
        ],
    )

    payload = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert payload["plan"] == {"counts": {"light": 1}, "total": 1}
    assert payload["registry"]["by_domain"] == {"light": 1, "sensor": 1}
    assert payload["entities"][1]["entity_category"] == "diagnostic"
    assert payload["entities"][0]["state"] == "on"
    assert payload["controller"]["poll"] == {
        "last_update_success": True,
        "update_interval_seconds": 300,
        "consecutive_server_errors": 0,
        "structure_age_seconds": 42,
    }
    assert payload["controller"]["push"]["callbacks_received"] == 7
    # Every identifying value, at every depth, in one payload
    assert payload["entry"]["data"]["password"] == REDACTED
    assert payload["entry"]["unique_id"] == REDACTED
    assert payload["controller"]["health"]["device_id"] == REDACTED
    assert payload["controller"]["push"]["callback_path"] == REDACTED
    assert payload["controller"]["backup"]["last_backup"] is None
