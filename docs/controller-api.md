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

## 2. Management API – `/api/management/v1`

Spec is the vendor file `device-api.yaml` (kept outside the repo). Used by the integration:

| Method | Path | Notes |
|---|---|---|
| POST | `/flashsys/system/backupConfiguration` | system configuration backup (~5 KB ZIP) |
| POST | `/scada-main/general/backup` | project/SCADA backup (~1.8 MB ZIP) |
| GET | `/custom/deviceInfo` | firmware, hardware, architecture (not used yet) |
| GET | `/flashsys/Status/SystemStatus` | status/uptime/memory (not used yet) |

Backup request: headers `Accept: application/json, application/octet-stream, */*`, `Content-Type: application/json`, body `{"data":{"password":"<backup password>"}}`. The response is a ZIP with encrypted entries (`application/x-gzip` or `application/octet-stream` content type, but the magic bytes are `PK`). Status 400 = password rule violated; 401/403 = auth. Allow a long timeout (the client uses 180 s).

**Password rule (enforced by the controller):** at least 8 characters, one upper-case letter, one lower-case letter, one digit. Implemented in `backup_utils.is_valid_backup_password`.

Not used on purpose: restore endpoints, admin password change, hostname/network changes, KNX/BACnet patches, log clearing. The BACnet settings include a `Password` field.

## Privacy rules for real data

- `wiser_dump_raw.json`, `wiser_backup_*.bin`, `wiser_mgmt_probe.json` and Touch backup JSON files (`touch_backup*.json`) are private. All of them are git-ignored; never copy any of them into the repo or into chat output.
- Share `wiser_dump_anon.json` (anonymised titles/ids) or aggregate counts instead.
