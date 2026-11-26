"""Shaping and redaction of the diagnostics payload.

The payload exists to answer one question that no test can answer and no log
line reports: **what did this installation actually become in Home Assistant?**
The suite mocks Home Assistant, so the platform wiring, the dynamic add path and
the registries are covered by nothing; a screenshot of the device page shows
names and states but not the archetype, the role or the viability decision that
produced them. So this file puts the decision and its result side by side - the
function, its category, whether its composite was viable, every datapoint with
its `dic:dpa.*` archetype and role, and the registry row and state each one
ended up as.

`review` is the part to read first: it pre-computes the handful of things that
make an entity "look wrong" (a composite that was not viable, a datapoint with
no role, a datapoint with no title, an unavailable or unknown state, an entity
id with a `_2` suffix) so a reader does not have to cross-reference the rest.

Pure module: no Home Assistant imports, so it stays unit-testable.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .datapoints import DIAGNOSTIC_ROLES, datapoint_role
from .plan import (
    COMPOSITE_PLATFORMS,
    COMPOSITE_ROLES,
    composite_is_viable,
    datapoint_platform,
)
from .widgets import CAT_SKIP, classify_function

REDACTED = "**REDACTED**"

# Keys whose value never goes into a file a user attaches to a bug report.
#
# `host`/`api_base`-adjacent values are the owner's LAN address; `device_id` is
# the MAC or serial the stable unique id is derived from, which the management
# API hands out on a plain read and which this project keeps out of entities and
# attributes already; `callback_path` carries the webhook id push frames are
# posted to. The signing secret is not reachable from here at all - the push
# manager does not expose it - and must stay that way.
REDACT_KEYS = frozenset(
    {
        "password",
        "backup_password",
        "username",
        "host",
        "certificate_fingerprint",
        "unique_id",
        "device_id",
        "callback_path",
        "secret",
    }
)

# An entity id Home Assistant had to disambiguate: two entities asked for the
# same slug. `_2` on this installation would contradict the premise that the old
# config entry was removed before the current one was added.
_SUFFIXED = re.compile(r"_(\d)$")


def redact(value: Any) -> Any:
    """Return `value` with every REDACT_KEYS entry replaced, at any depth."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if key in REDACT_KEYS and item is not None:
                redacted[key] = REDACTED
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _dpa_type(types: Any) -> str | None:
    """Return the `dic:dpa.*` tag, the one thing that identifies the Touch slot."""
    for tag in types or []:
        if isinstance(tag, str) and tag.startswith("dic:dpa."):
            return tag
    return None


def _dpt_type(types: Any) -> str | None:
    """Return the `urn:knx:dpt.*` tag, which is only ever a fallback."""
    for tag in types or []:
        if isinstance(tag, str) and "dpt." in tag:
            return tag
    return None


def datapoint_row(dp: dict[str, Any], consumed: bool) -> dict[str, Any]:
    """Return one datapoint, with the decisions taken about it next to its data."""
    role = datapoint_role(dp)
    title = dp.get("title") or ""
    return {
        "id": dp.get("id"),
        "title": title,
        # The entity name of a leftover datapoint is its title, which is an
        # installer-chosen KNX group object name. No title means the entity falls
        # back to the role or the raw id, which is what a "wrong name" looks like.
        "named_by": "title" if title else ("role" if role else "datapoint_id"),
        "dpa": _dpa_type(dp.get("types")),
        "dpt": _dpt_type(dp.get("types")),
        "role": role,
        "writable": bool(dp.get("writable")),
        "unit": dp.get("unit") or None,
        "enum": list(dp.get("enum") or []),
        "value": dp.get("value"),
        "consumed_by_composite": consumed,
        "platform": None if consumed else datapoint_platform(dp, role),
    }


def function_rows(functions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one row per exported function, in id order, with its datapoints."""
    rows = []
    for func_id, func in sorted((functions or {}).items()):
        category = classify_function(func)
        composite = COMPOSITE_PLATFORMS.get(category)
        viable = bool(composite) and composite_is_viable(category, func)
        wanted = COMPOSITE_ROLES.get(category, frozenset()) if viable else frozenset()

        datapoints = []
        for _dp_id, dp in sorted((func.get("datapoints") or {}).items()):
            role = datapoint_role(dp)
            consumed = bool(role) and role in wanted and role not in DIAGNOSTIC_ROLES
            datapoints.append(datapoint_row(dp, consumed))

        rows.append(
            {
                "id": func_id,
                "title": func.get("title"),
                "types": list(func.get("types") or []),
                "location_id": func.get("location_id"),
                "category": category,
                # The composite this function could become, and whether its
                # datapoints could actually drive it. A category with a composite
                # that was not viable is the most likely reading of "a light I
                # expected is a pile of sensors".
                "composite_platform": composite,
                "composite_viable": viable,
                "skipped": category == CAT_SKIP,
                "datapoint_count": len(datapoints),
                "datapoints": datapoints,
            }
        )
    return rows


def plan_summary(plan: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return how many entities the current plan asks for, per platform."""
    counts = {platform: len(specs) for platform, specs in sorted((plan or {}).items())}
    return {"counts": counts, "total": sum(counts.values())}


def _entity_row(entity: dict[str, Any]) -> dict[str, Any]:
    """Return one registry entity, trimmed to what a diagnosis needs."""
    return {
        "entity_id": entity.get("entity_id"),
        "name": entity.get("name") or entity.get("original_name"),
        "has_custom_name": bool(entity.get("name")),
        "unique_id_suffix": _unique_id_suffix(entity.get("unique_id")),
        # Home Assistant's own device registry id, not the controller's identity:
        # keyed `device` so the `device_id` redaction (the MAC or serial the
        # stable unique id comes from) cannot swallow the entity-to-device link.
        "device": entity.get("device_id"),
        "entity_category": entity.get("entity_category"),
        "disabled_by": entity.get("disabled_by"),
        "hidden_by": entity.get("hidden_by"),
        "state": entity.get("state"),
    }


def _unique_id_suffix(unique_id: Any) -> str | None:
    """Return the function or datapoint id a unique id ends with.

    The entry id in the middle is noise for a reader and changes on a re-add, and
    the tail is what ties the entity back to the export.
    """
    if not isinstance(unique_id, str):
        return None
    return unique_id.rsplit("_", 1)[-1]


def entity_review(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the entities worth looking at first, by the symptoms reported."""
    unavailable, unknown, unnamed, suffixed, disabled = [], [], [], [], []
    for entity in entities:
        entity_id = entity.get("entity_id")
        state = entity.get("state")
        name = entity.get("name") or entity.get("original_name")
        if state == "unavailable":
            unavailable.append(entity_id)
        elif state in (None, "unknown"):
            unknown.append(entity_id)
        if not name:
            unnamed.append(entity_id)
        if entity.get("disabled_by"):
            disabled.append(entity_id)
        # A `_2` suffix on an entity id means Home Assistant disambiguated two
        # entities that wanted the same slug. It is expected to be absent here
        # (one config entry, the previous one removed before the re-add), so if
        # it is present that premise is wrong and matters more than the names.
        match = _SUFFIXED.search(entity_id or "")
        if match and not (name or "").rstrip().endswith(match.group(1)):
            suffixed.append(entity_id)
    return {
        "unavailable": unavailable,
        "unknown_or_no_state": unknown,
        "unnamed": unnamed,
        "numeric_suffix": suffixed,
        "disabled": disabled,
    }


def _plan_review(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the decisions that most often produce an entity that looks wrong."""
    degraded, roleless, untitled = [], [], []
    for row in rows:
        if row["composite_platform"] and not row["composite_viable"]:
            # The function fell through to loose datapoint entities instead of
            # becoming the light/cover/climate its category promised.
            degraded.append(
                {
                    "function_id": row["id"],
                    "title": row["title"],
                    "category": row["category"],
                    "roles": sorted(
                        {dp["role"] for dp in row["datapoints"] if dp["role"]}
                    ),
                    "writable_roles": sorted(
                        {
                            dp["role"]
                            for dp in row["datapoints"]
                            if dp["role"] and dp["writable"]
                        }
                    ),
                }
            )
        for dp in row["datapoints"]:
            if dp["role"] is None:
                # No measured archetype: the datapoint still gets an entity, but
                # a plain one named after its group object. A new DPA_ROLES row
                # has to come from a measurement, so these are the candidates.
                roleless.append(
                    {"datapoint_id": dp["id"], "dpa": dp["dpa"], "dpt": dp["dpt"]}
                )
            if dp["named_by"] != "title":
                untitled.append({"datapoint_id": dp["id"], "named_by": dp["named_by"]})
    return {
        "composite_not_viable": degraded,
        "datapoints_without_role": roleless,
        "datapoints_without_title": untitled,
    }


def build_diagnostics(
    *,
    entry: dict[str, Any],
    controller: dict[str, Any],
    functions: dict[str, dict[str, Any]],
    datapoints: dict[str, dict[str, Any]],
    plan: dict[str, list[dict[str, Any]]],
    entities: list[dict[str, Any]],
    devices: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the whole diagnostics payload, redacted.

    Everything in here is derived from data the integration already holds; the
    only new reads are the two registries, which is what turns "the plan asked
    for 41 entities" into "these 41 entities exist and this is what they show".
    """
    rows = function_rows(functions)
    entity_rows = [_entity_row(entity) for entity in entities]
    by_domain = Counter(
        (row["entity_id"] or "").split(".", 1)[0] for row in entity_rows
    )
    return redact(
        {
            "entry": entry,
            "controller": controller,
            "export": {
                "functions": len(functions or {}),
                "datapoints": len(datapoints or {}),
                "writable_datapoints": sum(
                    1 for dp in (datapoints or {}).values() if dp.get("writable")
                ),
                # A datapoint naming a function the cached structure does not know
                # means the export moved under us since the last structure refresh.
                "orphan_datapoints": sum(
                    1
                    for dp in (datapoints or {}).values()
                    if dp.get("parent_function_id")
                    and dp["parent_function_id"] not in (functions or {})
                ),
            },
            "plan": plan_summary(plan),
            "registry": {
                "entities": len(entity_rows),
                "by_domain": dict(sorted(by_domain.items())),
                "devices": devices,
            },
            "review": {**_plan_review(rows), **entity_review(entities)},
            "functions": rows,
            "entities": entity_rows,
        }
    )
