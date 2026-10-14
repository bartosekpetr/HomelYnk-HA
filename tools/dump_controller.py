"""Dump a Wiser for KNX controller's API and report how the integration classifies it.

Usage (from the repository root):
    py -3 tools/dump_controller.py 192.168.0.104

Credentials are prompted for and never stored. Two files are written:
    wiser_dump_raw.json   - full raw API output (PRIVATE, git-ignored, do not share)
    wiser_dump_anon.json  - titles and ids replaced (safe to share)
"""

from __future__ import annotations

import base64
import getpass
import json
import re
import ssl
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The package __init__ imports Home Assistant; stub it so this runs standalone.
for _mod in (
    "homeassistant", "homeassistant.const", "homeassistant.core",
    "homeassistant.config_entries", "homeassistant.exceptions",
    "homeassistant.helpers", "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator", "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform", "homeassistant.components",
    "homeassistant.components.binary_sensor", "aiohttp", "voluptuous",
    "homeassistant.helpers.event", "homeassistant.helpers.device_registry",
    "homeassistant.util", "homeassistant.util.dt",
):
    sys.modules.setdefault(_mod, MagicMock())

API_BASE = "/api/w4knx/3rdparty/v1"
ENDPOINTS = ("locations", "functions", "datapoints")


def fetch(host: str, auth: str, name: str):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # The controller is on the LAN; bypass any corporate proxy.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
    )
    req = urllib.request.Request(
        f"https://{host}{API_BASE}/{name}",
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/vnd.api+json, application/json",
            "Content-Type": "application/vnd.api+json",
        },
    )
    with opener.open(req, timeout=30) as resp:
        return json.load(resp)


def anonymise(raw: dict) -> dict:
    """Replace free text and identifiers, keep structure, types and settings."""
    counters: Counter = Counter()
    ids: dict[str, str] = {}

    def alias(value, prefix):
        key = f"{prefix}:{value}"
        if key not in ids:
            counters[prefix] += 1
            ids[key] = f"{prefix}-{counters[prefix]}"
        return ids[key]

    text_keys = {"title", "schneider:titleBase", "schneider:alarmText",
                 "schneider:parentFunctionName", "schneider:parentLocationName"}
    id_keys = {"schneider:parentFunction": "id", "schneider:parentLocation": "id"}
    uuid_re = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F-]{20,}")

    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in text_keys and isinstance(v, str):
                    out[k] = alias(v, "text")
                elif (k in id_keys or k == "id") and isinstance(v, (str, int)):
                    out[k] = alias(v, "id")
                elif k == "value" and isinstance(v, str):
                    out[k] = "<redacted>"
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            return uuid_re.sub(lambda m: alias(m.group(0), "uuid"), node)
        return node

    return walk(raw)


def parse(raw: dict):
    """Run the integration's own classification, without Home Assistant."""
    from custom_components.wiser_for_knx.widgets import (
        binary_device_class,
        classify_function,
        detect_widget_type,
        is_binary_datapoint,
    )

    dps: dict[str, dict] = {}
    for item in raw["datapoints"].get("data", []):
        a, m = item.get("attributes", {}), item.get("meta", {})
        dps[str(item.get("id"))] = {
            "title": a.get("title", ""), "unit": a.get("unit", ""),
            "value_type": a.get("valueType"), "value": a.get("value"),
            "writable": a.get("writable", False), "enum": a.get("enum", []),
            "parent_function_id": a.get("schneider:parentFunction"),
            "types": m.get("@type", []),
        }

    summary = []
    for item in raw["functions"].get("data", []):
        a = item.get("attributes", {})
        fid = str(item.get("id"))
        func = {
            "id": fid, "title": a.get("title", ""),
            "types": item.get("meta", {}).get("@type", []),
            "widget_id": a.get("schneider:widgetId"),
            "widget_settings": a.get("schneider:widgetSettings"),
            "datapoints": {k: d for k, d in dps.items()
                           if str(d["parent_function_id"]) == fid},
        }
        summary.append({
            "widget_id": func["widget_id"],
            "widget_type": detect_widget_type(func),
            "category": classify_function(func),
            "binary_class": binary_device_class(func),
            "has_urns": bool(func["types"]),
        })
    return summary


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    host = sys.argv[1]
    user = input("Username: ")
    pwd = getpass.getpass("Password: ")
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()

    raw = {}
    for name in ENDPOINTS:
        print(f"Fetching {name} ...")
        raw[name] = fetch(host, auth, name)

    (ROOT / "wiser_dump_raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    (ROOT / "wiser_dump_anon.json").write_text(
        json.dumps(anonymise(raw), indent=2), encoding="utf-8")

    summary = parse(raw)
    print("\nClassification result (no names shown):")
    for (cat, wtype, cls), n in Counter(
        (s["category"], s["widget_type"], s["binary_class"]) for s in summary
    ).most_common():
        print(f"  {n:3d} x category={cat:<14} widget={wtype}  binary_class={cls}")
    missing = sum(1 for s in summary if not s["widget_type"])
    print(f"\nFunctions without a detected widget type: {missing}/{len(summary)}")
    print("Distinct schneider:widgetId values:",
          sorted({str(s["widget_id"]) for s in summary}))
    print("\nWrote wiser_dump_raw.json (PRIVATE) and wiser_dump_anon.json (shareable).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
