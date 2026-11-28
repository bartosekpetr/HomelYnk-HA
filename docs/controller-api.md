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

**Header requirement:** this surface serves `application/vnd.api+json`, and `Accept` must match it **verbatim or by wildcard**. The client (`api.py::_get_headers`) sends `application/vnd.api+json, application/json`. The full matrix was measured on 2026-11-22, after a probe that politely asked for `application/json` got 406 everywhere and nearly hid an unrelated 404 underneath it:

| `Accept` | result |
|---|---|
| `*/*` | 200 |
| `application/vnd.api+json` | 200 |
| `application/*` | 200 |
| `application/json, */*` | 200 |
| `application/json;q=1.0, */*;q=0.8` | 200 |
| `application/json` | **406** |
| `text/*` | **406** |
| *absent* | **406** |

So the rule is not "json is wrong" but "match the served type or wildcard it — and never omit the header". The two `/.well-known/knx` probes in `api.py` send `application/json, */*`, which is in the 200 column only because of the `*/*`: removing it would turn every answer on this surface into a 406, and a 406 is easy to misread as "wrong endpoint". `async_check_tls` deliberately sends no `Accept` at all and ignores the status code — it only needs the TLS handshake — so a 406 there is harmless by design.

### Findings from real dumps (`tools/dump_controller.py`)

- Touch widget ids (`se-*`) are **not** exposed: `schneider:widgetId` is a hash and `widgetSettings` is mostly null. Classification therefore uses function URNs.
- Function URNs seen: `switchingLight`, `dimming`, `dimmingDali`, `colorRGB`, `colorRGBW`, `switchingSocket`, `switching`, `switchingAC`, `switchingFan`, `power`, `airQuality`, `gasSensor`, `particleSensor`, `scene`, `alarm*` (`alarm`, `alarmFire`, `alarmGas`, `alarmWater`, `alarmWind`, `alarmTemp`, `alarmLight`, `alarmDewPoint`, `alarmAutomation`), `info`, `content`, `VDCThermostat`, `genericThermostat`, `temperatureAirFan`, `temperatureAir`, `temperatureFloor`, `se8000`, `airzone`, `iTRV`, `blindsVertical`, `blindsHorizontal`, `shadingRotary`, `blinds`, `smartLock`, `weather`, `gauge`, `windowDoorSensor`, `schneider.windoor.type.door`, `movementDetector`, `schneider.logicThermostat.type.thermostat`, `schneider.generic`. The function type → datapoint type mapping for every one of them is the summary table in the skillset's `widget-matrix.md`.
- Datapoint titles are user-defined group-object names; every `valueType` is `"string"` (values are strings such as `on`, `off`, `"0"`).
- Light/switch datapoint types: `dpa.417.70` + `dpt.switch` (switchingLight/Socket on/off), `dpa.418.61` + `dpt.switch` and `dpa.418.63` + `dpt.scaling` (dimmer on/off and brightness %, unit `%`), `dpa.901.51` + `dpt.power` (socket power, W, read-only).
- **Colour: RGB and white are the whole of it, and that is a catalogue fact rather than a sample.** The skillset's widget rig enumerates the controller's own widget catalogue and builds *every* type in it with all optional slots populated, recording each type's full slot definition; over all **47 types and 269 distinct slots** the only colour slots are `se-rgb-dimmer`'s `rgb`/`rgb-status` (DPT 232.600, the hex triplet) and `se-rgbw-dimmer`'s red/green/blue/white (DPT 5.001). **There is no colour-temperature or tunable-white slot anywhere**, so no `dic:dpa.*` archetype for one exists and none may be invented (AGENTS.md §3). Corroborating it: the nine lighting-system widgets publish only DPT 1.001, 5.001, 9.001 and 232.600; the catalogue's slot datatypes are the majors 1, 5, 7, 9, 12, 14, 16, 20 and 232, with no 7.600 and no 242/249/250.600; and DPT **250.600**, which the controller's own datatype catalogue labels "3 byte DALI brightness and color temperature control", is used by **no slot of any widget** — the two DALI group widgets expose only a 1.001 switch and a 5.001 value. Nor is there a back door: the single 2-byte-unsigned slot in the catalogue is `se-air-quality`'s read-only `tvoc-index`, and `se-gauge`'s generic slot (`dpa.417.65`/`dpt.generic`), the one slot carrying an arbitrary DPT, is `writable: false`. A multi-channel dimmer's spare channel *is* a writable 0–100 % path to a CCT actuator that accepts DPT 5.001, but each channel exports as its own separate `fct.dimming` function carrying the **same** `dpa.418.61`/`.63` archetypes as plain brightness, so nothing in the data distinguishes it from a dimmer. Colour temperature therefore belongs to HA's native KNX integration over KNX/IP, not here (SMA-246, 2026-11-27).
- **A gauge is the one tile whose datapoint says nothing and whose *function* says everything.** `se-gauge` always publishes one read-only `dic:dpa.417.65` + `urn:knx:dpt.generic` datapoint with no unit, whatever DPT is wired to its `gauge-object` slot — so the archetype cannot name the quantity, and `valueType` stays `string` however the tile is configured. What varies is the function's **second** `@type`, composed from the widget's `gauge-device` setting as `urn:knx:fct.schneider.<value>`. Measured with scratch gauges on one object and confirmed on 15 live tiles:

  | widget `settings` | function `@type` | datapoint `minimum`/`maximum` |
  |---|---|---|
  | `{}` | `urn:knx:fct.schneider.generic` | 0 / 100 |
  | `min -20, max 50, decimals 1` | `urn:knx:fct.schneider.generic` | -20 / 50 |
  | `+ gauge-device weather.humiditySensor` | `urn:knx:fct.schneider.weather.humiditySensor` | 0 / 100 |
  | `+ gauge-device power.powerSensor` | `urn:knx:fct.schneider.power.powerSensor` | 0 / 3000 |
  | `+ gauge-device weather.CO2Sensor` | `urn:knx:fct.schneider.weather.CO2Sensor` | 0 / 2000 |
  | `+ gauge-device device.*`, no name | `urn:knx:fct.schneider.device.generic` | -20 / 50 |
  | `+ gauge-device device.*` + name | `urn:knx:fct.schneider.device.<name>` | -20 / 50 |

  So `min`/`max` are published verbatim as the datapoint's `minimum`/`maximum`, `decimals` as `schneider:resolution`, and the device type as that URN — **composed from an unvalidated string**, which is why `datapoints.FCT_GAUGE_ROLES` matches whole URNs exactly and never types a `device.<name>`. 🪤 **The `gauge-device` enum has no temperature value** (it offers power/energy/voltage/current/frequency, humidity, CO, CO2, ozone, battery, brightness, dimmer level, shutter position, wind speed and `device.*`), so a temperature gauge publishes exactly what an unconfigured one does and is not typeable here at all. 🪤 And a named quantity is not the same as a known unit: `power.powerSensor` is DPT 9.024 kW or 14.056 W, `voltageSensor` V or mV, `WindSpeedSensor` m/s or km/h, and no published field distinguishes them — those get a number and no unit rather than a unit that is wrong by a factor of 1000.
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

### The `dic:dpa.*` archetype identifies the widget slot

A datapoint's `meta["@type"]` carries **two** tags: a `dic:dpa.<archetype>` and a
`urn:knx:dpt.<type>`. The datapoint *type* is ambiguous — `dpt.scaling` is a dimmer's
brightness, a shutter's position, a battery level, a fan speed and a valve drive's
heating demand — but the **archetype says which Touch slot the datapoint came from**,
which the API exposes nowhere else. Measured across all 47 widget types in
`widget-api-matrix.json`; `datapoints.py::DPA_ROLES` is the table, with the slot in a
comment on every row. The load-bearing examples:

| archetype | slot | note |
|---|---|---|
| `dpa.800.65` / `dpa.800.66` | shutter height / slat position | the only way to tell the two `dpt.scaling` apart |
| `dpa.417.70` vs `dpa.417.72` | generic switch status vs **thermostat** on/off | a thermostat publishes both, and `417.70` is its *fan manual mode* |
| `dpa.399.56` / `dpa.392.5x` | current temperature / setpoints | both are `dpt.valueTemp` |
| `dpa.65533.51` / `dpa.65533.52` | battery level / low-battery alert | percentage vs flag |
| `dpa.65534.51`…`.61` | CO2, particles, formaldehyde, CO, NO2, ozone, TVOC | all `dpt.airQuality`/`airQualityDensity` |
| `dpa.901.51` | socket active power | read-only, W |
| `dpa.812.51` | device status | `online`/`offline`, diagnostic |

So classification needs no title heuristics at all: titles are user-defined KNX group
object names (in the installer's own language, and mojibake-prone over other surfaces),
i.e. display text. The integration keeps title matching only as a last-resort fallback
for a function whose URN is unknown.

### Findings from the 2026-11 probing rounds

Measured across every control surface of one controller and written up in
`bartosekpetr/wiser-knx-skillset` — a **private** repository (confirmed 2026-11-22), so the name
is a pointer for the maintainer and not a link a reader can follow (`skills/wiser-knx/homelynk-ha.md`
is the Home Assistant chapter, `widget-matrix.md` the per-widget evidence, `push.md` the push
protocol). Everything this integration relies on is restated here in full, so nothing below depends
on reading it.

That repository is also **not publishable, and not just private by setting**: its own audit of
2026-11-23 found live controller credentials committed inside probe-result JSON — the admin
password hash and the BACnet server password in plaintext, both still equal to the values on the
box. So nothing may be copied out of it into this public repository verbatim; a measurement quoted
here has to be re-described, which is what the sections below do. The lesson generalises to this
tree and is why the privacy rules at the end of this file are not the whole defence: the skillset
blocked credential *file types* in `.gitignore` and every one of those secrets arrived as a
**value inside a file type the tree exists to commit**. A filename list cannot see into a file it
is meant to allow.

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

**An enum member is encoded by its name, not by its position in the list** (measured
2026-11-21 on the reference controller, API write watched on the KNX bus). `dpt.heatCool`
is published with `enum: ["heat", "cool"]`; writing `heat` put raw `01` on the group object
and `cool` put raw `00`, which is DPT 1.100 (0 = cool, 1 = heat) — i.e. the *reverse* of the
published order, and the read side decodes the same mapping back. So the order of `enum` is
presentation only and carries **no** information about the raw value behind a member. A second
function confirmed it on 2026-11-22: on a live `fct.blindsVertical`, `dpt.step` published
`["increase", "decrease"]` encodes `increase` → raw `01` and `decrease` → raw `00`, and
`dpt.upDown` published `["down", "up"]` encodes `up` → raw `00` and `down` → raw `01`. Both are
their DPT's bit, neither is the list index.

**The shutter stop member is `decrease`** — settled by that write, plus a second witness that
needs no bus at all: all three of the vendor's own Touch shutter widgets
(`se-shutter-vertical`, `se-shutter-horizontal`, `se-shutter-rotary`) call
`this.model.write("stop-object", 0)` from their stop button, so raw 0 is what a stop *is* on
this controller, and `decrease` is how the API spells raw 0. Note which way round that is: the
earlier inference from a single inbound reading had named `increase`, which is the member that
*moves* a shutter. Reading a vendor front-end is cheap, and it was available the whole time.

**What a one-bit enum member puts on the bus**, measured (the HA integration keeps this table in
`datapoints.py::ENUM_BIT_BY_TOKEN`):

| type | published enum | raw 0 | raw 1 | when |
|---|---|---|---|---|
| `dpt.step` | `increase,decrease` | `decrease` | `increase` | 2026-11-22 |
| `dpt.upDown` | `down,up` | `up` | `down` | 2026-11-22 |
| `dpt.startStop` | `start,stop` | `stop` | `start` | 2026-11-22 |
| `dpt.deviceStatus` | `offline,online` | `online` | `offline` | 2026-11-22 |
| `dpt.heatCool` | `heat,cool` | `cool` | `heat` | 2026-11-21 |

The device-status row is the one worth a second look: an object reads **`online` while its bit
is clear**, which is the opposite of the reading a KNX error object invites.

**Control and status collapse into one datapoint.** The datapoint's value is the status
object; a write to it drives the control object. So optimistic *and* pessimistic state are
both wrong in general: where an actuator bridges control → status the value follows shortly,
and where nothing does (a lone KNX output) it never follows. The integration therefore
updates its local state optimistically and never does write-then-verify-else-error. Watched
directly on 2026-11-22: a full-slot `se-shutter-vertical` with ten group objects exports **seven**
datapoints, the height and slat control slots having collapsed into their status datapoints, and
writing the height datapoint drove the `height-position` object while its value kept coming from
`height-position-status`.

**`height-invert` exports nothing and changes nothing the API publishes.** The tenth slot of that
widget produced no datapoint at all; driving its group object from the bus left the published
height identical (30 stayed 30, not 70); and nothing in the Touch front-end bundles reads it. So
the API always publishes the raw KNX height, and a client that converts to Home Assistant's
"how far open" convention is not undermined by an installation that wires that slot. Which way a
real actuator travels is still untested — the convention itself is all that is settled here.

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

**The export is a cache, and the process that maintains it can be absent while the API still
answers** (measured 2026-11-21 on the reference controller). The function/datapoint graph is
not computed per request: the `apit3` app's daemon regenerates it when the Touch
configuration's CRC changes, and the HTTP handlers serve the cached result with live values
read separately. **`apit3` is two components, and only one of them is a process** (measured
2026-11-22): the REST surface — `/functions`, `/datapoints`, `/subscribe`, `/subscriptions` —
is nginx-embedded Lua (`content_by_lua_file`) with **no process of its own**, so it answers
whenever nginx is up, while the daemon is a real process (`lua /lib/apps/daemon.lua apit3 …`,
pidfile `/var/run/apps-daemon-apit3.pid`). That is the structural reason the freeze below is
invisible from the API: the half that answers requests does not need the half that maintains
the export, so there is nothing for a 5xx or an empty collection to report. On that controller
the daemon was **not running** — `touch3`, `cloud-connector` and `management` were, `apit3`
was not — and the effect was precisely split:

| | behaviour with the daemon down |
|---|---|
| `GET /functions`, `GET /datapoints` | 200, complete, no error anywhere |
| datapoint **values** | still live: a bus write showed up within 5 s |
| a **new or re-slotted widget** | never appears, at any wait |

So "the API answers and my entities still work" does **not** mean the export is current, and a
widget that is correctly configured can be missing for a reason that is invisible from the
API: no 5xx, no empty collection, nothing for the integration to detect. Nothing restarts an
app daemon that dies either — the vendor's launcher writes a pid and refuses to double-start,
the minutely `apps` cron only runs the store's `cron` scripts, and `/usr/share/procmon` (the one
thing on the box that does restart a dead process, minutely) does not watch app daemons. That last
point was re-measured on 2026-11-22 by the stronger method: the `apit3` daemon was killed outright
and **nothing restarted it within 120 s**. (The two rounds disagree about *why* — an entry list
covering the SCADA core, nginx, redis and OpenVPN in the first reading, an empty config directory
in the second — and only the conclusion is load-bearing here. Separately worth knowing: procmon
does `reboot` the unit if the 1-minute load average reaches 18, which is the one thing the
`Load (1 min)` health sensor can warn about.) `apit3` was also at the store's latest build
(`20260909`), so no app update fixes this. The freeze lasts until someone starts the daemon.

Restarting it is the fix and was confirmed on 2026-11-22: `daemon.start("apit3")` through the
vendor's own `apps.daemon` launcher, and both widgets that had been waiting appeared in the very
next poll (`/functions` 3 → 5, `/datapoints` 7 → 15), with the export tracking a teardown back
down again afterwards. **A reboot is not a reliable fix**: on that unit `/var/run` held pidfiles
for `touch3`, `cloud-connector` and `cc-watchdog` dated to the last boot and none for `apit3` at
all, i.e. the daemon had not run since that boot, and every widget-export measurement in the
skillset predates it. The freeze began at a boot rather than being cured by one.

🪤 **A later round pulls the other way, and the advice survives both.** The authorised reboot of
2026-11-25 (§3b item 6) recorded `apit3` running again **34.5 s** after the trigger, under a new
pid — so that boot did start the daemon. The two readings are unreconciled and neither is wrong:
the 2026-11-25 run rebooted a box whose daemon was *alive* beforehand, while the frozen-export case
is a box whose daemon is *dead*, and nobody has rebooted one of those. So "reboot and see" is still
not a fix anyone can promise, and the instruction to users is unchanged: reboot if you like, then
add a widget and check that it appears. If an installation reports that a widget added in
Touch never shows up in Home Assistant while everything else keeps working, this is the first
thing to check, and it is checkable only on the controller (`ps | grep apit3`). The
integration's "Rescan devices" button cannot help: it re-reads the same cache.

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
| GET | `/custom/deviceInfo` | firmware, hardware, architecture, uptime (used by the health sensors) |
| GET | `/flashsys/Status/SystemStatus` | uptime, load, memory, partitions (used by the health sensors) |

Backup request: headers `Accept: application/json, application/octet-stream, */*`, `Content-Type: application/json`, body `{"data":{"password":"<backup password>"}}`. The response is a ZIP with encrypted entries (`application/x-gzip` or `application/octet-stream` content type, but the magic bytes are `PK`). Status 400 = password rule violated; 401/403 = auth. Allow a long timeout (the client uses 180 s).

**`deviceInfo` carries no MAC and no serial** on firmware 3.1.0 (measured 2026-11-21: the
payload is exactly `architecture`, `fwVersion`, `hwVersion`, `lastUpdate`, `uptime`). So
`identity.stable_id_from_device_info` returns `None` there and the runtime upgrade of an
entry's `unique_id` to a hardware id never fires — a manually added entry keeps the id it was
created with, and only the DHCP discovery path ever learns a MAC. Both are handled; the thing
to avoid is assuming a hardware id will arrive. `/.well-known/knx` has no identity fields
either, and the `id` in `/node` ended in `456789101112` on the reference unit, which reads as
a vendor placeholder rather than a per-device value — do not adopt it from one controller.

Both parsers were re-run against the live controller on 2026-11-21: `health.parse_health`
produced firmware `3.1.0`, hardware `>=3.2`, the architecture string, uptime 823238 s, the
three load averages, 16.8 % memory and 6.6 % storage, with `device_id: None` as above. Uptime
cross-checked against the controller's own `uptime` command.

**Password rule (enforced by the controller):** at least 8 characters, one upper-case letter, one lower-case letter, one digit. Implemented in `backup_utils.is_valid_backup_password`.

**Validate the body, not the status code** (skillset round of 2026-11-20). There is no `success` key and no JSON envelope: the body *is* the archive, so HTTP 200 alone is no evidence that what arrived is a backup. `backup_utils.zip_entry_count` parses it before it is stored and the manager refuses to write anything that is not a readable ZIP. The entry count is the invariant to report: on the reference controller the project archive held the same number of entries at every measurement while its **size drifted upwards** (423–431 KB earlier, 452133 B on 2026-11-20) because the trend data inside it keeps growing. **Never check a backup against a size band** — doing so rejects a good archive exactly when a restore matters. Entries of a password-protected archive are listed without the password; only their contents are encrypted.

Two related hardening findings from the same round, and where this integration stands on them:

- *A `Content-Disposition` filename joined onto a local directory is a path-traversal sink.* Not applicable here by construction: file names are generated from host, kind and timestamp (`backup_utils.backup_filename`) and the host is passed through `safe_host`, so the controller's response headers never choose a path.
- *A project backup is a copy of the whole installation and should not be created at the process umask.* Stored files are `chmod 0600` in `backup.py` before the atomic rename.

**This surface is far wider than the four calls above, and that is a safety fact, not trivia.**
Measured 2026-11-22 (the skillset's twelve-app store survey): the controller's `management` app
registers `location /api/management/v1` as its own nginx route and exposes **39 operations**,
all answering 200 with the ordinary admin credential — `flashsys/system/hostname` (GET *and*
PATCH), `flashsys/Network/KNCConnection` (PATCH — the KNX connection itself),
`flashsys/Network/BACnet` (PATCH), `POST flashsys/system/AdminAccess`,
`POST scada-main/general/restore` and `POST flashsys/system/RestoreConfiguration`,
`GET`/**`DELETE`** on `scada-main/Logs` and `scada-main/ErrorLogs`, the `project_backups` family
(list/get/post/patch/**restore**/delete), `ets_project_backups`, Modbus profiles, `users`, the
OpenVPN/WireGuard settings and the cloud pairing and remote-access grants. The route is
**HTTPS-only** (it answers 406 over plain HTTP) and answers 403 to any method outside
`GET|POST|PUT|DELETE|PATCH`.

So the older note here — "no path to these exists on the management API this integration uses"
— was **wrong**, and the correction matters in one direction only: *restore is callable, and it
is one HTTP POST away from the credentials this integration already holds.* Keeping it unexposed
is now an explicit choice rather than a limitation. Not used on purpose: restore (both kinds),
admin password change, hostname/network changes, KNX/BACnet patches, log clearing. Reboot and
shutdown are genuinely absent from this surface.

Values on this surface that must stay out of entities, attributes and any future diagnostics: the
BACnet settings include a `Password` field, and `flashsys/Network/Interfaces` hands out the unit's
**MAC** on a plain read. The same round also reports a **service tag** in `custom/deviceInfo` —
which this repo's own live read of that endpoint on 2026-11-21 did *not* see (it returned exactly
`architecture`, `fwVersion`, `hwVersion`, `lastUpdate`, `uptime`; see above). The two readings are
unreconciled and it does not matter which is right for how the code should behave:
`health.parse_health` whitelists the fields it keeps (firmware, hardware, architecture, uptime,
load, memory, storage) rather than passing the payload through, so an identity field appearing in a
future firmware is published by nothing. **Keep that whitelist shape** — never forward a management
payload wholesale into an attribute dict.

## 3. Push – `POST /subscribe` (measured, and now used)

The 3rd Party API advertises two ways not to poll, and on 2026-11-22 both were measured end to
end on the reference unit (firmware 3.1.0, `apit3` 1.36.3), with the channel's last deliberately
unmeasured row — what it does across a controller reboot — closed on **2026-11-25** (§3b item 6).
One of them does not exist. The other
is what `push.py` and `push_utils.py` implement, on by default since SMA-112 — §3c is what the
code does with each measurement below, and it is the part to read before changing any of it.

| | endpoint | what the spec says | what this firmware does |
|---|---|---|---|
| WS | `GET /messaging/ws` | subscriptions **and** read/write over a WebSocket whose `Sec-WebSocket-Protocol` is "mandatory, fixed" — value never stated | 🔴 **does not exist** |
| CB | `POST /subscribe` | HTTP callback, body fully specified, `url` **HTTPS only** | ✅ implemented, and plain `http://` works |

### 3a. The WebSocket is not on this firmware

Every form of the request answers **404**: plain GET, upgrade with and without
`v12.stomp` / `v11.stomp` / `v10.stomp` / `stomp`, with and without a credential, and the
`/messaging`, `/ws`, `/messaging/ws/websocket`, `/messaging/ws/info` and SockJS path shapes. The
controls are what make that mean something — in the same run, over the same socket, with the same
request builder: `/node` without upgrade headers → **200**, `/node` *with* the upgrade headers
still attached → **200**, `/node` without a credential → **401**, and an invented
`messaging/nope-control` path → **404**. So the route is indistinguishable from a path that was
made up, and the 404 comes back even unauthenticated, i.e. it is a routing answer and not an auth
answer. On the box: nginx registers no `messaging/*` location, the on-box OpenAPI path set (33
definitions) has no such entry, the string `messaging` appears nowhere in `/data/apps` or `/www`
(so the Touch front-end does not speak it either), there is no Lua WebSocket *server* library, and
`apit3` is at the store's latest build. The only trace is a `Sec-WebSocket-Protocol` parameter stub
with **no enum and no default** — the controller's own definition does not state the value the
published spec calls fixed.

**Do not design against this endpoint, and do not write a frame encoder for it.** One good
consequence: the "push might require OAuth against the Schneider cloud" risk never arises, because
the channel that does exist takes the same HTTP Basic credential as every other surface. Re-run the
probe after a firmware update rather than assuming it stays absent.

### 3b. The callback channel, and the six things that change code

```http
POST /api/w4knx/3rdparty/v1/subscribe
Content-Type: application/vnd.api+json     Accept: application/vnd.api+json

{"data": [{"id": "<datapoint-uuid>", "type": "datapoint"}, ...],
 "meta": {"url": "http(s)://<ha-host>:<port>/<path>",
          "secret": "<shared secret>", "type": "subscribe.datapoint"}}
```

200 with the subscription object; all three `meta` fields are required.
`DELETE /subscriptions/{id}` → 204, and the delete was proven by re-driving the bus and recording
silence rather than by the status code. `GET /subscriptions/{id}/datapoints` lists what is
subscribed.

1. **A plain `http://` callback is accepted and honoured**, against the spec's HTTPS-only `url`:
   accepted, listed with the scheme intact, and really delivered (proven after first proving the
   controller could reach the listener at all, so a missing callback would have been unambiguous).
   That makes push reachable for an ordinary Home Assistant install with no TLS endpoint. The price
   is that every value and the signature cross the LAN in clear text — prefer HTTPS, know HTTP
   works.
2. **The frame** is JSON:API, one datapoint per POST, and
   `attributes.value` is **always a string** (`"on"`, `"100"`, `"cool"`) in the **same engineering
   units as `GET /datapoints`** — `dpt.scaling` as a percent (raw 255 → `"100"`, 51 → `"20"`), enum
   members by name, matching `attributes.enum` exactly. So `datapoints.py` decodes both paths
   unchanged. `attributes.timestamp` is real ISO-8601 UTC. `relationships` carries the subscription
   link, so one listener can demultiplex several. The subscription silently includes the two
   automation-trigger virtuals (`11111111-…`) — filter inbound by datapoint id, as the poll path
   already does.
3. 🪤 **`X-Callback-Signature`, and the secret is never echoed.** The `secret` is an HMAC key, not a
   token to compare:
   `msg = "POST " + url.path + " HTTP/1.1" + url.authority + Date + str(len(body)) + body`, header
   `= base64(lowercase_hex(HMAC-SHA256(secret, msg)))`. It is **base64 of the ASCII hex, not of the
   digest** (the controller's `hmacsha256` returns a 64-char hex string and base64-encodes those
   characters), so a verifier that base64-decodes and compares 32 raw bytes never matches. And the
   `Date` header is **local time labelled `GMT`** (an hour off the payload's own UTC timestamp on a
   CET unit) — it is inside the signed string, so feed it back **verbatim**; parsing or re-rendering
   it breaks the HMAC, and it is not a usable clock. The construction was read off the daemon's
   stripped LuaJIT bytecode instruction by instruction and then matched against live frames
   **2 of 2 exactly** — the bytecode alone would have been a reading; the match is what makes it
   a fact.

   🔴 **What that signature is worth, and what it is not.** The `secret` is stored on the
   controller **in plaintext**, in Redis under `meta.secret` beside the callback URL (measured
   2026-11-22). Anything with a root shell or on-box Lua can read every registered callback
   secret, so it is a signing key kept in clear next to the address it authenticates, and a
   reader of it can forge a callback that a *correct* verifier accepts. Verify the header anyway —
   it is what rejects a frame tampered with in flight, which matters because the channel may be
   plain HTTP — but treat it as tamper-evidence, not as proof of origin, and do not let a valid
   signature authorise anything beyond "a datapoint value changed". The rules that follow from
   it for SMA-112: generate a **fresh random secret per config entry** (never the controller
   password, never anything reused elsewhere in Home Assistant), re-generate it whenever the
   subscription is re-asserted, keep it out of the log and out of diagnostics, and bound the
   callback path to datapoint ids this entry actually subscribed.
4. 🔴 **A callback is a state notification, not an event.** Latency is sub-second (0.08–0.99 s
   across 8 samples) against the 10 s poll, and a sustained 1 Hz change delivered 40 of ~40. But a
   burst of 8 transitions 0.4 s apart delivered only **4** callbacks, each carrying the value as of
   delivery: changes closer than ~0.8 s to one datapoint are coalesced to the latest value and the
   intermediate states are never sent. Treat every callback as "this is the current value of this
   datapoint". Never count edges or reconstruct a sequence — and note that casual testing at 1 Hz
   will not show you this.
5. 🔴 **Push fails silent and does not self-heal, so the poll stays.** The REST surface is
   nginx-embedded Lua while delivery is a real daemon (`/lib/apps/daemon.lua apit3 …`), i.e. two
   different things. Kill the daemon with a live subscription and: the subscription record survives
   and keeps being listed, the REST API keeps answering 200, delivery stops completely, and nothing
   restarts it (120 s; procmon does not watch app daemons — §1 above). Before and after the restart
   delivery was 7 of 7, so the record itself is durable. **Nothing in the API distinguishes
   "subscribed and quiet" from "subscribed and dead"**, so a liveness timeout that falls back to
   reading `/datapoints` is mandatory, and `scan_interval` should become a slow backstop rather than
   being removed. Re-assert the subscription on startup and after any gap — for the reason in
   item 6, which since 2026-11-25 is a measured one rather than insurance against an unknown.
6. **Across a controller reboot: the subscription survives, and a `200` still proves nothing.**
   Measured 2026-11-25 on the reference unit under a one-time authorisation from its owner (a
   FlashSYS reboot is a destructive action on a live house; the skillset's rig refuses to run this
   leg without the authorisation recorded in the artefact, and it has not been re-run). The
   subscription record was still listed afterwards, **delivery resumed with no re-subscribe**, the
   pinned certificate was unchanged, and subscriptions that existed before the run were intact. Two
   controls are what make that a measurement rather than a tautology: the reboot demonstrably
   happened (`/proc/uptime` 13 days → 12.7 s, `apit3` back under a new pid) and the record was
   provably not on flash beforehand (0 hits grepping the on-flash snapshot for the subscription id
   while it was live and delivering, against 1 hit on the same file afterwards). Three consequences,
   and the first two are the ones that reach this integration:

   | mark | seconds after the reboot was triggered |
   |---|---|
   | REST surface stops answering | 5 |
   | **REST surface answers 200 again** | **25** |
   | `apit3` delivery daemon running again | 34.5 |
   | **first callback actually delivered** | **39.6** |

   🔴 **A `200` from the API does not mean push is flowing — and now that is also what a *healthy*
   startup looks like.** There is a ~15 s window where every endpoint answers, the subscription is
   listed, and nothing is being delivered. It is the same silent-failure shape as item 5, so the
   same rule covers both: hold the fast poll until callbacks are observed *arriving*, never because
   the API answered.

   🪤 **Delivery is lossy for roughly the first minute, then is not.** The drive immediately after
   the reboot delivered 3 of 7 changes — the three arriving in the same second, each carrying its
   datapoint's *latest* value — and 7 of 7 again on the settled box five minutes later. So the
   coalescing of item 4 is much wider during warm-up: state converges correctly, counted edges do
   not. Nothing was lost in the only sense that matters for an entity.

   ⬛ **A subscription is a cache entry, not a database row, so an *unclean* power loss can still
   lose one — inferred, not measured.** Its only store is a key in the controller's Redis
   (`app:se-apit3:subscriptions`): with a subscription live and listed, its id is in no SQLite table
   and in no file on disk. Redis's only flash copy is a snapshot written every 1800 s and on a clean
   shutdown — which is *why* the clean reboot above preserved it. A power cut is therefore expected
   to drop any subscription registered since the last snapshot, up to half an hour's worth, and
   nothing in the 3rd Party API can force a flush. Pulling power on a live house is not a
   measurement that will be taken, so this stays inferred — and it is the standing reason to
   re-assert on a slow beat instead of trusting `GET /subscriptions`.

### 3c. What the integration does with each of those

`push.py` owns the subscription and the callback endpoint; `push_utils.py` holds the pure parts
(signature, frame decode, body building) and is unit-tested in `tests/test_push_utils.py`. The
mapping from the six measurements above to the code:

| Measurement | What the code does |
|---|---|
| `http://` callback is honoured | the callback URL is Home Assistant's **internal** URL (`get_url`, cloud excluded) plus a webhook path, so a plain-HTTP install works with no extra setup |
| frame needs no new decoder | `parse_callback_body` returns `{id, value, timestamp}` and the value goes through the same `format_datapoint_value` the poll path uses. **No second decoder exists** |
| the two automation-trigger virtuals are included silently | `coordinator.async_apply_push_values` applies a value only to a datapoint the last poll actually returned — which keeps a frame from inventing state for an id the entity graph does not know, and `plan.py` gives the virtuals no entity. 🪤 It is **not** a filter on the virtuals themselves: on a real installation the poll *does* return both, so they pass this check, and they also go **out** in the subscribe body (`_wanted` is every exported datapoint). Harmless for state; unmeasured for the subscribe request, and one of the live candidates in §3d |
| signature is base64 of the **ASCII hex**, `Date` verbatim | `push_utils.expected_signature`, compared with `hmac.compare_digest`. The `path` and `authority` come from the **registered** URL, not from the inbound request, so a reverse proxy rewriting `Host` cannot invalidate a frame |
| the secret is kept in clear on the controller | a fresh `secrets.token_urlsafe(32)` per entry, regenerated on **every** re-assert, never logged, never in the sensor's attributes. A valid signature authorises exactly one thing: setting that datapoint's value |
| a callback is a state notification | each frame is applied as "this is the current value"; nothing counts edges |
| push fails silent and does not self-heal | **the poll never stops.** It slows to `PUSH_BACKSTOP_INTERVAL` (300 s) once a callback actually arrives and returns to `scan_interval` the moment delivery looks dead |
| a subscription survives a clean reboot, but a `200` runs ~15 s ahead of the first callback | `_async_assert` ends on `PUSH_STATUS_PENDING` with `async_set_push_cadence(False)`: a subscription that the controller accepted buys **no** cadence change, only an arriving callback does. So the window costs nothing — the integration is already polling through it |
| an unclean power loss can drop a subscription younger than the controller's last Redis snapshot | the subscription is re-asserted on a slow beat (`PUSH_RETRY_MAX_INTERVAL`) and `GET /subscriptions` is never read as proof that one is still registered. The re-assert deletes first, then creates, and a record left behind pointing at this entry's path is reconciled by path, so recovering from the lost case and the duplicated case is the same code |
| the first minute after a reboot coalesces much harder than the settled ~0.8 s | nothing counts edges, so a wider window changes no state. What it does do is make `_push_missed` fire — several datapoints moved with no callback for them — which lands on full-speed polling and a re-assert, i.e. the correct response to a channel that was in fact not delivering yet |

The liveness check is the part with no API support, so it is worth stating plainly: nothing
distinguishes "subscribed and quiet" from "subscribed and dead", so **the backstop poll is the
probe**. `coordinator._push_missed` compares each poll's values against what is held locally and
counts a datapoint that moved with no callback for it. Two in one poll is taken as delivery having
stopped; one is confirmed over a second poll, because a single miss can be the race between a poll
answer and a callback still in flight. An optimistic write cannot be mistaken for a miss — it has
already patched the local copy. That same race is why `_carry_over_pushed` keeps a value a
callback delivered *during* a poll: the poll's answer is the older snapshot, and letting it land
would roll the entity back for a whole backstop interval.

Two things are **not measured** and the code deliberately depends on neither answer: whether a
re-subscribe replaces or duplicates a record (so a re-assert always deletes first, then creates),
and whether there is a cap on datapoints per subscribe body (the whole set goes in one request and
batching is only a *fallback* if the controller refuses it). A third used to be on this list —
whether a subscription survives a controller reboot — and is now measured (§3b item 6): it does,
across a *clean* reboot. The code is unchanged by that answer, because the case it insures against
is the one still inferred: an unclean power loss, where the record is younger than the controller's
last Redis snapshot and is simply gone. Orphans are matched
by callback **path**, which is derived from the config entry id: the case that leaves an orphan is
exactly the one where Home Assistant's address changed, so matching the authority would miss it,
and matching the path means one entry can never delete another's record.

🪤 Everything in this section that needs Home Assistant itself — the webhook registration, the
watchdog, the unload path, the cadence switch — is **not covered by the test suite**, which mocks
Home Assistant. The signature, the frame decode and the liveness decision are covered.

### 3d. The first run in a real Home Assistant: the subscription was refused with a 5xx

Read from a diagnostics download on 2026-11-28 — the first HA-side evidence this channel has ever
had, and the first thing in §3 measured from inside Home Assistant rather than against the
controller. Installation: Home Assistant OS 2026.11.3, integration **0.9.0-beta.1**, 29 functions
and 44 datapoints exported.

```
push: status "unavailable"   reason "WiserKnxServerError"
      datapoints_subscribed 0   callbacks_received 0
      callbacks_rejected 0      delivery_stops 0
poll: last_update_success true   update_interval_seconds 10
      consecutive_server_errors 0
```

What that pins down, because only one code path can produce it: `reason` is set **only** in the
`except` around `_async_subscribe`, and orphan reconciliation swallows its own errors, so this is
`POST /subscribe` itself answering **5xx**. `WiserKnxServerError` is raised for nothing else. With
44 datapoints against `PUSH_SUBSCRIBE_CHUNK` of 100, exactly one request was made — the whole set
in one body, no batching — so the batching fallback is not implicated either.

Three things follow, and the third is the useful one:

- 🔴 **Push has never worked on an installation, and the degradation path did.** `status` was the
  pre-0.9.1 spelling of `failed`, the cadence went back to `scan_interval`, and the poll was
  perfectly healthy at that moment: success true, **zero** consecutive server errors. Nothing looked
  broken to the user, which is exactly what the backstop is for and is also why this sat unreported
  for two days.
- **The controller was answering reads fine while refusing to register a callback.** So this is not
  the intermittent 5xx that `/datapoints` and `/functions` throw while the export recomputes (§4) —
  that would have shown up in `consecutive_server_errors`. It is specific to the subscribe handler.
- 🪤 **The bare class name was not enough to diagnose it, and that is now fixed.** 500, 503 and 504
  from this unit point at different halves of it, and the status code was only ever in a
  `_LOGGER.debug` line that a default installation does not write. `push_utils.subscribe_failure_reason`
  now puts it in the reason (`WiserKnxServerError (HTTP 500)`), while still keeping the exception's
  *message* out, because that names the controller's address and the reason is an entity attribute
  that travels into a diagnostics download.

**Which 5xx, and therefore why, is still unknown** — do not fix towards a guess. The candidates
have not been narrowed by anything measured: the callback URL Home Assistant resolved (diagnostics
redacts the host by design, so the scheme and whether it is an IP or a name are not in the file),
the two automation-trigger virtuals going out in the body (`_wanted` is every exported datapoint,
and on this installation the poll returns both virtuals, so they are *not* filtered on either side),
or a body of 44 ids. The next diagnostics download from an 0.9.1-or-later build answers the first
question for free; reproducing `POST /subscribe` against a controller answers all of them.

The alternative that already works, and why it is still the wrong choice here: the localbus
WebSocket at `/apps/localbus.lp` upgrades (101) over pinned TLS with Basic auth and carries live
bus traffic — but it speaks group addresses and raw datatype codes, not datapoint UUIDs and
engineering units, and it is not gated by the Touch export. Right tool for measurement, wrong tool
for an entity graph that must stay aligned with `/datapoints`.

## Privacy rules for real data

- `wiser_dump_raw.json`, `wiser_backup_*.bin`, `wiser_mgmt_probe.json` and Touch backup JSON files (`touch_backup*.json`) are private. All of them are git-ignored; never copy any of them into the repo or into chat output.
- Share `wiser_dump_anon.json` (anonymised titles/ids) or aggregate counts instead.
- **The git-ignore list above is a filename gate, and a filename gate is not the whole defence.**
  Everything it names is a file this repository never commits; it says nothing about a credential,
  a hostname or a real LAN address pasted into a file the repository *does* commit — a doc, a test
  fixture, a tool's docstring. That is exactly how the skillset shipped two live secrets (above),
  and this repository is **public**. So check the content of what you are committing, not only its
  name. The one measured sweep of this tree (2026-11-24, credential-shape scan over every tracked
  file) found **no credential material**: its ten hits were all `"password": "Password"` UI labels
  in `strings.json`/`translations/en.json`. The same sweep is what found the owner's real
  controller address in `tests/` and `tools/`, now replaced — use `192.168.1.x`, `10.0.0.5` or
  `1.2.3.4` placeholders for a host in any example, fixture or docstring.
