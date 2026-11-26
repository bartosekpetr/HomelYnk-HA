# Architecture

Diagram current as of `47929fa` — 2026-11-26. Kept current by the diagram-upkeep routine
(SMA-213). **Two corrections, and the first is to this page's own contract.** 🪤 The previous
baseline named `16941a8`, and that sha is no longer reachable from `main`: integrating
v0.9.0-beta.1 rebased it away (the diagram commit itself came back as `fdc87e0`). So
`git log 16941a8..HEAD` still works in a checkout holding the old object and **errors in a fresh
clone** — the same dangling-sha trap `AGENTS.md` §6 records for the skillset, reproduced here by
this page. The baseline is re-pointed to the commit this run actually checked from, and the lesson
is the one already written down: a sha in a citation is only stable until someone rewrites history.
Second, `diagnostics.py` / `diagnostics_utils.py` arrived in `a086d28`, which gave them a
responsibility row ([§3](#3-components-and-responsibilities)) and an in/out row
([§5](#5-per-component-in--out)) but put them in **neither master diagram**, in no edge table and
in no confidence row — a component this page claimed to draw and did not. Both master diagrams now
carry it as edges **59–62**, and [§8](#8-confidence) rates them. Range checked:
`fdc87e0..47929fa`, which also contains `39f3bd3` (the reboot measurement, already folded into
§7 and §8 by that commit), two new read-only coordinator properties and `plan.py`'s
`_COMPOSITE_PLATFORMS` → `COMPOSITE_PLATFORMS` rename — accessors and a visibility change that
exist so diagnostics can read them, not behaviour, so no existing edge moved.

The revision before this one is where push arrived, and that remains the current shape:
`push.py` and `push_utils.py` are components, the controller has an **inbound** edge to Home
Assistant (edge 54, the only one in that direction), `manifest.json` declares `iot_class:
local_push`, and the coordinator's poll has two cadences rather than one. What push did *not*
change is the destination of every failure: the poll never stops, so every way push can break
lands on the behaviour v0.8.0 already had.

🔴 The honest line on it, repeated in [§8](#8-confidence) because it is the thing most likely to be
mis-read: the **controller** side of push is measured, the **pure** half of the implementation is
unit-tested, and the **Home Assistant** half has never run. No Home Assistant has yet received a
callback from a controller.

Subject: the `wiser_for_knx` custom integration and the whole path between Home Assistant and
a Wiser for KNX controller — config flow and options, the coordinators, the API client, the
role map and the entity plan, all ten entity platforms, the backup manager, and the KNX IoT
3rd Party API contract
(`schneider_knx_iot_3rdparty_v1_openapi.json`, [docs/controller-api.md](controller-api.md)).

Everything here is derived from the code, `manifest.json`, `hacs.json`, the CI workflow and the
measurement write-ups already in this repo and in `bartosekpetr/wiser-knx-skillset` — **a private
repository, and one its own 2026-11-23 audit found carrying live controller credentials, so it is
unpublishable rather than merely unpublished**. A measurement quoted here therefore has to stand
on its own description, and nothing may be copied out of it verbatim; there is no link a reader
outside the project could follow either. Confidence per edge is in [§8](#8-confidence), and the
rows marked **measured 2026-11-22** come from a live `fct.blindsVertical` built on scratch group
addresses — the one session that did touch a controller. The rows added on **2026-11-23** are
second-hand by construction: the HACS release gate and the certificate-changed card are *reports*
of things that happened on the owner's own installation (`AGENTS.md` §6, `15fbab6`, `16feae7`),
and the push protocol and the `Accept` matrix were measured by the skillset's rigs and are
summarised here from `AGENTS.md` and [docs/controller-api.md](controller-api.md). The two rows
added on **2026-11-24** — the `apit3` component split and the plaintext callback secret — are
second-hand in the same way: both were measured on the skillset's reference controller on
2026-11-22 and only written up on 2026-11-23, and they are here because they are the *mechanism*
under two rows that already existed. Nothing in either revision touched a controller, a Home
Assistant or the network.

The single most important thing on this page: **the integration owns almost nothing of what a
user sees.** Which devices exist, which channels are exported, what a value means and whether a
write has any effect are all controller-side decisions. Most "integration bugs" are the
controller answering honestly. [§7](#7-failure-attribution) is the table for that.

---

## 1. Master diagram — ASCII

```
  EXTERNAL - can change with nobody in this repo acting
  +----------------------+  +----------------------------+  +---------------------------+
  | GitHub releases      |  | GitHub Actions             |  | Wiser Touch widget config |
  | + HACS               |  | .github/workflows/         |  | slots / channels /        |
  | distribution channel |  | validate.yml  (CI only)    |  | disable_export            |
  | reads a PUBLISHED    |  | ruff==0.17.3, pytest,      |  | the real source of truth, |
  | release; a tag alone |  | compileall, hassfest@master|  | NOT readable over either  |
  | is invisible (1)     |  | hacs/action@main, nightly  |  | API                       |
  +----------+-----------+  +----------------------------+  +------------+--------------+
        (1)  | installs custom_components/wiser_for_knx               (2)| gates export
             v                                                           |
 +============================ HOME ASSISTANT PROCESS =====================|===========+
 |                                                                        |           |
 |  HA-OWNED SURFACES                                                     |           |
 |  zeroconf (3)   dhcp (4)   user "Add integration" (5)                  |           |
 |  config entry store: data + options (6,7,8)   entity registry (11,12)  |           |
 |  device registry (10,11)   issue registry (13)   service registry (14) |           |
 |  HA backup subsystem (16)  HA executor (18,21)  shared aiohttp session (20)        |
 |  reauth trigger (9)  <config>/wiser_backups/ (17)  diagnostics API (59)|           |
 |      |                                                                 |           |
 |      v                                                                 |           |
 |  +-------------------------+                 +---------------------------+         |
 |  |     config_flow.py      |  (6) creates    |        __init__.py        |         |
 |  | user|zeroconf|dhcp ->   |---------------->| migrate v1->v2->v3 (7)    |         |
 |  | credentials ->          |  entry, then    | setup / unload / remove   |         |
 |  | [trust_certificate] ->  |  (8) reload     | deletes no entity (12)    |         |
 |  | backup -> entry         |<----------------| create_backup svc (14,15) |         |
 |  | options flow, reauth (9)|                 | initial-backup task       |         |
 |  +-----------+-------------+                 +--+------+--------+--------+         |
 |        (30)  | uses tls, identity,       (23)|  (24)|   (25)|   (22)|              |
 |              | backup_utils, api            |      |        |       |              |
 |              |                              v      v        v       |              |
 |              |       +-----------------------+  +---------+  +-----------+         |
 |              |       |    coordinator.py     |  | health  |  | backup.py |         |
 |              |       | WiserKnxDataUpdate-   |  | coordi- |  | manager + |         |
 |              |       | Coordinator           |  | nator   |  | HA pre/   |         |
 |              |       | datapoints every 10 s |  | 5 min   |  | post hooks|         |
 |              |       | static cache 1 h,     |  | poll,   |  | lock,     |         |
 |              |       |   retry 5 min,        |  | best    |  | schedule, |         |
 |              |       |   give up at 3 h      |  | effort  |  | prune     |         |
 |              |       | enum-verbatim writes  |  +----+----+  +--+-----+--+         |
 |              |       | optimistic local state|  (28)|        (37)|  (17)|          |
 |              |       | entity_plan per poll  |       v            |      v          |
 |              |       +--+-----------------+--+     +----------+   |  <config>/      |
 |              |     (27)|                 |         | health.py|   |  wiser_backups  |
 |              |          v                |         | parse    |   |  /*.zip        |
 |              |     +-----------+          |        +----------+   |  (18 executor) |
 |              |     |  plan.py  |          |                        |                |
 |              |     | composite |          |                        |                |
 |              |     | + datapnt |          |                        |                |
 |              |     | entity    |          |                        |                |
 |              |     | specs     |          |                        |                |
 |              |     +--+-----+--+          |                        |                |
 |              |        |     |             |                        |                |
 |              |        v     v             |(32,33,34,35,36)        |                |
 |              | widgets.py  datapoints.py  |                        |                |
 |              | classify    dpa -> role     |                        |                |
 |              |   (fct URN)   (slot role)  |                        |                |
 |              |                   +--------+--+--------+------+     |                |
 |              |                   v           v        v      v     |                |
 |              |        light switch cover climate lock  sensor binary_sensor         |
 |              |        select number button (scenes + controller actions)            |
 |              |                   \            |        |        /   |               |
 |              |                    +-----------+--------+-------+    |               |
 |              |                                |                     |               |
 |              |                entity.py base + datapoint entity (36)|               |
 |              |                async_setup_plan_entities: adds what   |               |
 |              |                the plan grew, never removes          |               |
 |              |                     -> entity + device registries    |               |
 |              +-------------------------+----------------------------+               |
 |                                        v                                            |
 |                          +----------------------------+     +------------------+    |
 |                          |          api.py            |(38) |     tls.py       |    |
 |                          | WiserKnxClient             |<----| normalize/format |    |
 |                          | the ONLY aiohttp caller    |     | fingerprint,     |    |
 |                          | 5xx retried 3x (0.5s,1.0s) |     | fetch cert (21)  |    |
 |                          | api_base regex-guarded     |     +--------+---------+    |
 |                          | TLS mode fixed per client  |              |              |
 |                          +------------+---------------+              |              |
 |                                       | (40..48, 53)                 | (49)         |
 |   +-------------------------------------------------------------+                   |
 |   |                         push.py  (53..56)                   |                   |
 |   | WiserKnxPushManager: owns the subscription, the webhook HA   |                   |
 |   | answers on, the signing secret and the fallback to polling.  |                   |
 |   | A frame: verify X-Callback-Signature -> filter by datapoint  |                   |
 |   | id -> coordinator.async_apply_push_values -> listeners.      |                   |
 |   | THE POLL NEVER STOPS: 300 s while callbacks arrive,          |                   |
 |   | scan_interval the moment they do not (push fails SILENT).    |                   |
 |   | push_utils.py: signature, frame decode, subscribe body (pure)|                   |
 |   +-------------------------------------------------------------+                   |
 |   +-------------------------------------------------------------+                   |
 |   |                  diagnostics.py  (59..62)                   |                   |
 |   | HA pull, on demand only - never polled, decides nothing.    |                   |
 |   | Reads both registries, hass.states and the coordinator;     |                   |
 |   | puts each decision next to its result: category and         |                   |
 |   | viability, dpa archetype, role, platform, entity, state.    |                   |
 |   | THE ONLY EGRESS: this file goes into a public bug report.   |                   |
 |   | redact() gates it BY KEY NAME; api_base is safe only        |                   |
 |   | because api.py regex-guards it to a path (no host in it).   |                   |
 |   | diagnostics_utils.py: shaping, review, redact (pure)        |                   |
 |   +-------------------------------------------------------------+                   |
 |   const.py (39) supplies every constant above; identity.py (31) the stable ids;     |
 |   backup_utils.py (37) the pure password / filename / prune / ZIP-parse helpers     |
 +=======================================|==============================|=============+
                                         |     TRUST / OWNERSHIP BOUNDARY
                                         |     HTTPS:443, HTTP Basic (admin),
                                         |     self-signed cert pinned by SHA-256
 +=======================================v==============================v=============+
 |                       WISER FOR KNX CONTROLLER  (not ours)                          |
 |                                                                                     |
 |  GET /.well-known/knx (40)  unauthenticated, returns api.base                       |
 |                                                                                     |
 |  3rd Party API  /api/w4knx/3rdparty/v1                                              |
 |    GET /locations            (41)  also the authentication probe                    |
 |    GET /functions            (42)  meta["@type"] = fct.* URNs -> platform           |
 |    GET /datapoints           (43)  THE WHOLE ENTITY GRAPH, one request;             |
 |                                    meta["@type"] also = dic:dpa.* -> widget slot    |
 |    PUT /datapoints/values    (44)  answers 202 Accepted before deciding             |
 |    POST /subscribe           (53)  registers the HTTP callback; meta.url/secret/type|
 |    GET  /subscriptions       (53a) listed to find this entry's orphans              |
 |    DELETE /subscriptions/{id}(53b) on unload, and before every re-assert            |
 |    ---> POST to HA's webhook (54)  the ONLY inbound edge; signed, see below         |
 |    NOT USED: GET /messaging/ws - 404 on this firmware: the path DOES NOT            |
 |                   EXIST, however fully the spec describes it                        |
 |                   /sites, /node, /devices, /installations, bulk + project writes,   |
 |                   PUT /functions|locations/attributes                               |
 |                                                                                     |
 |  Management API  /api/management/v1                                                 |
 |    GET  /custom/deviceInfo                  (45)  firmware, hardware, arch, uptime  |
 |                                                   (NO MAC/serial on fw 3.1.0)       |
 |    GET  /flashsys/Status/SystemStatus       (46)  uptime, load, memory, partitions  |
 |    POST /flashsys/system/backupConfiguration(47)  system ZIP; body IS the ZIP       |
 |    POST /scada-main/general/backup          (48)  project ZIP; size drifts          |
 |    NOT USED on purpose: restore x2, admin password, hostname, KNX/BACnet, logs.     |
 |      A POLICY choice, not a missing endpoint: this route is 39 operations wide      |
 |      and every one answers 200 to the credentials the integration already holds     |
 |                                                                                     |
 |                         ^                                ^                          |
 |                         |                           (50) | export engine, gated by  |
 |                         |                                | write-object + status    |
 |                         |                                | slot pair AND by         |
 |                         |                                | disable_export, and      |
 |                         |                                | ASYNCHRONOUS (>= 15 s)   |
 |                         |                        +-------+--------+                 |
 |                         +------------------------| Touch widget   |                 |
 |                                                  | configuration  |                 |
 |                                                  +----------------+                 |
 |                                                                                     |
 |   datapoint write --(51)--> CONTROL group object --> KNX bus --> actuator            |
 |   datapoint value <--(52)-- STATUS  group object <-- actuator <-- KNX bus            |
 |   ^ the same single datapoint. Read slot and write slot are different objects.       |
 +=====================================================================================+
```

### Every edge, with direction

| # | From | To | Direction / carries |
|---|---|---|---|
| 1 | GitHub release + HACS | user's `custom_components/` | one-way, out-of-band install/update, **gated on a published release**: HACS reads releases, so a pushed tag with no release — or a draft, or a pre-release — reaches nobody |
| 2 | Touch widget config | controller export engine | one-way; decides what the API publishes |
| 3 | HA zeroconf | `config_flow.async_step_zeroconf` | push; IP, hostname, port, properties |
| 4 | HA dhcp | `config_flow.async_step_dhcp` | push; IP + MAC (OUI-matched) |
| 5 | User | `config_flow.async_step_user` | push; manual host/port/credentials |
| 6 | `config_flow` | config entry store | write, once per flow (`data` + `options`) |
| 7 | config entry store | `__init__.async_migrate_entry` | read+write; v1→v2→v3 |
| 8 | options flow | config entry store → `async_reload_entry` | write, then full entry reload |
| 9 | `ConfigEntryAuthFailed` | HA reauth → `config_flow.async_step_reauth` | one-way signal out of the coordinator |
| 10 | `__init__` | device registry | write; the controller device |
| 11 | entity platforms | entity + device registries | write; one device per function |
| 12 | entity platforms | entity registry | **add only**, at setup and on every later poll; v0.8.0 removed the setup-time delete sweep |
| 13 | `__init__._sync_transport_issues` / `async_remove_entry` | issue registry | create/delete repair issues |
| 14 | `__init__` | service registry | register/remove `wiser_for_knx.create_backup` |
| 15 | service call | **every** loaded entry's backup manager | fan-out, no target selector |
| 16 | HA backup subsystem | `backup.async_pre_backup` / `async_post_backup` | pull; never blocked by failure |
| 17 | backup manager | `<config>/wiser_backups/*.zip` | write (parse-as-ZIP, temp, `chmod 0600`, rename) and **unlink** on prune |
| 18 | backup manager | HA executor | blocking filesystem work off the loop |
| 19 | `async_track_time_interval` | `backup manager._scheduled_backup` | timer, every `backup_interval_hours` |
| 20 | HA shared aiohttp session | `api.WiserKnxClient` | injected; **not** used in pinned-cert mode |
| 21 | HA executor | `tls._fetch_fingerprint` | blocking socket off the loop |
| 22 | `__init__` | `api.WiserKnxClient` | constructs it; owns its lifetime |
| 23 | `__init__` | `coordinator` | constructs + `async_config_entry_first_refresh` |
| 24 | `__init__` | health coordinator | constructs + `async_refresh` (best effort) |
| 25 | `__init__` | backup manager | constructs + `async_start` |
| 26 | `api` | `coordinator` | locations, functions, datapoints |
| 27 | `coordinator` | `widgets.classify_function` | pure call, per function |
| 28 | health coordinator | `api.async_get_health` → `health.parse_health` | pull, every 5 min |
| 29 | health coordinator | `__init__` | `device_id` → entry `unique_id`; firmware/hw → device info |
| 30 | `config_flow` | `tls`, `identity`, `backup_utils`, `api` | probe, verify, validate |
| 31 | `__init__` | `identity.stable_id_from_legacy` | v1 unique-id migration |
| 32 | `light.py` / `switch.py` | `coordinator.data` (read), `async_write_datapoint` (write) | **different slots, see §4** |
| 33 | last-backup sensor | backup manager listener | push on every backup result |
| 34 | health sensors | health coordinator | pull from its last payload |
| 35 | buttons | backup manager / `coordinator.async_refresh_structure` | one-shot commands |
| 36 | `entity.py` | `coordinator.data`, `client.base_url` | name, area, availability, `configuration_url` |
| 37 | backup manager | `api.async_get_backup`, `backup_utils` | download, **validate as a ZIP**, name, list, prune |
| 38 | `api` | `tls.fingerprint_bytes` | builds `aiohttp.Fingerprint` once |
| 39 | `const.py` | everything | constants only, no behaviour |
| 40 | `api` | `GET /.well-known/knx` | unauthenticated; returns `api.base` |
| 41 | `api` | `GET {api_base}/locations` | also the authentication probe |
| 42 | `api` | `GET {api_base}/functions` | slow cadence only |
| 43 | `api` | `GET {api_base}/datapoints` | every poll; the whole graph |
| 44 | `api` | `PUT {api_base}/datapoints/values` | write; 202 before deciding |
| 45 | `api` | `GET /api/management/v1/custom/deviceInfo` | identity + firmware |
| 46 | `api` | `GET /api/management/v1/flashsys/Status/SystemStatus` | health |
| 47 | `api` | `POST /api/management/v1/flashsys/system/backupConfiguration` | system ZIP; the **body is the archive**, no envelope |
| 48 | `api` | `POST /api/management/v1/scada-main/general/backup` | project ZIP; same, and its size drifts upwards |
| 49 | `tls._fetch_fingerprint` | raw TLS handshake on `host:port` | **second boundary crossing**, no aiohttp, no credentials |
| 50 | Touch config | 3rd Party API | gated and asynchronous; see §4 |
| 51 | datapoint write | CONTROL group object → KNX bus → actuator | write direction |
| 52 | STATUS group object | datapoint value | read direction; may never follow 51 |
| 53 | `push.WiserKnxPushManager` | `POST {api_base}/subscribe` | write; registers the callback URL, a fresh per-entry secret and every exported datapoint id. Re-asserted on startup, when the exported set grows, after delivery stops, and on a slow beat |
| 53a | `push` | `GET {api_base}/subscriptions` | read; **orphan reconciliation only** — a record whose callback *path* is this entry's is deleted before a new one is made |
| 53b | `push` | `DELETE {api_base}/subscriptions/{id}` | write; on unload, on reload and before every re-assert. A record left behind makes the controller POST at a dead listener for ever |
| 54 | controller delivery daemon | HA webhook → `push._async_handle_callback` | **inbound, and the only edge that crosses the boundary in that direction.** Unauthenticated by necessity (the controller speaks HTTP Basic, not HA auth), so the gate is `X-Callback-Signature` + `local_only`. Always answers 200 |
| 55 | `push` | `coordinator.async_apply_push_values` | per frame; patches the value and notifies listeners. **Never** `async_set_updated_data`, which would reset the poll timer |
| 56 | `coordinator._check_push_delivery` | `push.async_delivery_stopped` | the liveness signal, and the only one that exists: a backstop poll finding values no callback reported |
| 57 | `push` | `coordinator.async_set_push_cadence` | switches the poll between the 300 s backstop and `scan_interval`. Never switches it off |
| 58 | `GET /messaging/ws` | — | **not an edge at all**: 404 on this firmware in every form tried. The spec describes it; the controller does not serve it |
| 59 | HA diagnostics API | `diagnostics.async_get_config_entry_diagnostics` | pull, **on demand only** — a human clicking *Download diagnostics*. Never polled, never scheduled, and the only edge on this page a user triggers by hand after setup |
| 60 | entity registry + device registry + `hass.states` | `diagnostics.py` | read. The registry is the authority on **what exists**, which is the one thing a screenshot of the device page cannot distinguish from a fresh install: an entity that was created and then stopped being exported is still a row |
| 61 | `coordinator` | `diagnostics.py` | read-only: `data`, `entity_plan`, health, push, the backup manager, and `server_errors` / `structure_age` — two properties that exist for this edge and no other. Reads nothing from the controller, so a diagnostics download cannot disturb a poll |
| 62 | `diagnostics_utils.build_diagnostics` | a JSON file the user attaches to a public issue | **egress, and the only one on this page that leaves for a human rather than the controller.** `redact()` is the entire gate, and it matches **by key name** — see [§8](#8-confidence) for why `api_base` survives that design and `host` does not have to |

---

## 2. Master diagram — Mermaid

```mermaid
flowchart TB
  subgraph EXT["External - changes with nobody in this repo acting"]
    HACS["GitHub releases plus HACS<br/>distribution channel<br/>reads a PUBLISHED release;<br/>a tag alone is invisible"]
    CI["GitHub Actions validate.yml<br/>ruff 0.17.3 pinned, pytest,<br/>compileall, hassfest at master,<br/>hacs action at main, nightly cron"]
  end

  subgraph HA["Home Assistant process"]
    subgraph HAS["HA-owned surfaces"]
      ZC["zeroconf discovery"]
      DH["dhcp discovery"]
      USR["User: Add integration"]
      CE["Config entry store<br/>data plus options, version 3"]
      ER["Entity registry"]
      DR["Device registry"]
      IR["Issue registry"]
      SR["Service registry"]
      HB["HA backup subsystem"]
      EX["HA executor"]
      SESS["Shared aiohttp session"]
      FS["config/wiser_backups/*.zip"]
      HADG["HA diagnostics API<br/>Download diagnostics,<br/>on demand only"]
    end

    subgraph INT["custom_components/wiser_for_knx"]
      CF["config_flow.py<br/>user, zeroconf, dhcp,<br/>credentials, trust_certificate,<br/>backup, options, reauth"]
      INIT["__init__.py<br/>migrate, setup, unload,<br/>service, deletes no entity,<br/>initial-backup task"]
      COORD["coordinator.py<br/>datapoints every scan_interval,<br/>300 s while push delivers<br/>static cache 1 h / retry 5 min / die 3 h<br/>enum-verbatim writes<br/>optimistic local state<br/>a poll finding what push did not reported it dead"]
      HCOORD["health coordinator<br/>5 min, best effort"]
      BM["backup.py<br/>manager, lock, schedule, prune<br/>ZIP gate then temp, 0600, rename<br/>plus HA pre/post backup hooks"]
      APIC["api.py WiserKnxClient<br/>the only aiohttp caller<br/>5xx retried 3x<br/>api_base regex-guarded"]
      PM["push.py WiserKnxPushManager<br/>webhook, per-entry secret,<br/>verify every frame,<br/>re-assert, orphan reconcile,<br/>switches the poll cadence"]
      PU["push_utils.py<br/>signature, frame decode,<br/>subscribe body (pure)"]
      TLSM["tls.py<br/>fingerprint pin, fetch, format"]
      IDM["identity.py<br/>MAC / serial, v1 id migration"]
      WID["widgets.py<br/>function URN to category"]
      DPM["datapoints.py<br/>dic:dpa archetype to widget-slot role<br/>plus the fct.se8000 F to C fix"]
      PLAN["plan.py<br/>composite viability plus<br/>the platform of every leftover datapoint"]
      HLT["health.py<br/>deviceInfo plus SystemStatus parsing"]
      BU["backup_utils.py<br/>password rule, filenames, prune,<br/>ZIP parse and entry count"]
      ENT["entity.py<br/>base and datapoint entity,<br/>controller device info,<br/>async_setup_plan_entities"]
      LI["light.py<br/>on/off, brightness, RGB, RGBW"]
      SW["switch.py<br/>function and datapoint switches"]
      CV["cover.py<br/>position inverted, tilt, up/down, stop"]
      CL["climate.py<br/>setpoint, HVAC mode, preset, fan"]
      LK["lock.py"]
      BS["binary_sensor.py<br/>role to device class"]
      SEL["select.py / number.py<br/>writable enums and numbers"]
      SE["sensor.py<br/>datapoint readings, 7 health,<br/>last backup, export counts"]
      BT["button.py<br/>Create backup, Rescan devices,<br/>one per KNX scene"]
      DIAG["diagnostics.py<br/>reads both registries, hass.states<br/>and the coordinator;<br/>decides nothing, writes nothing"]
      DU["diagnostics_utils.py<br/>payload shaping, the review block,<br/>and redact() BY KEY NAME (pure)"]
      CONST["const.py<br/>constants only"]
    end
  end

  DLOAD["Downloaded JSON file<br/>attached to a public bug report<br/>redact() is the only gate"]

  subgraph CTRL["Wiser for KNX controller - not ours"]
    WK["GET /.well-known/knx<br/>unauthenticated, returns api.base"]
    TP["3rd Party API /api/w4knx/3rdparty/v1<br/>GET /locations, /functions, /datapoints<br/>PUT /datapoints/values"]
    PUSH["Push API: POST /subscribe,<br/>GET and DELETE /subscriptions/id<br/>plus the delivery daemon that POSTs back"]
    WS["GET /messaging/ws<br/>in the spec, 404 on this firmware:<br/>NOT SERVED at all"]
    MG["Management API /api/management/v1<br/>GET /custom/deviceInfo<br/>GET /flashsys/Status/SystemStatus<br/>POST backupConfiguration<br/>POST scada-main/general/backup<br/>backup body IS the archive, no envelope"]
    EXPORT["Export engine<br/>gated and asynchronous"]
    TOUCH["Touch widget configuration<br/>slots, channels, disable_export<br/>unreadable over both APIs"]
    GOC["CONTROL group object"]
    GOS["STATUS group object"]
    BUS["KNX bus and actuators"]
  end

  HACS -->|"installs the folder"| INT
  CI -.->|"CI only, never runs in HA"| INT

  ZC --> CF
  DH --> CF
  USR --> CF
  CF -->|"creates entry"| CE
  CE -->|"data plus options"| INIT
  CF -->|"options change triggers reload"| INIT
  COORD -->|"ConfigEntryAuthFailed"| CF
  CF --> IDM
  CF --> TLSM
  CF --> BU
  CF --> APIC

  INIT --> APIC
  INIT --> COORD
  INIT --> HCOORD
  INIT --> BM
  INIT --> IDM
  INIT -->|"controller device"| DR
  INIT -->|"insecure_tls, insecure_http"| IR
  INIT -->|"registers create_backup"| SR
  SR -->|"fans out to every entry"| BM
  HCOORD -->|"device_id, firmware, hardware"| INIT

  COORD --> WID
  COORD --> DPM
  COORD --> APIC
  HCOORD --> APIC
  HCOORD --> HLT
  BM --> APIC
  BM --> BU
  BM -->|"write and prune"| FS
  BM --> EX
  HB -->|"pre_backup refresh, never blocking"| BM
  SESS -->|"unless a cert is pinned"| APIC
  EX --> TLSM
  TLSM -->|"fingerprint bytes"| APIC
  CONST -.-> INT

  COORD -->|"entity_plan, once per poll"| PLAN
  WID --> PLAN
  DPM --> PLAN
  PLAN --> ENT
  ENT --> LI
  ENT --> SW
  ENT --> CV
  ENT --> CL
  ENT --> LK
  ENT --> BS
  ENT --> SEL
  ENT --> SE
  ENT --> BT
  COORD --> LI
  COORD --> SW
  COORD --> CV
  COORD --> CL
  COORD --> LK
  COORD --> BS
  COORD --> SEL
  COORD --> SE
  COORD --> BT
  HCOORD --> SE
  BM --> SE
  BM --> BT
  LI -->|"entities and devices;<br/>ADD ONLY, nothing in the<br/>integration removes one"| ER
  SW --> ER
  CV --> ER
  CL --> ER
  LK --> ER
  BS --> ER
  SEL --> ER
  SE --> ER
  BT --> ER
  ENT -->|"one device per function,<br/>via_device the controller"| DR

  APIC -->|"api_base discovery"| WK
  APIC -->|"reads and writes"| TP
  APIC -->|"health and backups"| MG
  TLSM -->|"raw TLS handshake, no credentials"| CTRL
  APIC -->|"subscribe, list, delete"| PUSH
  PM --> APIC
  PM --> PU
  PM -->|"verified frame:<br/>patch value, notify listeners.<br/>NEVER resets the poll timer"| COORD
  COORD -->|"a change no callback reported"| PM
  INIT --> PM
  PM --> SE
  PUSH ==>|"POST signed callback;<br/>THE ONLY INBOUND EDGE.<br/>unauthenticated by necessity,<br/>gated by X-Callback-Signature"| PM
  APIC -.->|"never called, and<br/>there is nothing to call"| WS

  HADG -->|"a human clicks it;<br/>never polled"| DIAG
  ER -->|"what exists, plus each state"| DIAG
  DR -->|"controller plus one per function"| DIAG
  COORD -->|"data, entity_plan, health, push,<br/>server_errors, structure_age"| DIAG
  DIAG --> DU
  DU ==>|"redacted JSON; THE ONLY EGRESS,<br/>and the only edge that leaves<br/>for a human, not the controller"| DLOAD

  TOUCH --> EXPORT
  EXPORT -->|"functions first, datapoints 15 s plus later"| TP
  TP -->|"write lands on"| GOC
  GOC --> BUS
  BUS --> GOS
  GOS -->|"read comes from"| TP
```

---

## 3. Components and responsibilities

| Component | Owns | Does **not** own | If removed |
|---|---|---|---|
| `config_flow.py` | the only place credentials, transport mode and a certificate pin are decided; probe-before-prompt for discovery; options and reauth | any runtime polling or writing | integration cannot be added or reconfigured at all; existing entries keep working until an auth or certificate failure, which then has nowhere to go |
| `__init__.py` | entry lifecycle: migrate → client → coordinator → backup manager → health → device → service → platforms → initial backup | deciding *what* the controller publishes; **no longer deletes any entity** (every exported type has a platform again since v0.8.0) | nothing loads |
| `api.py` (`WiserKnxClient`) | the single HTTP chokepoint for both controller APIs; the `Accept: application/vnd.api+json` header; 5xx retry; the exception taxonomy that decides reauth vs retry; `api_base` validation | interpreting values, classifying, or deciding entity state | everything controller-facing stops; `tls.py`'s cert read still works |
| `coordinator.py` | polling cadence, the locations/functions cache and its staleness policy, enum-verbatim writes, optimistic local state, the auth/TLS → reauth escalation, and `entity_plan` — the plan recomputed once per successful poll and shared by every platform | HTTP, classification rules, what an entity *means*, backups | every controller entity and the Rescan button die. The backup *logic* is independent of it — but the manager and the health coordinator are **attached to** this object (`coordinator.backup_manager`, `coordinator.health`) and `hass.data[DOMAIN][entry_id]` *is* the coordinator, so every platform reaches them through it. Backups survive a failing coordinator; they would not survive deleting it |
| health coordinator | the controller-health values, on an independent 5-minute cadence, best effort | the entity graph | the health sensors go away; the entry still loads, and would stop learning its MAC/serial-based `unique_id` |
| `widgets.py` | **function**-level classification: Touch widget id → KNX URN (matched on the *whole* URN) → datapoint roles → title, in that order, to one of light/switch/cover/climate/lock/sensor/binary_sensor/scene/skip | which datapoint becomes which entity | every function would fall to the default category and the platform split would collapse |
| `datapoints.py` | **datapoint**-level roles: `dic:dpa.*` archetype → the Touch slot it came from (`DPA_ROLES`, every row measured), with the `dpt.*` type as fallback; the binary-token map; the `fct.se8000` F→C conversion. Pure, HA-free, unit-tested | which platform a role lands on | every entity would be back to guessing from titles and units; two `dpt.scaling` slots on one function could not be told apart |
| `plan.py` | the entity plan: which composite a function supports (`composite_is_viable`), which datapoints that composite consumes, and the platform for every datapoint left over (`datapoint_platform`). Pure, HA-free, unit-tested | reading or writing anything | platforms would each re-derive their own entity set and a datapoint could end up on two platforms, or on none |
| `health.py` | parsing `deviceInfo` + `SystemStatus` into flat values | fetching them | health sensors go blank |
| `identity.py` | the stable entry `unique_id` (MAC, then serial) and the pre-0.7 id migration | entity or device ids — those are keyed on `entry_id` | entries would key on host/IP again and DHCP churn would duplicate them |
| `tls.py` | trust-on-first-use: read a certificate without trusting it, normalise and display the SHA-256 | deciding to trust (the user does) | self-signed controllers could only be used with verification off |
| `backup.py` | the lock, the schedule, the **refusal to store a body that is not a readable ZIP**, atomic write at `0600`, prune, `last_error`, and the HA pre/post-backup hooks | the controller's backup format or password rule; whether the archive can actually be *restored* | controller backups are gone; every other entity is unaffected |
| `backup_utils.py` | the password rule, filenames, listing, pruning and the ZIP parse / entry count — pure, HA-free, unit-tested | any I/O decision | same as above |
| `entity.py` | naming, area suggestion, `via_device` nesting, the "no datapoints ⇒ unavailable" rule, role lookup for composites, the datapoint entity base (unique id = `datapoint.id`), and `async_setup_plan_entities` — the one place entities are added, on setup *and* on every later poll, and the one place that never removes any | state semantics; what the plan says | entities would lose device grouping and availability honesty, and a device added in Touch would need a reload |
| `light.py` | on/off, brightness as a percentage, RGB from the hex triplet and RGBW from the per-channel scaling slots | whether the write takes effect | dimmers and colour lights disappear |
| `switch.py` | the function-level switch, plus a switch for a writable on/off datapoint no composite took (a thermostat's fan manual mode) | — | the most-used entities disappear |
| `cover.py` | the KNX→HA position inversion, tilt, open/close via the movement object, and `STOP` as the enum member that puts a 0 on the bus | whether the actuator's stop object agrees with the controller's own stop button | shutters become a position number and a select |
| `climate.py` | the current/setpoint split, operation mode as a **preset** (not an HVAC mode), heat/cool + the `dpa.417.72` thermostat switch as the HVAC mode, fan modes, and the `fct.se8000` conversion on both directions | the thermostat obeying (202 is not confirmation) | thermostats become a temperature sensor and a setpoint number |
| `lock.py` | lock/unlock, and the fact that `ajar` is neither | — | smart locks become a select and a sensor |
| `binary_sensor.py` | the role → device-class map, the alarm/contact classes that can only come from the function, and the published-token → on/off mapping | which datapoints are binary (that is `datapoints.py`) | alarms and contacts become string sensors |
| `select.py` / `number.py` | the generic fallbacks for a writable enum and a writable number, so no exported control is invisible | role semantics | anything not modelled by a richer platform becomes read-only |
| `sensor.py` | a sensor per readable datapoint (units and device classes from the role, never from the controller's own unit string), the seven controller-health sensors, the **Last backup** sensor, and the exported function/datapoint counts | fetching anything | every reading the controller publishes becomes invisible, and so does the controller's own state |
| `button.py` | **Create backup** and **Rescan devices** (both `EntityCategory.CONFIG`), plus one button per KNX scene number | scheduling | manual backup still available via the service; rescan and scene recall have no replacement |
| `push.py` | the push subscription's whole life: the webhook Home Assistant answers on, the per-entry signing secret, verifying every frame, re-asserting the subscription, and switching the poll between its backstop and `scan_interval` | deciding *state* (that is the coordinator) and decoding a value (that is `datapoints.py`) | the integration polls every `scan_interval` and nothing else, which is exactly v0.8.0's behaviour |
| `push_utils.py` | the pure parts of that: the `X-Callback-Signature` construction, the frame decode, the subscribe body, the secret, orphan matching | anything needing Home Assistant | — |
| `diagnostics.py` / `diagnostics_utils.py` | the only read-only consumer of the whole graph: HA's **Download diagnostics** for an entry, assembling the entity and device registries, the coordinator's state and the entity plan into one payload, with every function's category and composite viability, every datapoint's archetype, role and platform, and the redaction that keeps password, user, host, MAC/serial and callback path out of a file users attach to issues. Pure half unit-tested | any decision — it reports the ones already taken, and writes nothing | the project loses its only way to see what an installation actually became; a report of a wrong entity goes back to being a screenshot |
| `const.py` | every tunable and every KNX URN | behaviour | — |

### Explicitly not part of this system

- **No restore.** Backups are downloaded only. Recovery is a manual upload in the controller's own
  web UI with the backup password. There is no code path that can restore, and deliberately so.
- **No controller administration, and this is now a policy choice rather than a limitation.**
  Measured 2026-11-22: the `management` route is **39 operations** wide and every one answers 200
  to the credentials this entry already holds — including `POST scada-main/general/restore`,
  `flashsys/system/RestoreConfiguration`, `PATCH flashsys/system/hostname`, `PATCH
  flashsys/Network/KNCConnection` (the KNX connection itself), `POST flashsys/system/AdminAccess`
  and `DELETE scada-main/ErrorLogs`. This integration calls **four** of them (health ×2, backup
  ×2). An earlier revision of this page and of `docs/controller-api.md` said no path to the others
  existed; that was wrong, and it was wrong in the direction that matters — a one-tap restore in
  Home Assistant is one POST away. Reboot and shutdown really are absent from this surface. Two
  values must stay out of entities, attributes and any future diagnostics: the BACnet settings'
  `Password` field, and the **service tag** `custom/deviceInfo` returns (`health.parse_health`
  publishes neither; see [§8](#8-confidence) for what is still unresolved about that field).
- **No WebSocket.** `GET /messaging/ws` **answers 404 on this firmware in every form tried** — it
  is specified and not served, so the websocket is not "the harder option", it is not an option.
  Do not write a frame encoder for it; re-probe after a firmware update instead of assuming it
  stays absent. The *other* route is no longer absent from this system: `POST /subscribe` is
  implemented in `push.py`, on by default, and `manifest.json` now declares `iot_class:
  local_push`. **Polling did not go away** — it is the backstop, because push fails silent and
  nothing on the controller restarts the daemon that delivers it. The protocol and its traps are
  in [§8](#8-confidence) and [docs/controller-api.md](controller-api.md) §3.
- **No scenes, schedulers or automations from the controller's own engine.** They exist on the
  LogicMachine side (Configurator `scenes`, `schedulers`, the automation plugin) and the 3rd-party
  API does not expose them — all of those paths answer 404 locally. A KNX `fct.scene` *function*
  is exposed, as one button per published scene number, because that is a datapoint write.
- **No colour temperature, no transitions, no effects.** Colour is RGB and RGBW only; the
  controller publishes nothing else for a light.
- **No history backfill from the controller.** `vis/graph` is the only series endpoint, it reads
  the `objectlog` table rather than the trend configuration, and object ids are recycled: a
  freshly created object came back carrying 100+ rows left by previous occupants of its id.
  Recorder history is Home Assistant's own.
- **No backup download from the HA UI, and no copying backups elsewhere** (e.g. `/media`).
- **No pagination.** Deliberate: `?offset=`/`?limit=` are ignored by this firmware.
- **No `title` writes.** `PUT /functions|locations/attributes` answers 405; renaming happens in HA.

---

## 4. The load-bearing data path

`GET /datapoints` is the load-bearing request: the entire entity graph is built from it, once per
`scan_interval`. Everything below is on that path or on the write path that mirrors it.

```mermaid
flowchart TB
  W0["Touch widget channel"] -->|"GATE 1: needs BOTH a write object<br/>AND its status feedback object"| W1["Channel is exportable"]
  W1 -->|"GATE 2: disable_export,<br/>only honoured as a real JSON boolean;<br/>the integer 1 is stored and ignored"| W2["Channel is exported"]
  W2 -->|"GATE 3: asynchronous.<br/>Function appears FIRST,<br/>datapoints attach 15 s later,<br/>minutes under config churn"| F["fct.* function plus its datapoints"]

  F --> G1["GET /functions - slow cadence only"]
  F --> G2["GET /datapoints - every poll"]

  G2 -->|"GATE 4: 5xx retried 3x,<br/>then UpdateFailed = no new data.<br/>NEVER an empty installation"| CD["coordinator.data"]
  G1 -->|"GATE 5: cached 1 h.<br/>Refresh failure keeps serving the cache,<br/>retries at 5 min, dies at 3 h"| CD

  CD -->|"join on schneider:parentFunction"| FN["functions with datapoints attached"]
  FN -->|"classify_function:<br/>widget id, then WHOLE URN,<br/>then datapoint roles, then title"| CAT["category: light, switch, cover,<br/>climate, lock, sensor,<br/>binary_sensor, scene, skip"]
  FN -->|"datapoint_role:<br/>dic:dpa.* archetype = the widget slot,<br/>dpt.* only as fallback"| ROLE["role per datapoint"]
  CAT --> PLAN["plan_entities"]
  ROLE --> PLAN
  PLAN -->|"composite_is_viable:<br/>no writable slot = no composite,<br/>so a misread category degrades<br/>to sensors instead of breaking"| COMP["composite entity:<br/>light, switch, cover, climate, lock"]
  PLAN -->|"every datapoint the composite<br/>did not consume"| DPE["datapoint entity:<br/>sensor, binary_sensor,<br/>select, number, switch, button"]
  COMP --> E["HA entity"]
  DPE --> E
  E -->|"GATE 6: the plan is recomputed on every<br/>successful poll and new entities are added.<br/>Nothing is ever removed, because a<br/>missing datapoint means a failed read"| REG["entity registry"]

  E -->|"TRANSFORM: percent to 0-255 for brightness,<br/>100 minus position for a cover,<br/>F to C for fct.se8000"| HAST["HA state - read path"]
  E -->|"TRANSFORM: the same, inverted - except<br/>brightness FLOORS AT 1 percent,<br/>so the write is not the read's inverse"| WR["write value"]

  WR -->|"GATE 7: value replaced by the<br/>datapoint's own enum member, verbatim"| PUT["PUT /datapoints/values"]
  PUT -->|"GATE 8: 202 Accepted means<br/>WELL-FORMED, not APPLIED"| CTL["CONTROL group object"]
  CTL --> BUS["KNX bus, actuator"]
  BUS --> STAT["STATUS group object"]
  STAT -->|"ASYMMETRY: this is what the<br/>datapoint VALUE reads back.<br/>If no actuator bridges control to status,<br/>it NEVER follows the write"| G2

  PUT -->|"optimistic: coordinator mutates<br/>its own cached value in place"| HAST
```

### Walked through, with the places the obvious model is wrong

1. **A channel is not a device, and a widget is not a device.** One Touch widget publishes 1..N
   functions, of possibly *different* types. A 6-gang light switch with all 18 slots filled gives
   **6** `fct.switchingLight` functions; `se-logic-thermostat` at full slots gives **25 functions
   and 48 datapoints**. All of them share one `schneider:widgetId`. So grouping is by
   `schneider:parentFunction` and every match is enumerated — stopping at the first match yields
   one plausible-looking entity while five channels silently go missing.

2. **A missing device is usually not a bug.** Three separate controller-side gates (above) can hide
   a correctly configured widget, and only one of them is visible in the function/datapoint graph.
   A channel with a write object but no status feedback is simply never exported, even where the
   Touch documentation calls the feedback optional.

3. **A function with no datapoints is a normal state, not an empty device.** `entity.py::available`
   returns False for it rather than reporting a confident "off" that ignores every command.

4. **A failed read is not an empty installation.** `/datapoints` and `/functions` answer 500
   intermittently — most often while the controller recomputes its export — and *permanently* while
   an `se-danfoss-thermostat` widget has its `object-device-status` slot populated. `api.py` retries
   5xx three times (0.5 s then 1.0 s); the coordinator then raises `UpdateFailed`, which makes
   entities unavailable and removes nothing. After 3 consecutive refusals the log names the Danfoss
   cause, because nothing in HA looks wrong.

5. **The structure is up to an hour stale by design.** Locations and functions are cached for
   `STATIC_REFRESH_INTERVAL` (1 h). Two things shorten that: a datapoint referencing a function or
   location id the cache has never seen triggers one extra refresh (de-duplicated through
   `_unresolved_refs`, so an orphan datapoint costs one refresh and not one per poll), and the
   **Rescan devices** button forces it. If refreshes fail the cache is still served, retried every
   5 minutes, and abandoned at 3 hours — at which point entities go unavailable rather than serving
   stale structure forever.

6. **Entities follow the plan, and the plan only grows.** Every platform registers the same
   helper (`entity.py::async_setup_plan_entities`), which reads `coordinator.entity_plan` at setup
   *and* on every coordinator update, and adds whatever key it has not seen before. That is what
   makes a widget added in Touch appear without a reload — it has to be, because a function is
   published seconds to minutes before its datapoints, so the set at setup time is routinely
   incomplete. The deliberate asymmetry: **nothing is ever removed**, because a datapoint missing
   from a poll means the controller did not answer (or the installer set `disable_export`), not
   that a device is gone. Stale entities are left for the user to delete; up to v0.7 the entry
   setup deleted "leftover" entities instead, which is exactly the behaviour a 500 could weaponise.
   The plan is computed once per poll in the coordinator rather than once per platform, because
   `se-logic-thermostat` alone can produce 25 functions and 48 datapoints.

7. **Read slot ≠ write slot.** A widget's control and status objects collapse into **one**
   datapoint: its `value` is the status object, a write to it drives the control object. So both
   optimistic *and* pessimistic state are wrong in general — where an actuator bridges control to
   status the value follows shortly, where nothing does (a lone KNX output) it never follows. The
   integration therefore updates its own cached value optimistically and **never** does
   write-then-verify-else-error.

8. **202 means well-formed, not applied.** A value that is not a member of the datapoint's `enum`
   *verbatim* is accepted and silently discarded: on the same writable switch datapoint `on`
   produces a telegram while `1` and `true` produce nothing. `coordinator._enum_member` maps the
   value onto the published spelling case-insensitively and logs a value that matches no member,
   because nothing else will report it. It reads the enum from the *last poll*, so a datapoint that
   was not in the last successful poll gets no enum mapping.

9. **Optimistic state works by reference sharing.** `async_write_datapoint` mutates
   `self.data["datapoints"][id]["value"]` in place. Entities read through
   `function_data["datapoints"][dp_id]`, which is the *same dict object* — `_async_update_data`
   attaches datapoints by reference. The optimistic update is visible to entities only because of
   that aliasing; a defensive `deepcopy` anywhere in that assignment would silently break it.

10. **Values are already in engineering units.** A `dpt.scaling` raw 128 is published as `50` with
    `unit: "%"`. Re-deriving a percentage from 0–255 would be wrong by 2.55×, so the published
    percentage is used as a percentage throughout. The 0–255 conversion in `light.py` is purely
    HA-side, between HA's brightness scale and the controller's percent.

11. **That percent↔255 conversion is lossy in both directions, truncating, and the write is not
    the read's inverse.** `int(percent/100*255)` on read; on write `int(brightness/255*100)`
    **floored at 1 % for any non-zero brightness** (`b7c69ae`, v0.8.1-beta.1). Consequences, from
    the code: HA brightness 128 writes 50 % and reads back **127**, and HA brightness 1 writes 1 %
    and reads back **2** — so the bottom of the slider moves one step on its own. The floor is
    there because the alternative was worse than a rounding artefact: 1 of 255 is 0.4 %, which
    truncated to 0 %, and 0 % is *off*, so the end of the slider a user reaches for to dim a light
    all the way turned it out instead. `turn_off` still writes a real 0 — the floor applies only to
    a brightness the user asked for. None of this is controller behaviour.

12. **Datapoint selection is by archetype, not by title or unit.** Each datapoint carries a
    `dic:dpa.*` archetype that identifies the Touch **slot** it came from, which nothing else in
    the API exposes: `dpa.800.65` is a shutter's height and `dpa.800.66` its slats, `dpa.65533.51`
    a battery level and `dpa.65533.52` its low-battery flag, although each pair shares one
    `dpt.*`. The sharpest case is a thermostat, which publishes **two** writable `dpt.switch`
    datapoints — `dpa.417.72` is the thermostat's own on/off and `dpa.417.70` its fan manual mode —
    so a lookup by type alone would turn the fan off when Home Assistant asked for the thermostat.
    Titles are user-defined KNX group-object names in the installer's own language and are used
    for nothing but a last-resort category guess. A dimmer that publishes only brightness
    correctly has *no* switch datapoint; `is_on` and the turn on/off calls fall back to brightness.

13. **Match on the whole URN.** Vendor types exist
    (`urn:knx:fct.schneider.logicThermostat.type.thermostat`). Splitting on `.` and taking the last
    segment reads that as `thermostat`; taking the segment after `fct.` reads it as `schneider`.
    `widgets.py` substring-matches the full URN for exactly this reason.

14. **A misclassified function degrades, it does not break.** `plan.py::composite_is_viable`
    refuses to build a composite whose datapoints cannot drive it: `fct.temperatureAir` with one
    reading and `fct.iTRV` with one heating demand are both classified climate and both fall
    through to plain sensors rather than becoming thermostats with no controls. Everything the
    composite does not consume becomes its own entity, so the worst case of a wrong category is a
    sensor where a richer entity could have been — never a missing reading.

15. **Two transforms are asserted, not measured.** A KNX height position counts travel *downwards*
    (0 % = fully up) while Home Assistant counts how far a cover is *open*, so `cover.py` inverts
    it; that is the KNX convention and HA's own KNX integration default, but this project has not
    verified it against a real actuator. And `fct.se8000`'s F→C conversion is measured on the
    *published* value only: undoing it on the read path follows from that measurement, while
    redoing it on a setpoint write has never been seen on a bus. Both are called out in the README
    with a request to report a mismatch.

16. **The cover stop object writes the member that puts a 0 on the bus** — `decrease`, for the
    `increase,decrease` enum this controller publishes on a `dpt.step`. Measured end to end on a
    live `fct.blindsVertical` on 2026-11-22: through the API `increase` put raw `01` on the stop
    group object and `decrease` put raw `00`, and Schneider's own Touch widgets
    (`se-shutter-vertical`, `se-shutter-horizontal`, `se-shutter-rotary`) all write literal `0`
    there from their stop button. Two independent lines, one from the bus and one from the
    vendor's own front-end, and they agree.

    The earlier **inference was wrong, in the direction that would have mattered**: it read
    `increase` → raw 1 → DPT 1.010 *Stop*, when DPT 1.010 has 0 = Stop, so the member it named
    was the one that moves a shutter. What saved it was refusing to ship an inference — item 15's
    rule applied to the one case where being wrong costs movement rather than a no-op.

    The member is resolved through `datapoints.enum_member_for_bit`, from a table of measured
    token → bit pairs, rather than hard-coded: a member encodes to its own DPT's bit and not to
    its position in the published list, so the only safe way to ask for "the member that sets this
    bit" is a lookup that can *fail*. When it fails, `STOP` is not advertised — an enum this
    project has never measured still gets no guess.

### The backup path (the project's actual main feature)

```
trigger: schedule (every backup_interval_hours, default 24) | Create backup button
       | wiser_for_knx.create_backup service (fans out to EVERY loaded entry)
       | HA pre-backup hook | initial backup after setup (2 attempts, 60 s apart)
   |
   v  async with self._lock      <- serialises every trigger; no concurrent downloads
   v  configured?  -> password must pass the controller's rule (>=8, upper, lower, digit)
   |                  an empty/invalid password raises and backups are simply skipped
   v  POST backupConfiguration  -> system ZIP   (180 s timeout)
   v  POST scada-main/general/backup -> project ZIP
   |     BOTH downloads complete before anything is written
   |     400 => password rule violated; 401/403 => auth; timeout => connection error
   v  executor, then PER KIND in order (system, then project):
   |     GATE: zip_entry_count parses the body. HTTP 200 is NOT evidence:
   |           the body IS the archive, so a JSON error or a login page
   |           answered with 200 is refused here and never stored
   v     write wiser_<host>_<kind>_<ts>.zip.tmp, chmod 0600, rename
   v  prune: keep newest `backup_keep` (default 7) PER KIND and PER HOST
   v  last_backup / last_error / last_files -> listeners -> Last backup sensor
```

Asymmetries on it:

- **The status code proves nothing about the body.** There is no JSON envelope and no `success`
  key: the body *is* the archive. So the only check that means anything is parsing it, which is
  why `zip_entry_count` runs before any write. Equally, the check that looks obvious is the wrong
  one — the project archive's **byte size drifts upwards** on its own because the controller's
  trend data lives inside it, while the entry count stays put. A size band would reject a good
  archive exactly when a restore matters.
- **The gate proves "readable ZIP", not "usable backup".** `zipfile` lists entries of a
  password-protected archive without the password, so the parse never needs it — but it also
  never opens an entry. A well-formed archive with **zero entries passes** (the unit tests assert
  that a zero-entry ZIP is valid), and no code path anywhere in this repo has ever restored one.
- **A per-kind failure is not all-or-nothing.** `_store` validates *and writes* one kind at a time
  in `BACKUP_KINDS` order — `system`, then `project`. If the system body is a ZIP and the project
  body is not, the freshly written **system file is already renamed into place** when the project
  one raises, `prune_backups` never runs for that round, and `last_backup` / `last_files` are left
  at their previous values while `last_error` is set. So the **Last backup** sensor reports a
  failure next to a new file on disk that it does not list. Only the single-kind refusal is
  covered by a test; this interleaving is read from the code (confirmed by running `_store`
  against a temp directory, see [§8](#8-confidence)).
- **`0600` is not retroactive.** The mode is applied to each file as it is written, so backups
  taken by v0.7.0-beta.2 or earlier (the mode arrived in v0.8.0) keep whatever the
  process umask gave them. Nothing re-modes the directory, so a `wiser_backups/` folder will hold
  both modes for as long as the old files survive pruning.
- **Pruning is keyed on the host string.** Filenames are `wiser_<safe_host>_<kind>_<ts>.zip` and
  `list_backups` filters on that prefix. If the controller's address changes (DHCP, or the user
  edits the host), the old files are no longer matched by any prune pass and accumulate forever.
- **The HA backup hook never blocks.** `async_pre_backup` catches `HomeAssistantError` and logs a
  warning, so an unreachable controller degrades the HA backup to "no fresh controller backup"
  rather than failing it.
- **The backup password is not the controller password.** It is stored in the entry *options*, and
  it is the only thing that can open the ZIPs. Losing it makes every stored backup unusable — there
  is no recovery path in this repo or in the controller.
- **The service has no target.** `wiser_for_knx.create_backup` iterates every loaded entry's
  manager, so on a multi-controller setup one call backs up all of them.

---

## 5. Per-component in / out

| Component | Reads | Publishes | Over |
|---|---|---|---|
| `config_flow.py` | discovery payloads; user form input; `/.well-known/knx`; `/locations`; `/custom/deviceInfo`; the peer certificate | a config entry (`data`: host, port, ssl, verify_ssl, username, password, api_base, certificate_fingerprint; `options`: backup_*), `DATA_INITIAL_BACKUP` | HA flow API; aiohttp; raw TLS socket |
| `__init__.py` | entry `data` + `options`; health payload | client, coordinators, backup manager, controller device, the `create_backup` service, repair issues | HA registries, `hass.data[DOMAIN][entry_id]` |
| `api.py` | both controller APIs | parsed dicts (locations, functions, datapoints), health dict, raw ZIP bytes, bool for a write | HTTPS + HTTP Basic |
| `coordinator.py` | `api` collections | `{"locations", "functions", "datapoints"}`, `entity_plan`, plus `UpdateFailed` / `ConfigEntryAuthFailed` | `DataUpdateCoordinator` listeners |
| health coordinator | `api.async_get_health` | flat health dict | same |
| `widgets.py` | a function dict | one of `light`/`switch`/`cover`/`climate`/`lock`/`sensor`/`binary_sensor`/`scene`/`skip` | pure call |
| `datapoints.py` | a datapoint dict (its `types`, `unit`, `enum`, `value`); a function's types | a role, an on/off state, a parsed number, a Celsius value | pure call |
| `plan.py` | the functions of the last poll | `{platform: [spec]}`, where a spec is a composite (`function_id`) or a datapoint (`datapoint_id`, `role`, `diagnostic`) | pure call |
| `health.py` | `deviceInfo`, `SystemStatus` | `device_id`, firmware, hardware, architecture, uptime, loads, memory %, storage % | pure call |
| `identity.py` | a controller info payload, or a legacy unique id | a normalised MAC or a serial — **`None` on firmware 3.1.0**, which publishes neither (measured 2026-11-21: `deviceInfo` returns only `architecture`, `fwVersion`, `hwVersion`, `lastUpdate`, `uptime`), so a manually added entry keeps its original `unique_id` for life and only the DHCP path ever learns a MAC. Handled, not a bug; `/.well-known/knx` carries no identity either, and `/node`'s `id` ends in `456789101112`, which looks like a vendor placeholder and must not be adopted as identity on the evidence of one unit | pure call |
| `tls.py` | a fingerprint string; the live peer certificate | normalised/displayable fingerprint, `aiohttp.Fingerprint` bytes | `ssl.get_server_certificate` in the executor |
| `backup.py` | options (password, interval, keep); existing files' mtimes; `api` ZIPs | `0600` ZIP files, `last_backup`/`last_error`/`last_files`, listener callbacks, a debug line carrying the entry count | filesystem, HA timer, HA backup hooks |
| `backup_utils.py` | a directory, a host, kinds, keep; a downloaded blob | validity bool, filenames, file lists, deletions, ZIP entry count (or `ValueError`) | pure + `pathlib` + `zipfile` |
| `entity.py` | `coordinator.data`, `coordinator.entity_plan`, `client.base_url` | entity name, `device_info` (model = the KNX function type), `suggested_area`, availability, extra attributes, and the `async_add_entities` calls for every platform | HA entity API |
| `light.py` | the function's datapoints | `is_on`, `brightness`, `color_mode`, `rgb_color`, `rgbw_color`; writes `on`/`off`, a percentage or a hex triplet | coordinator |
| `cover.py` | the function's datapoints | position and tilt (inverted), `is_closed`/`is_opening`/`is_closing`, supported features; writes a position, `up`/`down`, or the stop member | coordinator |
| `climate.py` | the function's datapoints | current and target temperature, HVAC mode, preset, fan mode, min/max from the datapoint; writes a Celsius setpoint, `heat`/`cool`, `on`/`off`, an enum member | coordinator |
| `lock.py` | the function's datapoints | `is_locked`, `is_jammed`, `is_open`; writes `lock`/`unlock` | coordinator |
| `binary_sensor.py` | one datapoint | `is_on`, device class | coordinator |
| `select.py` | one datapoint | options (the published enum), current option; writes a member verbatim | coordinator |
| `number.py` | one datapoint | value, min/max/step, unit; writes a number | coordinator |
| `switch.py` | the function's datapoints, or one datapoint | `is_on`; writes `on`/`off` | coordinator |
| `sensor.py` | backup manager state; health coordinator; one datapoint | `Last backup` (timestamp + attributes), 7 health sensors and 2 export counts (all `DIAGNOSTIC`), and a value per readable datapoint with a role-derived unit, device class and enum options | HA entity API |
| `button.py` | — | two `CONFIG` buttons, plus one per scene number | coordinator / backup manager |
| `diagnostics.py` | the entity and device registries, `hass.states`, the coordinator (data, `entity_plan`, poll state, health, push, backup manager), the entry's `data`/`options` | one JSON payload: `export` counts, `plan` counts, a `review` block (composites that were not viable, datapoints with no role or no title, unavailable/unknown/unnamed/`_2`-suffixed entities), then every function, datapoint and registry row — redacted | HA diagnostics API (on demand, never polled) |

---

## 6. Change exposure

### Can change version or behaviour with nobody acting

| Thing | Why it moves | Blast radius |
|---|---|---|
| `hassfest@master` and `hacs/action@main` in `validate.yml` | **mutable refs**, re-resolved on every run, and there is a nightly `cron: "0 0 * * *"` | CI can start failing or start passing differently on an untouched repo. `actions/checkout`, `actions/setup-python` are SHA-pinned and `ruff==0.17.3` is version-pinned, so this is the only moving piece in CI |
| `pytest-homeassistant-custom-component==0.13.375` | pinned, but it pulls a **real** `homeassistant` transitively | see the next table row — this pin is what decides which code the suite exercises |
| `tests/conftest.py` mocking | it injects `homeassistant.*` mocks **only when `homeassistant` is not importable** | so CI (HA installed) and the documented local Windows setup (HA not installed) run *different code* from the same test files. "Tests pass locally" and "tests pass in CI" are not the same claim |
| Controller firmware | updated by the installer/user, out of band | the export gates, the 500 behaviour, `api.base` from `/.well-known/knx`, and the engineering-unit conversions are all firmware behaviour. Every measured fact in [docs/controller-api.md](controller-api.md) is pinned to firmware 3.1.0. The absences are firmware facts too: `GET /messaging/ws` 404s *on this firmware*, and a later one could serve it — so that row is a reason not to build a websocket client today, not proof that one will never be possible |
| The Touch widget configuration | an installer edits a widget; nothing notifies HA | devices appear, change type, fan out or vanish. Nothing is exported until the gates pass, and nothing becomes an *entity* until the entry reloads |
| The size of the project backup | the controller's **trend data lives inside the archive** and keeps growing; nobody acts | `wiser_backups/` grows without any config change, and any size-based assertion about a backup rots on its own. Measured on the skillset's reference controller: 423–431 KB earlier, 452133 B on 2026-11-20, entry count unchanged throughout. This is why the entry count is the only thing compared |
| The controller's self-signed certificate | rotation, regeneration, expiry | a pinned fingerprint stops matching → `WiserKnxCertificateError` → `ConfigEntryAuthFailed` → reauth, which shows the old and new fingerprints and never re-trusts automatically. This fired on a real installation on 2026-11-22 and the card appeared as designed; submitting it calls `async_update_reload_and_abort`, so the **entry survives and the entity ids with it**. The branch a user is likely to take instead — delete and re-add — is the one that re-keys everything (see *Has no rollback*), which is why the README now says to submit the card |
| The controller's IP | DHCP | zeroconf/dhcp re-discovery updates the entry host when the stable `unique_id` matches. Already-written backup filenames keep the old host and fall out of pruning |
| HA core | users update it | min supported is `hacs.json`'s `2024.12.0`. Known pending cosmetic deprecation: `via_device` in `entity.py` should become `via_device_id` |
| HACS / GitHub releases | a published release is offered to every user | HACS only offers an update when tag, published release and `manifest.json` `version` agree — and it reads **releases**, not tags. A pushed tag with no release, a draft, or a pre-release reaches nobody: v0.8.0 sat tagged on GitHub for a day while HACS offered nothing (2026-11-22), and v0.7.0-beta.1/.2 are published as pre-releases and are therefore still invisible unless the user has turned on beta versions for this repository. The release step is manual and there is no `gh` CLI on the maintainer's host, which is what makes it skippable |

`manifest.json` has `"requirements": []` — the integration itself pulls no Python dependency, so
there is no runtime dependency-bump exposure at all. Everything above is either CI or the
controller.

### Has no rollback

- **Entity deletion is gone, and that is the point.** Up to v0.7.x `_remove_unsupported_entities`
  deleted every `binary_sensor`/`cover`/`climate` entity and any `sensor` whose unique id was not
  on an allow-list, on **every** setup — and registry removal takes the entity's customisations
  with it (name, area, icon, hidden/disabled state), which is not recoverable. v0.8.0 deleted that
  code path. Nothing in this integration removes an entity now; what a user upgrading from
  v0.5.0–v0.7.x already lost is not recoverable either. **Do not re-introduce a sweep**: the
  controller can answer "no datapoints" for reasons that have nothing to do with the device
  existing (a 500, an export being recomputed, `disable_export`), and a sweep turns any of those
  into permanent data loss.
- **Pruning unlinks files.** `prune_backups` calls `Path.unlink`. Past the `keep` count per kind,
  the file is gone.
- **The backup password.** Lost ⇒ every stored ZIP is permanently unopenable.
- **Deleting and re-adding the integration re-keys everything.** Entity unique ids are
  `wiser_for_knx_<entry_id>_<function_id>` and device identifiers are `<entry_id>_<function_id>`,
  so a new entry means new unique ids: new registry entries, suffixed entity ids, and broken
  automations. The *entry* `unique_id` is stable (MAC/serial), but the entities are not keyed on it.
- **Config entry migration is forward-only.** `async_migrate_entry` returns `False` for
  `version > 3`, so an entry written by a newer version will not load on an older one.
- **A write that lands on the bus.** No undo, by nature. This is why there is no bulk-write or
  scene-firing surface here.

---

## 7. Failure attribution

| Symptom | Suspect first | Notes |
|---|---|---|
| **Every** entity unavailable at once, HA log shows `Error fetching data` | the controller, not the integration | `/datapoints` is 5xx-ing. After 3 consecutive refusals the log names the likely cause |
| …and it never recovers | a Touch **`se-danfoss-thermostat` (floor heating) widget with `object-device-status` populated** | makes `GET /datapoints` return 500 for as long as the widget exists; deleting it restores the endpoint immediately. 37 other widget types declare the same slot and are all harmless — it is the combination |
| Entry fails to set up, retries with backoff | `ConfigEntryNotReady` from the first refresh | a 5xx or an unreachable controller at startup. Correct behaviour, not a fault |
| HA asks to re-authenticate | `ConfigEntryAuthFailed` | either 401/403 (credentials changed on the controller) **or** a certificate that no longer matches the pin. The reauth flow distinguishes them |
| A **"Controller certificate changed"** card on an installation that was working | **not a fault** | the controller now presents a different certificate than the pinned one — a regenerated or reinstalled controller certificate is the usual cause, and an upgrade is often just when it is first noticed. Compare the new fingerprint with the controller and **submit the card**: that keeps the entry, the entity ids and the history. Deleting the integration to get past it re-keys every entity |
| One device shows **Unavailable** while the rest are fine | **not a fault** | the function is published but its datapoints have not attached yet — 15 s typically, minutes during config churn. Recovers on a later poll. `fct.content` (Content widget) legitimately never has any |
| A widget configured in Touch has no HA device at all | the controller's export gates | needs **both** a write object and its status feedback; and `disable_export` suppresses export when stored as a real boolean (stored as the integer `1` it is ignored, so it *looks* set and is not). Neither is visible in the function/datapoint graph |
| …and both its slots and `disable_export` are right, and the API keeps answering 200 | the controller's **export daemon**, and there is nothing here to detect it | the function/datapoint graph is a cache that `apit3`'s daemon regenerates when the Touch config CRC changes, and nothing on the controller supervises that daemon. With it stopped the whole REST surface still answers 200 with live values and **no new widget ever appears** — because the half that answers requests is nginx-embedded Lua with no process of its own, while the half that maintains the export is the daemon ([§8](#8-confidence)). So a frozen export is indistinguishable from a complete one from inside Home Assistant and **no detector should be added**; the fix is controller-side, and neither a reboot nor an app update is a reliable one |
| A new widget appears in the API but gets no entity | the controller's export latency, then the integration | since v0.8.0 every platform adds what the plan grew on each poll, so a new device appears within one poll of its *datapoints* being published. A function with no datapoints yet produces nothing, by design |
| A 6-gang switch shows one entity instead of six | the integration, if it ever stops enumerating | channel fan-out is 1:N; grouping must be by `schneider:parentFunction`, never by widget id, and must not stop at the first match |
| Entity state lags the bus by minutes, and the **Push** sensor says `live` | the delivery daemon stopping *between* backstop polls | push has no in-band liveness signal at all, so the backstop poll is the probe: `live` only means a callback arrived at some point and no poll has caught a missed change since. A poll finding two changed values no callback reported flips it to `degraded` and puts the poll back on `scan_interval`. Worst-case lag is therefore one backstop interval (300 s), not forever |
| The **Push** sensor says `pending` and `callbacks_received` stays 0 | the controller cannot reach Home Assistant's URL | the subscription was accepted — that is what `pending` means — but nothing is being delivered. Check that HA's **internal** URL is one the controller can reach (the callback is registered against it) and that nothing between them drops the POST. Polling is at the configured interval throughout, so this costs freshness and nothing else |
| The **Push** sensor says `unavailable` | the registration, not the delivery | the `reason` attribute names which step failed: no reachable HA URL, no datapoints exported yet, or the controller refusing `POST /subscribe`. It is retried with backoff for as long as the entry is loaded |
| `callbacks_rejected` climbing | a frame that failed verification | an unsigned, mis-signed or oversized POST reached the endpoint and was dropped without touching state. One or two around a re-assert is normal (a frame signed with the previous secret); a steady climb means something else is POSTing at the webhook |
| The controller restarted, and the **Push** sensor dipped through `degraded` and back to `live` while `delivery_stops` rose by one | **not a fault** — the two halves of the controller come back separately | measured 2026-11-25: the REST surface answers `200` at 25 s and the first callback lands at **39.6 s**, and delivery is heavily coalesced for roughly the first minute (3 of 7 driven changes, each the latest value). So a poll in that window legitimately finds values no callback reported, which is exactly what `_push_missed` is for. The subscription itself survives a clean reboot, and the re-assert that follows costs nothing |
| Entity state is stale after a **power cut** and the **Push** sensor says `live` | ⚪ **inferred** — the subscription may simply be gone | a subscription is a Redis cache entry on the controller, snapshotted to flash only every 1800 s, so an unclean loss of power can drop one registered since the last snapshot. The backstop poll catches it within 300 s, flips to `degraded` and re-asserts. Nothing has to be done in Home Assistant; if it recurs, note that a clean restart does **not** have this failure mode |
| A command does nothing, HA shows the new state anyway | the controller accepted and discarded it | 202 ≠ applied. Check the log for the `accepts only …` warning from `_enum_member`; if it is absent the value matched the enum and the write did reach the bus |
| A command reaches the bus but the entity snaps back on the next poll | **not a fault** | the datapoint value is the *status* object. If no actuator bridges control → status, it will never follow. Optimistic state is the only honest option |
| Brightness comes back one or two steps off what was set | the integration's percent↔255 truncation | HA 128 → 50 % → 127, HA 1 → 1 % → 2. Lossy both ways and truncating; not a controller behaviour |
| The faintest setting on the dimmer slider switches the light off | a version **before** v0.8.1-beta.1 | 1 of 255 is 0.4 %, which truncated to 0 %, and 0 % is off. Fixed in `b7c69ae`: any non-zero brightness now writes at least 1 %. On a current version, suspect the actuator's own minimum dim level instead |
| Device names or rooms are wrong / stale | the Touch config, then the 1 h cache | `PUT /functions\|locations/attributes` answers 405, so the API `title` is an initial value only; rename in HA. `/locations` is flat with every `type: null`, so the room name is used directly as the suggested area and no floor hierarchy exists |
| A device moves to a different area after a restart | the flat `/locations` list | `suggested_area` is re-derived from `schneider:parentLocationName` each time the device is created |
| A backup fails with `Controller returned an invalid … backup` | the controller's answer, not the filesystem | HTTP 200 with a body that is not a readable ZIP (a JSON error, a login page). The response body *is* the archive, so it is parsed before it is stored, and the archive named in the message was **not** written. Never diagnose a stored archive by its size — the project archive grows with the trend data inside it, the entry count is the invariant |
| …and a new `_system_` file is on disk anyway, while **Last backup** still shows the old one | **not a fault, and not a partial write** | kinds are validated and written one at a time in order, so a refused `project` body leaves an already-renamed, complete `system` file behind. That round's prune is also skipped, so the `keep` count can sit one over until the next successful backup |
| A stored backup cannot be opened, but no error was ever reported | **the backup password, or the controller** | the ZIP gate only proves the bytes parse as an archive; it never opens an entry and a zero-entry archive passes it. Nothing in this repo restores, so "a backup exists" is not "a backup works" — check the password first |
| Entities vanished after an upgrade | upgrades **to** v0.5.0-v0.7.x | those versions deleted `binary_sensor`/`cover`/`climate` entities and function-derived sensors on every setup. v0.8.0 removed that sweep entirely, so nothing is deleted any more — the platforms are back and the entities are re-created with their old unique ids |
| Entities left over after the v0.8.0 upgrade, permanently unavailable | **not a fault** | function-keyed sensors from before v0.5.0 are not re-adopted: sensors are now keyed on `datapoint.id`. Delete them in the UI |
| A reading, control or flag the controller exports has no entity | the plan | `plan.py` assigns a platform to every datapoint; only the `dpt.uuid` automation-trigger virtuals and whole `skip` categories (media, camera, Content) are dropped on purpose. Anything else missing is a gap in `datapoint_platform` |
| A thermostat's fan turned off when the thermostat was turned off | the integration, if roles ever merge again | the two are different archetypes (`dpa.417.72` the thermostat, `dpa.417.70` the fan manual mode) and carry different roles for this reason |
| A cover's position reads inverted | the actuator's convention vs KNX's | `cover.py` assumes the KNX convention (0 % = fully up) and inverts for HA. Not verified against hardware; the widget's own `height-invert` slot is measured not to affect what the API publishes |
| A cover's stop button moves the shutter | the actuator's stop object | the integration sends the value the controller's own stop button sends (raw 0 = `decrease`, measured). An actuator wired to stop on 1 would move instead |
| An SE 8000 thermostat reads ~18 °C low or sets ~32 off | `fct.se8000`'s own F→C conversion | undone on the read path and redone on the write path. The read side follows a measurement; the write side has never been seen on a bus |
| No backup files appear, no error anywhere | no valid backup password | an empty or rule-violating password makes `configured` False and backups are skipped silently by design. Set it in **Configure** |
| Backup fails with HTTP 400 | the password rule | ≥ 8 chars with an upper-case letter, a lower-case letter and a digit, enforced by the controller |
| Backup fails with HTTP 404 on the *initial* automatic backup while the button works | open, seen once | v0.5.1 names the failing endpoint and retries once after 60 s. Check the log if it recurs |
| Old backups never get cleaned up | the host string changed | pruning matches on `wiser_<safe_host>_`; files from a previous address are orphaned |
| An HA backup succeeded but contains a stale controller backup | the controller was unreachable at pre-backup time | by design: a warning is logged and the HA backup is never blocked |
| Health sensors are blank, everything else works | the management API | the health coordinator is best effort — a failure there never blocks setup |
| Everything goes unavailable for a minute or two and recovers, and the **Uptime** sensor has restarted | **the controller rebooted itself** | its process monitor `reboot`s the unit when the 1-minute load average reaches **18**. Nothing in the integration triggers it or can prevent it, and nothing in either API announces it — the **Load (1 min)** health sensor climbing is the only advance warning, which is what makes it the one health value worth an alert threshold. Measured on the skillset's reference controller, not on this project's |
| The entry has no `unique_id` | the management API was unreachable at setup | a legacy IP-based id cannot be converted offline, so it is cleared and re-learned from `deviceInfo` or from discovery later |
| HTTP 406 from the 3rd-party API | the `Accept` header | the rule is **match the served `application/vnd.api+json` or wildcard it, and never omit the header** (full matrix in [§8](#8-confidence)): `application/json` *alone*, `text/*` and an **absent** header all answer 406, while the served type, `*/*`, `application/*` and any list containing `*/*` answer 200. So trimming `_get_headers` to plain JSON, or dropping the `*/*` from either `/.well-known/knx` probe, turns every answer on that surface into a 406 that reads like a wrong endpoint. The management API is a separate surface and takes `application/json` |
| A repair issue about insecure transport | configuration, not a fault | `insecure_tls` (ssl on, verification off, no pin) and `insecure_http` (ssl off) are mutually exclusive and are re-synced on every setup |
| Reads are slow / the controller is loaded | collection size | collections are never paged, so every poll transfers the whole datapoint set. `se-logic-thermostat` at full slots alone is 25 functions / 48 datapoints |
| Tests pass locally but fail in CI (or the reverse) | the conftest mock/real divergence | mocks are injected only when `homeassistant` is not importable |
| A new version is committed, tagged and pushed, and HACS offers nothing | the **release** step, not HACS and not the integration | HACS reads published releases. A tag on GitHub with no release attached is invisible, and so is a draft or a pre-release unless the user has enabled beta versions for this repository. Check `GET /repos/.../releases/latest`: it must answer the new tag with `draft=false` and `prerelease=false`, and `manifest.json` at that tag must match it |
| HACS shows a commit hash instead of a version | HACS installed from the `main` branch | ⋮ → *Redownload* and pick a release version. Nothing in the integration can detect or report this |

---

## 8. Confidence

### Edges

| Edge | Confidence | Basis |
|---|---|---|
| `GET /locations`, `/functions`, `/datapoints` shapes and fields | **measured** | real-controller dumps via `tools/dump_controller.py`; unit tests use real URNs and datapoint types |
| `PUT /datapoints/values` → 202, and 202 ≠ applied | **measured** | enum-verbatim probing: `on` produced a telegram, `1`/`true` produced nothing |
| Control/status collapse into one datapoint | **measured** | writing an `se-ac-switch` status datapoint emitted a `groupwrite` to `object-1` |
| `dpt.scaling` published as percent (raw 128 → `50`) | **measured** | written both ways round on the same object |
| `dic:dpa.*` archetype ⇒ the Touch slot the datapoint came from | **measured** | every row of `datapoints.py::DPA_ROLES` comes from the skillset's `widget-api-matrix.json`: 47 widget types built three ways each, slot by slot |
| Which `fct.*` a widget publishes, and with which datapoint types | **measured** | the same sweep; the mapping is the summary table in `widget-matrix.md` |
| `fct.se8000` publishes `(bus − 32) × 5/9` and labels it `C` | **measured** on the read path | three bus values, cross-checked against a control `se-thermostat` on the same group address. **Undoing it on a write is inferred**, never observed |
| A KNX height position is 0 % when fully up, so HA's position is its inverse | **asserted** | the KNX convention for DPT 5.001 and Home Assistant's own KNX integration default. Not measured here, and not reported by the API |
| The stop object's `decrease` is what a stop sends | **measured** ×2 | the write put raw `00` on the group object (2026-11-22, bus monitor), and all three vendor Touch shutter widgets write literal `0` to that slot. What an *actuator* then does with a 0 is its own affair — untested, and the README asks for a report |
| The Touch `height-invert` slot does not change what the API publishes | **measured** | the slot exports no datapoint at all, driving it from the bus left the published height unchanged, and nothing in the Touch front-end bundles reads it (2026-11-22). So HA's fixed inversion is not undermined by an installation that wires it |
| An enum member encodes by name, not by list position | **measured** | `dpt.heatCool` published `["heat","cool"]`; `heat` → raw `01`, `cool` → raw `00`, decoding the same way back |
| The function/datapoint graph is a cache the `apit3` daemon regenerates | **measured** | with that daemon stopped: 200s, live values, and no new widget exported at any wait |
| …and the half that answers requests is not a process at all | **measured 2026-11-22** | `apit3` is **two components**: the REST surface (`/functions`, `/datapoints`, `/subscribe`, `/subscriptions`) is nginx-embedded Lua with no process of its own and answers whenever nginx is up, while the export-maintaining, callback-delivering daemon is a separate process with its own pidfile. That is the *mechanism* behind the row above and behind the silent-push row below: both failures are one dead process that the answering half does not depend on. It is also why a frozen export has no in-band detector to add: the standing rule in `AGENTS.md` §4 is not to try |
| `dpt.R-G-B` carries a six-digit hex triplet | **observed-only** | the `3BHEX` unit and the measured values match it; a non-triplet value is reported as no colour rather than parsed |
| The 3rd-party API's `Accept` rule: **match the served type or wildcard it, and never omit the header** | **measured**, full matrix | 2026-11-22: `*/*`, `application/*`, `application/vnd.api+json` and any list containing `*/*` → 200; `application/json` alone, `text/*` **and an absent header** → 406. So the earlier summary ("plain json is 406") was true but misleading — the two `/.well-known/knx` probes in `api.py` send `application/json, */*` and sit in the 200 column *only* because of the `*/*`. Dropping it would turn every answer on that surface into a 406, which reads like a wrong endpoint. The matrix is in [docs/controller-api.md](controller-api.md) |
| The management route is 39 operations wide, HTTPS-only, and restore is callable with the integration's own credentials | **measured** | the skillset's app-store survey, 2026-11-22. This integration calls four of those operations; see [§3](#explicitly-not-part-of-this-system) for why the rest stay unexposed |
| `custom/deviceInfo` carries no MAC and no serial on firmware 3.1.0 | **measured 2026-11-21**, and now **in conflict with a later reading** | the 2026-11-21 live read returned only `architecture`, `fwVersion`, `hwVersion`, `lastUpdate`, `uptime`; the 2026-11-22 management-surface survey reports the same endpoint returning the unit's **service tag**. Both cannot be complete. Unresolved here, and deliberately not guessed at — ask for a re-read of the payload's key names. What *is* certain from the code: `identity.py` matches only `macAddress`/`mac`/`MAC`/`macaddress` and `serialNumber`/`serial`/`serialnumber`, and `health.parse_health` publishes neither, so a field under any other name is adopted as identity by nothing and published by nothing. If a re-read names it `serialNumber`, that changes — and it would become entry identity *and* a value in a public diagnostic |
| Collections ignore `?offset=`/`?limit=` | **measured** | `items == total` on every request |
| Export needs write object **and** status feedback | **measured** | a test layout built with channels deliberately incomplete, compared against the dump |
| `disable_export` is a real second gate, boolean-only | **measured** | written both as `true` and as `1`, then read back |
| Function published before its datapoints (~15 s, longer under churn) | **measured** | `se-alarm-water`, `se-light-dimmer-rotary`, `se-thermostat-vdc`, re-measured on a quiet controller |
| Channel fan-out 1:N; `se-logic-thermostat` → 25 functions / 48 datapoints | **measured** | full-slot sweep |
| `se-danfoss-thermostat` + `object-device-status` wedges `/datapoints` | **measured** | bisected one slot at a time; 37 other types with the same slot are harmless |
| Intermittent 5xx on `/datapoints` / `/functions` | **measured** | observed repeatedly during export recomputation |
| Datapoint and function ids stable across widget edits and renames | **measured** | ids byte-identical across edits; API `title` follows the rename |
| `PUT /functions\|locations/attributes` → 405 | **measured** | probed |
| `/locations` is flat, every `type: null` | **measured** | dumps |
| Both management backup endpoints return a password-protected ZIP | **measured** | `tools/probe_management.py`, and end-to-end in a real HA |
| The backup response has no JSON envelope and no `success` key — the body is the archive | **measured** | the same probe; re-confirmed in the wiser-knx-skillset round of 2026-11-20 |
| The project archive's size drifts upwards while its entry count holds | **measured, but not on this repo's controller** | the skillset's reference controller, **2026-11-20**: 452133 B against the 423–431 KB band recorded earlier, entry count identical at every measurement. A fact about that controller on that date — the direction is what the code relies on, not the numbers |
| `zip_entry_count` refuses a non-ZIP body, and `_store` writes nothing for that kind | **inferred from code**, unit-tested | `tests/test_backup.py` covers the single-kind refusal, the `0600` mode and a zero-entry archive. No controller has been made to answer 200 with a non-archive, so the *trigger* has never been reproduced against real hardware |
| The per-kind interleaving: a refused `project` leaves a written `system` file and skips that round's prune | **inferred from code**, confirmed locally | not covered by any test. Verified for this revision by calling `_store` directly against a temp directory with a valid `system` and an invalid `project` payload: the system file was present at `0600` and two over-`keep` files survived. Local filesystem only — no controller, no HA |
| Entries of a password-protected ZIP list without the password | **inferred** | a property of the ZIP format and of `zipfile` (only entry *contents* are encrypted); asserted in the code's docstring, not probed against a real controller archive |
| Backup password rule | **measured** | controller returns 400 below it |
| `/custom/deviceInfo`, `/flashsys/Status/SystemStatus` field names | **measured** | management-API probe; `health.py` parses the real payloads |
| Light/switch control end to end, including the 202 | **measured** | real HA against a real controller |
| The 1 % brightness floor reaches the controller as 1 % and `turn_off` still as 0 | **inferred from code**, unit-tested | `tests/test_platform_entities.py` pins 1 → 1, 128 → 50, 255 → 100 and `turn_off` → 0, and is red against the pre-`b7c69ae` conversion. No dimmer has been driven from a real Home Assistant since the change, so what an *actuator* does when asked for 1 % — dim to its own minimum, or ignore it — is unobserved |
| `/.well-known/knx` returns an `api.base` | **observed-only** | the probe works; a controller actually *moving* its base has never been seen, and the regex guard has only been unit-tested |
| HTTP 404 from a backup endpoint on the initial automatic backup | **observed-only** | seen exactly once; the button worked at the same time. Cause unknown |
| `fct.se8000` F→C conversion on `dpt.valueTemp` | **measured**, but **not on this integration's path** | verified against an `se-thermostat` on the same group address. Only matters if climate returns |
| `fct.gasSensor` concentrations (factor of 1000) | **observed-only, unexplained** | `se-air-quality` `no2`/`ozone` published `0.0215` for a raw 21.5. Sensors from functions are not imported, so it is off-path |
| zeroconf matchers (`wiser*`, `spacelynk*`, `logicmachine*` on `_http._tcp`) | **inferred** | from `manifest.json`; the probe-before-prompt guard exists precisely because the match is a guess |
| DHCP OUI matchers (`000CC6*`, `000054*`, `E04F43*`) | **inferred** | vendor ranges; they cover far more than controllers, hence the probe |
| `GET /messaging/ws` is **not served** by this firmware | **measured — an absence, deliberately established** | 2026-11-22, firmware 3.1.0 / `apit3` 1.36.3: 404 for every subprotocol and path shape, with and without a credential, identical to a deliberately invented path, while the same request builder reached 200 on `/node` in the same run; nginx registers no `messaging/*` route, the on-box OpenAPI set defines none, and the string is absent from `/data/apps` and `/www`. Four independent lines agreeing on an absence is as close as this project gets to proving one. **Do not write a frame encoder for it** |
| `POST /subscribe` + `DELETE /subscriptions/{id}` work, and a plain `http://` callback is accepted and genuinely delivered | **measured** | same round. The spec says the callback `url` must be HTTPS; the controller stores the scheme intact and delivers to it anyway — which is what makes push reachable for an ordinary HA install, at the price of values and signature crossing the LAN in clear text. `DELETE` → 204, proven by re-driving the bus and recording silence |
| The callback payload reuses the existing decoder: JSON:API, one datapoint per POST, `value` **always a string**, same engineering units as `GET /datapoints`, `timestamp` real ISO-8601 UTC | **measured** | same round. The subscription silently includes the two automation-trigger virtuals, so a consumer must filter inbound by datapoint id |
| `X-Callback-Signature` = `base64(lowercase_hex(HMAC-SHA256(secret, msg)))` over `"POST " + path + " HTTP/1.1" + authority + Date + len(body) + body` | **measured** | same round. Two traps in one row: it is base64 **of the ASCII hex**, not of the digest; and the `Date` header must be fed in **verbatim** — it is local time mislabelled `GMT`, an hour off the payload's own UTC timestamp, so parsing or re-rendering it breaks the HMAC and it is not a usable clock. The construction is not an inference from the frames: it was read instruction-by-instruction off the delivery daemon's stripped LuaJIT bytecode and then matched against live frames **2 of 2 exactly**. Delivery itself still has a single witness (our own listener); the signature no longer has none |
| The callback `secret` is a signing key the controller stores in **plaintext** | **measured 2026-11-22** | it sits in Redis under `meta.secret` beside the callback URL, readable by anything with a root shell or on-box Lua, and it is never echoed back to the subscriber. So a valid `X-Callback-Signature` proves the frame was not tampered with in flight — worth having, because the channel may be plain HTTP — and does **not** prove origin. The consequences are implemented: a fresh `secrets.token_urlsafe(32)` per config entry, regenerated on every re-assert, never logged and absent from the diagnostic sensor's attributes ([docs/controller-api.md](controller-api.md) §3b–3c) |
| A callback is a **state notification, not an event**, and push **fails silent** | **measured** | changes to one datapoint closer than ~0.8 s are coalesced to the latest value (8 transitions at 0.4 s delivered 4) — so never count edges or reconstruct a sequence; and with the delivery daemon killed the subscription stays listed and the whole REST surface keeps answering 200 while nothing is delivered indefinitely. At 1 Hz neither shows up, so casual testing will not find them. This is why **polling must stay** as a backstop with a full re-read on reconnect |
| A subscription **survives a clean controller reboot** and delivery resumes with no re-subscribe — but the REST surface answers `200` at 25 s while the first callback lands at **39.6 s** | **measured 2026-11-25** | one authorised run on the reference unit; a reboot is a destructive action on a live house and the rig refuses this leg without the owner's recorded authorisation, so it has **not** been re-run. Two controls make it a measurement rather than a tautology: the reboot demonstrably happened (uptime 13 days → 12.7 s, `apit3` back under a new pid) and the record was provably not on flash beforehand (0 greps of the on-flash snapshot for the subscription id while it was live, against 1 after). The consequence for this repo is the ~15 s window in which **every endpoint answers and nothing is being delivered** — a `200` is not evidence push is flowing, on a healthy box |
| An **unclean** power loss can drop a subscription younger than the controller's last Redis snapshot | ⚪ **inferred** from a measured storage model | measured 2026-11-25: a subscription is a Redis key (`app:se-apit3:subscriptions`) in no SQLite table and in no file on disk, and Redis's only flash copy is a snapshot on `save 1800 1` plus one on clean shutdown — which is why the clean reboot preserved it. Pulling power on a live house will not be measured, and nothing in the 3rd Party API can force a flush. This is the standing reason the subscription is re-asserted on a slow beat instead of `GET /subscriptions` being trusted |
| Coalescing is **much wider for about the first minute** after a reboot — 3 of 7 driven changes, each the latest value; 7 of 7 once settled | **measured 2026-11-25** | same run. It changes no state here (nothing counts edges) and it is *expected* to trip `_push_missed`, which lands on full-speed polling and a re-assert — the right answer for a channel that was in fact not delivering yet |
| All nine push rows above | **measured outside this repo** | by the skillset's `push_lab.py` / `push.md` (private, `0ca7709`, 2026-11-22; the signature and secret-storage rows re-stated in its architecture revision `c46a9f9`, 2026-11-23; the three reboot rows measured 2026-11-25 and written up in its `push.md` §2i–§2j, artefacts `push-storage-20261125T162807Z.json` and `push-reboot-20261125T161557Z.json`), summarised in this repo's `AGENTS.md` §6. They describe a *controller* contract — they are evidence about the controller, never about the code here. 🪤 Those two shas are **re-pointed**: that repository rewrote every commit on 2026-11-25 to purge two credentials it had committed, so the `63f6ace` and `f2bce62` cited here until now no longer resolve. A sha in a citation is only stable until someone rewrites history — match by subject line when one dangles |
| `push.py` / `push_utils.py` implement that contract correctly | **split** | the **pure half is unit-tested**: `tests/test_push_utils.py` pins the signed byte string, the base64-of-ASCII-hex encoding, the verbatim `Date` and the frame decode against the measured frame shape, and `tests/test_push_coordinator.py` covers applying a callback, the cadence switch and the liveness decision. The **Home Assistant half has never run**: the webhook registration, the URL resolution, the watchdog, the re-assert and the unload-time delete are **inferred from code**, like everything else HA-runtime in this table. No Home Assistant has yet received a callback from a controller |
| A frame the integration refuses never reaches entity state | **inferred from code**, unit-tested | an unsigned, mis-signed or oversized frame is counted and dropped before `async_apply_push_values` is reached, and a datapoint id the last poll did not return is ignored. The endpoint answers 200 either way: what the delivery daemon does with a non-200 is **not measured**, so provoking it is not worth the diagnostic |
| Push degrading always lands on working polling | **inferred from code** | every failure path — no reachable HA URL, a refused `POST /subscribe`, a callback that never arrives, delivery stopping mid-run — calls `async_set_push_cadence(False)` and leaves the coordinator on `scan_interval`, which is what the integration did before push existed. Reasoned from the code and from the fact that the poll is never cancelled, **not** demonstrated in a real Home Assistant |
| Every other spec path (`/sites`, `/node`, `/devices`, `/installations`, bulk and project writes, `POST`/`PUT /locations`) | **inferred from the spec only** | never called by this integration, never probed |
| Edge 1: HACS offers an update only from a published, non-draft, non-pre-release release | **observed-only** | v0.8.0 was tagged and pushed on 2026-11-22 and HACS offered nothing until the release was published; v0.7.0-beta.1/.2 were published *as* pre-releases and are invisible by default. Seen happening, not deliberately tested, and never bisected against HACS's own source |
| The certificate-changed reauth card is raised on a real installation | **observed-only** | owner-confirmed 2026-11-22: a controller presenting a different certificate than the pinned one produced the **"Controller certificate changed"** card with the new and previously trusted fingerprints, exactly as the code draws it. **Submitting** that card — `async_update_reload_and_abort`, entry and entity ids preserved — is still **inferred from code**: the owner removed and re-added the entry instead, so that branch has never been run |
| The v0.7.x → v0.8.x upgrade path | **never run** | v0.8.0 stable is the version every existing user will take it on, and no installation has upgraded across it. The one HA-side data point is a fresh v0.8.0-beta.2 install through HACS on 2026-11-22, reported working — no entity list was taken |
| Everything HA-runtime: flow steps, registries, scheduler, services, backup hooks, migration | **inferred from code** | `tests/conftest.py` mocks HA when it is not installed, so these are reasoned from the code and from the manual checklist in [docs/development.md](development.md), not asserted by the suite in every environment |
| Edges 59–61: diagnostics reads the registries, `hass.states` and the coordinator | **inferred from code**, pure half unit-tested | `tests/test_diagnostics.py` covers the shaping, the `review` block and the redaction against hand-built inputs. The three *reads* need a running Home Assistant — `er.async_entries_for_config_entry`, `dr.async_entries_for_config_entry` and `hass.states.get` are all mocked in the suite — so **no diagnostics file has ever been produced by a real Home Assistant.** This is the file SMA-216 asks the owner for, which makes it the one unexercised path the project is actively depending on |
| Edge 62: `redact()` keeps the owner's host, credentials, MAC/serial and callback path out of the downloaded file | **inferred from code**, unit-tested | the gate is a **key-name allowlist** (`password`, `backup_password`, `username`, `host`, `certificate_fingerprint`, `unique_id`, `device_id`, `callback_path`, `secret`), applied at any depth. 🪤 A key-name gate is exactly the shape `AGENTS.md` §5 warns about — "a list is not a gate" — because a value can ride out under a key nobody listed, and the entry's `data` is passed through wholesale. The one field that could re-introduce the host is **`api_base`, which is not redacted**; it is safe only because `api.py`'s setter regex-guards it to a plain path and rejects anything containing `//`, so it holds `/api/w4knx/3rdparty/v1` and never a URL. **That is a guarantee enforced in a different file from the redactor, and no test pins the pair** — checked by reading both on 2026-11-26, not by running them. `port` is unredacted by choice. The signing secret is not reachable from here at all: the push manager does not expose it |
| Edge 62 is the only egress from this system that is **not** to the controller | **inferred from code** | everything else crosses the boundary at the bottom of §1 to a device on the owner's LAN. This one crosses to a GitHub issue, which is public and permanent, and nothing in Home Assistant warns a user of that before the file downloads. Reasoned from the code path; no file has been produced, so what a real payload contains has never been inspected |

### Never probed

- The push path **from inside a running Home Assistant**. The controller side is measured and the
  HA-side code now exists (`push.py`: callback endpoint, signature verifier, liveness check,
  re-assertion, unload-time delete), but **no Home Assistant has yet received a callback from a
  controller**. Until one has, every claim about the registration, the watchdog and the unload path
  is read off the code. What to ask for when it is first run: the **Push** sensor's state and
  attributes, and whether entity state still tracks the bus.
- Whether a re-subscribe **replaces or duplicates** a record, and whether there is any cap on
  datapoints per subscribe body. Both deliberately not measured — the unit runs a live house — and
  the code depends on no answer to either: a re-assert always deletes before it creates, and the
  whole datapoint set goes in one body with batching only as a fallback. A third item stood here
  until 2026-11-25 — what a subscription does across a **controller reboot** — and is now measured
  (see the edge table above): it survives a clean one. What replaces it on this list is the *unclean*
  case, a power cut, which will not be measured on a live house; the subscription is still
  re-asserted on a slow beat rather than trusted to survive, now for that stated reason.
- Restore. Deliberately out of scope; the download side is the only half that was measured. The
  restore *endpoints* are no longer unknown — they are among the 39 operations measured on the
  management route and they answer to these credentials — but no stored archive has ever been
  opened with its password or fed back to a controller, by anything in this repo or any record in
  it. The ZIP gate narrows "we stored something" to "we stored
  something that parses" — it does not reach "we stored something that restores", and nothing
  here does.
- Multi-controller setups. The code supports them (`hass.data[DOMAIN]` is keyed by `entry_id`,
  pruning and filenames are per host, the service fans out), but nothing in the repo records this
  being run against two controllers at once.
- A controller actually moving its `api.base`. The code path exists and is unit-tested; it has
  never been exercised against real hardware. (A controller **presenting a changed certificate**
  mid-life no longer belongs on this list: it happened on 2026-11-22 and the card was raised as
  designed — see the edge table above for which half of that path is now observed and which half
  is still only read from the code.)
- Behaviour on any firmware other than 3.1.0 (`i.MX6UL LM2i`).
- Anything about `/datapoints` response time or memory at installation sizes larger than the dumps
  in hand. Collections are unpageable, so this is the scaling limit if one is ever hit.

---

## 9. Keeping this page honest

Every revision records `Diagram current as of <sha> — <date>` at the top. The next run diffs that
sha against `HEAD` and only re-revises if the components, their responsibilities, or how data moves
between them actually changed. Dependency bumps, test-only changes, copy edits and release notes
are not changes to this diagram.

Both Mermaid blocks on this page are validated by parsing them with `mermaid.parse`, not by eye.
