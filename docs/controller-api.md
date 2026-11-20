# Controller APIs and real-data findings

Applies to a Wiser for KNX controller (firmware 3.1.0, `i.MX6UL LM2i`), also spaceLYnk / LogicMachine based. All data below comes from real controllers; no credentials or installation data are stored in the repo.

## Transport

- HTTPS on port 443 with a self-signed certificate; HTTP Basic auth (default user `admin`).
- Both APIs share host, port and credentials.

## 1. KNX IoT 3rd Party API – `/api/w4knx/3rdparty/v1`

Spec: `schneider_knx_iot_3rdparty_v1_openapi.json` (repo root). JSON:API style.

| Method | Path | Use |
|---|---|---|
| GET | `/locations` | rooms/floors (`title`, hierarchy) |
| GET | `/functions` | devices; `meta["@type"]` holds KNX function URNs; `attributes` has `title`, `schneider:widgetId`, `schneider:widgetSettings`, location relationship |
| GET | `/datapoints` | datapoints; `attributes` has `title`, `unit`, `value`, `valueType`, `writable`, `enum`, `schneider:parentFunction`; `meta["@type"]` holds datapoint types |
| PUT | `/datapoints/values` | write: `{"data":[{"id":..,"type":"datapoint","attributes":{"value":"on"}}]}`; answers **202 Accepted** |

**Header requirement:** `Accept: application/vnd.api+json, application/json`. Plain `application/json` returns **HTTP 406**. The client (`api.py::_get_headers`) sends the right header.

### Findings from real dumps (`tools/dump_controller.py`)

- Touch widget ids (`se-*`) are **not** exposed: `schneider:widgetId` is a hash and `widgetSettings` is mostly null. Classification therefore uses function URNs.
- Function URNs seen: `switchingLight`, `dimming`, `switchingSocket`, `switching`, `power`, `airQuality`, `scene`, `alarm*`, `info`, `VDCThermostat`, `genericThermostat`, `temperatureAirFan`, `blindsVertical`, `weather`, `gauge`, `gasSensor`, `windowDoorSensor`, `movementDetector`, `iTRV`, `schneider.logicThermostat.type.thermostat`, `alarmAutomation`.
- Datapoint titles are user-defined group-object names; every `valueType` is `"string"` (values are strings such as `on`, `off`, `"0"`).
- Light/switch datapoint types: `dpa.417.70` + `dpt.switch` (switchingLight/Socket on/off), `dpa.418.61` + `dpt.switch` and `dpa.418.63` + `dpt.scaling` (dimmer on/off and brightness %, unit `%`), `dpa.901.51` + `dpt.power` (socket power, W, read-only).
- Binary-sensor datapoints (not imported any more but classified): `dpa.810.51`, `344.51`, `808.51`, `811.51` (`open`/`close`), `414.63` (`start`/`stop`). Numeric readings such as lux must not be treated as binary.
- A dump with 6 Touch widgets (2 light switches, 1 socket, 3 dimmers) produced 9 functions: 3 `switchingLight`, 3 `dimming`, 2 `switchingSocket`, 1 `alarmAutomation` (skipped) → 6 lights, 2 switches.

### Which widget channels are exposed (tested deliberately)

A test layout was configured with some channels incomplete, then compared with the dump:

| Widget channel configuration | Exposed as function? |
|---|---|
| Light switch: switch object **and** status feedback (same or different group address) | yes |
| Light switch: switch object only (mandatory field only, no status feedback) | **no** |
| Light switch / socket: status feedback only (no switch object) | **no** |
| Socket: switch + status (+ active power, device status) | yes; active power appears as a read-only `dpt.power` datapoint |
| Dimmer: value + status value + switch + status switch | yes (`dimming` with `dpt.scaling` and `dpt.switch`) |
| Dimmer: value + switch, no status feedback objects | **no** |

Conclusion: the controller publishes a channel through the 3rd-party API only when it has both a write object and its status feedback, even where the Touch widget documentation marks the status feedback as optional (light switch). This is a controller behaviour, not an integration filter. Each channel becomes its own function (a 3-channel light-switch widget gives 3 lights). "Device status" objects are not exposed as datapoints. The same group address may be used for the switch and its status feedback.

### Findings from the 2026-11 probing rounds

Measured across every control surface of one controller and written up in
[bartosekpetr/wiser-knx-skillset](https://github.com/bartosekpetr/wiser-knx-skillset)
(`skills/wiser-knx/homelynk-ha.md` is the Home Assistant chapter, `widget-matrix.md` the
per-widget evidence). Only what matters for this integration is repeated here.

**Reads can fail without the installation being empty.** This build intermittently answers
**500** on `/datapoints` and `/functions`, most often while it recomputes its API export
after a configuration change. `/datapoints` is the single request the whole entity graph is
built from, so one unretried 500 looks like an empty installation at startup and like "every
entity became unavailable" at runtime. The client retries 5xx (`COLLECTION_RETRIES`, growing
backoff) and the coordinator reports a failed poll as *no new information*: entities go
unavailable, nothing is removed.

One widget configuration wedges it **permanently**: an `se-danfoss-thermostat` (floor
heating) with its `object-device-status` slot populated makes `GET /datapoints` return 500
for as long as the widget exists; deleting the widget restores it immediately. It was
bisected one slot at a time, and the 37 other widget types that declare the same slot are
all harmless — it is the combination. After `SERVER_ERROR_HINT_AFTER` consecutive refusals
the integration logs this as the likely cause, because nothing in Home Assistant looks wrong.

**Collections are never paged.** Responses carry `meta.collection: {offset, items, total}`,
but this firmware ignores `?offset=` and `?limit=` and always returns everything with
`items == total`. A pager that trusts `offset` re-reads the first page forever.

**A write is accepted, not applied.** `PUT /datapoints/values` answers 202 for any
well-formed body and then silently discards a value that is not a member of the datapoint's
`enum` *verbatim*: on the same writable switch datapoint `on` produced a KNX telegram while
`1` and `true` produced nothing. The HTTP status cannot tell the two apart, so the
coordinator matches the value against the datapoint's own `enum` and logs a value that
matches no member.

**Control and status collapse into one datapoint.** The datapoint's value is the status
object; a write to it drives the control object. So optimistic *and* pessimistic state are
both wrong in general: where an actuator bridges control → status the value follows shortly,
and where nothing does (a lone KNX output) it never follows. The integration therefore
updates its local state optimistically and never does write-then-verify-else-error.

**Values are in engineering units.** A datapoint's `value` is converted from the raw group
object value per type and must be passed through unchanged: a `dpt.scaling` raw 128 is
published as `50` with `unit: "%"`, so re-deriving a percentage from 0–255 is wrong by a
factor of 2.55. One exception matters if climate ever returns: `fct.se8000` publishes every
`dpt.valueTemp` as `(raw − 32) × 5/9` while still labelling it `unit: "C"`, verified against
an `se-thermostat` on the same group address. There is no flag to detect it from; it has to
be special-cased on the function type. (`se-air-quality`'s `no2`/`ozone` published `0.0215`
for a raw 21.5 — a factor of 1000, measured but unexplained; treat `fct.gasSensor`
concentrations as unverified.)

**Export has a second, invisible gate.** Besides the write-object-plus-status rule above,
the widget setting "Disable API Export" (`disable_export`) suppresses export — but only when
stored as a real JSON boolean. Written as the integer `1` it is stored and ignored, so it
looks set in the Touch config while having no effect. A fully configured widget can therefore
be absent from the API for a reason invisible in the function/datapoint graph. There is no
room-level equivalent (`a=save_room_settings` answers 404 on this firmware). The firmware's
own `requiredForApp` tag is **not** the gate and has been measured wrong in both directions.

**A function is published before its datapoints.** Measured on `se-alarm-water`,
`se-light-dimmer-rotary` and `se-thermostat-vdc`: the function existed with zero datapoints
and they attached **15 s** later. The wait grows with configuration churn — the same types
publish in 1–6 s on a quiet controller but showed nothing after 240 s during a 47-widget
sweep. So a bulk import or a restore is exactly when "this function publishes nothing" must
not be concluded. Entities for a function with no datapoints yet report *unavailable* and
recover on a later poll. (`fct.content`, from the Content widget, legitimately has none.)

**One widget can become many devices**, in two ways, and the function type and count follow
the *slot combination*, not the widget type, so neither can be looked up from a static table:

| | measured |
|---|---|
| channel fan-out | a 6-gang `se-light-switch` with all 18 slots filled publishes **6** `fct.switchingLight` functions, titled `<widget> 1` … `<widget> 6`, one `dpt.switch` each, all sharing one `schneider:widgetId`; the same widget with only the mandatory pair publishes 1 |
| mixed export | `se-weather-station` with a wind threshold publishes `fct.weather` *and* `fct.alarmWind`; `se-thermostat` changes type with its slot set (`fct.temperatureAirFan` vs `fct.iTRV`) |
| largest fan-out | `se-logic-thermostat` at full slots: **25 functions, 48 datapoints** from one widget |

Entities are therefore grouped by `schneider:parentFunction`, never by widget id, and every
function matching a widget id is enumerated — stopping at the first match yields a
plausible-looking single entity while five channels silently go missing.

**Vendor function types exist.** `se-logic-thermostat` publishes
`urn:knx:fct.schneider.logicThermostat.type.thermostat` next to the standard `fct.iTRV` and
`fct.genericThermostat`. Matching must use the whole URN with a fallback for unknown types:
splitting on `.` and taking the last segment reads that one as `thermostat`, and taking the
segment after `fct.` reads it as `schneider`. `widgets.py` matches on substrings of the full
URN for this reason.

**Ids are stable, names are not ours to write.** `datapoint.id` and the function id survive
widget edits, group-address changes and renames byte-identically (the API `title` follows the
new name), which is what makes them usable as `unique_id`s. `PUT /functions|locations/attributes`
answers **405**, so the API `title` is an initial value only and renaming happens in Home
Assistant. `/locations` is a flat list — site, floors and rooms in one array, every `type`
`null` — and the floor → room hierarchy exists only in the Touch config, so the room name
from `schneider:parentLocationName` is used directly as the suggested area.

## 2. Management API – `/api/management/v1`

Spec is the vendor file `device-api.yaml` (kept outside the repo). Used by the integration:

| Method | Path | Notes |
|---|---|---|
| POST | `/flashsys/system/backupConfiguration` | system configuration backup (a few KB, ZIP) |
| POST | `/scada-main/general/backup` | project/SCADA backup (hundreds of KB to a few MB, ZIP) |
| GET | `/custom/deviceInfo` | firmware, hardware, architecture (used by the health sensors) |
| GET | `/flashsys/Status/SystemStatus` | uptime, load, memory, partitions (used by the health sensors) |

Backup request: headers `Accept: application/json, application/octet-stream, */*`, `Content-Type: application/json`, body `{"data":{"password":"<backup password>"}}`. The response is a ZIP with encrypted entries (`application/x-gzip` or `application/octet-stream` content type, but the magic bytes are `PK`). Status 400 = password rule violated; 401/403 = auth. Allow a long timeout (the client uses 180 s).

**Password rule (enforced by the controller):** at least 8 characters, one upper-case letter, one lower-case letter, one digit. Implemented in `backup_utils.is_valid_backup_password`.

**Validate the body, not the status code** (skillset round of 2026-11-20). There is no `success` key and no JSON envelope: the body *is* the archive, so HTTP 200 alone is no evidence that what arrived is a backup. `backup_utils.zip_entry_count` parses it before it is stored and the manager refuses to write anything that is not a readable ZIP. The entry count is the invariant to report: on the reference controller the project archive held the same number of entries at every measurement while its **size drifted upwards** (423–431 KB earlier, 452133 B on 2026-11-20) because the trend data inside it keeps growing. **Never check a backup against a size band** — doing so rejects a good archive exactly when a restore matters. Entries of a password-protected archive are listed without the password; only their contents are encrypted.

Two related hardening findings from the same round, and where this integration stands on them:

- *A `Content-Disposition` filename joined onto a local directory is a path-traversal sink.* Not applicable here by construction: file names are generated from host, kind and timestamp (`backup_utils.backup_filename`) and the host is passed through `safe_host`, so the controller's response headers never choose a path.
- *A project backup is a copy of the whole installation and should not be created at the process umask.* Stored files are `chmod 0600` in `backup.py` before the atomic rename.

Not used on purpose: restore endpoints, admin password change, hostname/network changes, KNX/BACnet patches, log clearing. The BACnet settings include a `Password` field.

## Privacy rules for real data

- `wiser_dump_raw.json`, `wiser_backup_*.bin`, `wiser_mgmt_probe.json` and Touch backup JSON files (`touch_backup*.json`) are private. All of them are git-ignored; never copy any of them into the repo or into chat output.
- Share `wiser_dump_anon.json` (anonymised titles/ids) or aggregate counts instead.
