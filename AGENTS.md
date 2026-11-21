# AGENTS.md – guide for AI agents and contributors

Home Assistant custom integration **Wiser for KNX** (domain `wiser_for_knx`), repo `bartosekpetr/HomelYnk-HA`, branch `main`, MIT licensed, distributed through HACS.
Unofficial project, not affiliated with Schneider Electric or the KNX Association. The icon in `brand/` is an original design; never add Schneider/KNX logos.

Read this file first. Deeper references:
- [docs/architecture.md](docs/architecture.md) – component map, the load-bearing data path and its gates, failure attribution, per-edge confidence
- [docs/controller-api.md](docs/controller-api.md) – the two controller APIs, real-data findings, backup facts
- [docs/development.md](docs/development.md) – setup, tests, tools, release process, Windows/proxy notes
- [README.md](README.md) – user-facing documentation (keep it in sync with behaviour changes)

## 1. Purpose and scope

The project does two things:
1. **Full control and monitoring of what the controller exports** (since v0.8.0, SMA-106): every function becomes the richest entity its datapoints support — `light`, `switch`, `cover`, `climate`, `lock` — and **every datapoint the composite does not consume becomes its own entity** (`sensor`, `binary_sensor`, `select`, `number`, `switch`, scene `button`). Nothing the controller publishes is invisible. Plus controller health and export diagnostics on the controller device.
2. **Controller backups**: download the password-protected *system* and *project* ZIP backups from the controller's management API, store them in `<HA config>/wiser_backups/`, schedule them, prune old ones, and take a fresh one before every Home Assistant backup.

History worth knowing: binary_sensor, cover, climate and the function-derived sensors were **removed in v0.5.0** and **re-added in v0.8.0** on the owner's instruction, now built on the measured `dic:dpa.*` role map instead of title heuristics. `__init__.py` no longer deletes any entity (`_remove_unsupported_entities` and `_SENSOR_SUFFIXES` are gone) — every exported type has a platform again, and a datapoint missing from a poll means a failed read, not a deleted device. Do not re-introduce an entity sweep.

Deliberately **not exposed**: restore, admin password change, hostname change, KNX/BACnet patches, log clearing, reboot/shutdown (no path to them exists on the management API this integration uses — the skillset's reboot is a *different* surface). The BACnet settings contain a `Password` field; redact it if diagnostics are ever added. Also deliberately absent: the controller's own scenes/schedulers/automations (not on the 3rd-party API), history backfill from `vis/graph` (it reads `objectlog` and object ids are recycled), and cover `stop` (the enum member that means stop has never been measured — see §4).

## 2. Repository layout

```
custom_components/wiser_for_knx/
  __init__.py       setup/unload, backup manager wiring, controller device registration,
                    create_backup service, initial backup (deletes no entities, on purpose)
  api.py            WiserKnxClient: discovery, auth, locations/functions/datapoints, writes, backup download
  backup.py         WiserKnxBackupManager (lock, schedule, store atomically, prune) + HA pre/post backup hooks
  backup_utils.py   pure helpers (password rule, filenames, list/prune) – no HA imports, unit-tested
  identity.py       pure helpers for the stable unique id (MAC/serial) and v1 id migration – no HA imports, unit-tested
  button.py         "Create backup" button (config category)
  config_flow.py    user + zeroconf/dhcp credentials steps, then a "backup" step; options flow
  const.py          constants, PLATFORMS, KNX function URNs, backup endpoints
  coordinator.py    DataUpdateCoordinator (datapoint polling + cached locations/functions,
                    enum-verbatim writes, entity_plan per poll) and the health coordinator;
                    holds backup_manager
  entity.py         base entity, datapoint entity, controller_device_info(),
                    async_setup_plan_entities (the ONLY place entities are added)
  datapoints.py     dic:dpa archetype -> widget-slot role, binary tokens, fct.se8000 F->C;
                    pure, no HA imports, unit-tested
  plan.py           composite viability + the platform of every leftover datapoint;
                    pure, no HA imports, unit-tested
  health.py         pure parsing of deviceInfo/SystemStatus into the health values
  tls.py            certificate fingerprint helpers (pinning self-signed certificates)
  light.py switch.py cover.py climate.py lock.py binary_sensor.py select.py number.py
                    entity platforms; thin - the decisions live in plan.py/datapoints.py
  sensor.py         datapoint readings + controller health + "Last backup" + export counts
  widgets.py        function classification (widget id -> whole KNX URN -> datapoint titles
                    -> title); pure, no HA imports
  services.yaml, strings.json, translations/en.json (strings.json and en.json must stay identical)
  manifest.json     version, zeroconf/dhcp matchers   | brand/ icon.svg + icon.png
tests/              pytest; conftest.py mocks the homeassistant package
tools/              dump_controller.py, probe_management.py (run by hand against a real controller)
hacs.json           min HA version 2024.12.0
```

Files in the repo root that must never be committed (git-ignored): `wiser_dump_*.json`, `wiser_backup_*.bin`, `wiser_mgmt_probe.json`, `live_*.json`. They contain private installation data. `schneider_knx_iot_3rdparty_v1_openapi.json` is the vendor's public 3rd-party API spec.

## 3. How it works

**Config flow** (`config_flow.py`): `user` (manual) or `zeroconf`/`dhcp` → `credentials` → verify (`discover_endpoints` + `authenticate`) → `backup` step (password, interval hours default 24, keep default 7, "create a backup right away" default on) → entry created with `data` (host, port, ssl, verify_ssl, username, password, api_base) and `options` (backup_*). The "backup now" flag is passed to setup through `hass.data[DATA_INITIAL_BACKUP]` (a set of unique ids). An empty password means backups are skipped until set in Configure. The options flow keeps the existing password if the field is left empty and validates new ones. `OptionsFlow.config_entry` comes from the base class (HA ≥ 2024.12); do not set it in `__init__`.

**Setup** (`__init__.py`): builds `WiserKnxClient`, coordinator, first refresh (failure → `ConfigEntryNotReady`), `WiserKnxBackupManager` (stored as `coordinator.backup_manager`), registers the controller device, registers the `wiser_for_knx.create_backup` service once, forwards platforms, and runs the initial backup in a background task (one retry after 60 s). Options changes reload the entry. It deletes **no** entities.

**Polling**: `coordinator._async_update_data` fetches datapoints every `scan_interval` seconds (default 10) and locations/functions on the slow `STATIC_*` cadence into a cache (hourly, retried every 5 min, dropped after 3 h of failures; `async_refresh_structure` is the "Rescan devices" button). At the end of a successful poll it stores `coordinator.entity_plan = plan_entities(functions)` — once per poll, not once per platform.

**Entity model** (the part to understand before touching any platform):
1. `widgets.classify_function(func)` → a category from the **function** (widget id, then substrings of the *whole* KNX URN, then datapoint titles, then the function title; default `sensor`).
2. `datapoints.datapoint_role(dp)` → a role from the **datapoint's `dic:dpa.*` archetype**, which identifies the Touch *slot* it came from. The `dpt.*` type is only a fallback and `None` is a valid answer. Never classify a datapoint by its title (user-defined group object names) or by its unit.
3. `plan.plan_entities(functions)` → `{platform: [spec]}`. A composite (light/switch/cover/climate/lock) is built only if `composite_is_viable` finds the writable roles it needs; it consumes the roles in `COMPOSITE_ROLES` and **every remaining datapoint gets its own entity** via `datapoint_platform`. A category that cannot be supported degrades to datapoint entities instead of producing a broken composite.
4. `entity.async_setup_plan_entities` adds a platform's entities at setup *and* on every later poll, keyed by `spec["key"]`, and never removes anything.

Unique ids: a composite is `{DOMAIN}_{entry_id}_{function_id}` (unchanged since v0.1, so existing light/switch entities survive the v0.8.0 upgrade) and a datapoint entity is `{DOMAIN}_{entry_id}_{datapoint_id}`; both ids are stable across widget edits, group-address changes and renames.

Adding support for something new: put the decision in `datapoints.py` (a role) and `plan.py` (a platform) with a unit test, and keep the platform file thin. A new `dic:dpa.*` row must come from a measurement — the skillset's `widget-api-matrix.json` — not from a guess.

**Writes**: `PUT {api_base}/datapoints/values` with JSON:API body; HTTP 200/201/202/204 = success (the controller answers 202 Accepted).

**Backups**: `POST /api/management/v1/flashsys/system/backupConfiguration` and `/scada-main/general/backup` with JSON `{"data":{"password": "..."}}`. Returns a password-protected ZIP. Each payload is parsed as a ZIP before anything is written; files are written to a temp name, `chmod 0600`, and renamed; pruning is per kind and per host. Errors raise `HomeAssistantError` and are stored in `last_error`. HA hooks `async_pre_backup`/`async_post_backup` in `backup.py` refresh the backups before each HA backup and never block it.

## 4. Controller facts agents must know (details in docs/controller-api.md)

- HTTPS, usually a self-signed certificate (verification is on by default since v0.7.0-beta.1 and self-signed certificates are trusted by pinning their fingerprint during setup), HTTP Basic auth, user `admin`.
- The 3rd-party API at `/api/w4knx/3rdparty/v1` **requires** `Accept: application/vnd.api+json, application/json`; plain `application/json` gives **HTTP 406**.
- The management API `/api/management/v1` uses the same host, port and credentials.
- Touch widget ids (`se-light-switch`, …) are **not** in the API; classification works from KNX function URNs (`switchingLight`, `dimming`, `switchingSocket`, `switching`, …). Vendor URNs exist (`fct.schneider.logicThermostat.type.thermostat`), so match on the whole URN — never split on `.` and take a segment.
- A datapoint's `meta["@type"]` carries **two** tags: a `dic:dpa.<archetype>` and a `urn:knx:dpt.<type>`. The archetype identifies the **Touch slot** the datapoint came from, which nothing else in the API exposes, and it is the only way to tell apart slots that share a `dpt.*`: `dpa.800.65` height vs `dpa.800.66` slats, `dpa.65533.51` battery level vs `.52` low-battery, `dpa.399.56` current temperature vs `dpa.392.5x` setpoints, and — the one that bites — `dpa.417.72` a thermostat's own on/off vs `dpa.417.70` its **fan manual mode**, both writable `dpt.switch` on the same function. The full measured table is `datapoints.py::DPA_ROLES`.
- Backup password rule: ≥ 8 characters with an upper-case letter, a lower-case letter and a digit.
- A backup response has **no JSON envelope and no `success` key — the body is the ZIP**, so HTTP 200 proves nothing. `backup_utils.zip_entry_count` parses it before `backup.py` stores it. Validate by parsing and counting entries, **never by byte size**: the project archive's size drifts upwards with the trend data inside it (452133 B measured on 2026-11-20 against the 423–431 KB recorded earlier) while the entry count stayed put. Stored files are `chmod 0600`.
- `/datapoints` and `/functions` answer **500** intermittently (export being recomputed) and *permanently* while an `se-danfoss-thermostat` widget has its `object-device-status` slot populated. 5xx is retried in `api.py`; a failed poll is "no new data", never an empty installation. Never delete entities because a refresh failed.
- Writes answer **202 before deciding**: a value that is not a member of the datapoint's `enum` verbatim is accepted and silently discarded. `coordinator._enum_member` maps to the published spelling.
- An enum member is encoded **by name, not by its position in the published list** (measured 2026-11-21, API write watched on the bus): `dpt.heatCool` is published `["heat","cool"]` and `heat` puts raw `01` on the object, `cool` raw `00` — DPT 1.100's order, the reverse of the list. Encode and decode agree. So never infer a raw value from the order of `enum`; that is exactly why the shutter stop member is still unknown.
- The export is a **cache**, regenerated by the controller's `apit3` app daemon when the Touch config CRC changes, while values reach the API separately. Measured 2026-11-21 with that daemon not running: `/functions` and `/datapoints` answer 200, values stay live, and **no new widget ever appears**. A frozen export is therefore indistinguishable from a complete one from inside Home Assistant - do not add a detector for it, and do not read "the API answers" as "the export is current".
- Control and status slots collapse into **one** datapoint (value = status object, write = control object), so state is optimistic and write-then-verify must not be added.
- Values are in engineering units: `dpt.scaling` is a percentage (raw 128 → `50`), so never rescale from 0–255. `fct.se8000` is the one function that applies an F→C conversion while still labelling the unit `C`; `datapoints.temperature_in/out` undo and redo it. The read side follows the measurement, the **write side is inferred** and is flagged in the README.
- A KNX height position counts travel *downwards* (0 % = fully up) while Home Assistant counts how far a cover is open, so `cover.py` inverts it. That is the KNX convention, **not** something the API reports — unverified against hardware.
- A shutter's stop object is a DPT 1.010 start/stop published as `dpt.step` with the enum `increase,decrease`. Which member stops the shutter is **unknown**, and writing the wrong one moves it, so cover `STOP` is not advertised and the datapoint is exposed as a `select`. If this is ever measured, wire it up and delete this bullet.
- A function is published **before** its datapoints (15 s typically, minutes during config churn), and export is also gated by the widget's `disable_export` setting. So "a function with no datapoints" and "a correctly configured widget missing from the API" are both normal controller states, not bugs.
- One Touch widget can publish **many** functions, of different types (6 for a full 6-gang switch, 25 for a full `se-logic-thermostat`). Group by `schneider:parentFunction`; never key devices by widget id or stop at the first match.
- Collections are not pageable: `?offset=`/`?limit=` are ignored and `meta.collection` always reports the whole set.

## 5. Working rules

- Run `py -3 -m pytest -q tests` and `py -3 -m compileall -q custom_components tools tests` before every commit. The tests mock Home Assistant (see `tests/conftest.py`), so anything touching HA runtime behaviour (config flow, scheduling, registries, hooks) is **not** covered; say so and ask the user to test in a real HA.
- Keep `widgets.py` and `backup_utils.py` free of Home Assistant imports so they stay unit-testable. When adding an HA import to code that tests import, extend the mocks in `tests/conftest.py` and the stub list in `tools/dump_controller.py`.
- Keep `strings.json` and `translations/en.json` identical. Update `README.md` when behaviour or options change.
- Never print or commit passwords, backup files, raw dumps or the Touch backup JSON. Use `wiser_dump_anon.json` or counts when analysing real data.
- Commits: author `bartosekpetr`; end every commit message with `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.
- Version bumps: edit `manifest.json` `version`, commit "Release vX.Y.Z: …", annotated tag `vX.Y.Z`. See docs/development.md for the push/release steps.
- Do not "fix" HA-version deprecations without checking `hacs.json` minimum (2024.12.0). Known cosmetic warning: `via_device` in `entity.py` should become `via_device_id` eventually.

## 6. Status and open items

Released: v0.1.0 → v0.8.0-beta.1 (see GitHub releases; `manifest.json` is the authority). Validated against real controller data: classification and datapoint roles (unit tests use the measured URNs, archetypes and enums), management API calls (probe), backups end-to-end in HA, light/switch control (HTTP 202 handling).

**`api.py`, `health.py`, `plan.py` and `datapoints.py` were run against the live controller on 2026-11-21** (outside the repo, driven by the skillset's credential and certificate pin; the suite still mocks HA): `async_check_tls` matched the pin, `discover_endpoints` returned the expected `api_base`, `authenticate` true, all three collections read, `/custom/deviceInfo` + `/flashsys/Status/SystemStatus` parsed by `health.parse_health`, and `write_datapoint_value` wrote `42` to a scratch datapoint with the new value read back before it was restored. `plan_entities` over the same live export produced 1 climate + 1 light, consumed every real datapoint, skipped both automation-trigger virtuals and left **0 archetypes without a role**. So the HTTP, TLS and decision layers are no longer unexercised — what remains unexercised is everything that needs HA itself (platform wiring, the dynamic add path, registries, hooks).

**Not yet exercised in a real Home Assistant** (v0.8.0-beta.1 — the test suite mocks HA, so none of this is covered): the new platforms end to end (cover, climate, lock, select, number, binary_sensor, datapoint sensors and scene buttons), the dynamic add path (`async_setup_plan_entities` firing on a later poll), and the effect of the removed entity sweep on an upgrade from v0.7.x. Ask the owner to install the beta and report the entity list before releasing a stable.

Open / unverified:
- **Cover position inversion** is the KNX convention (0 % = fully up), not something the API reports. The owner has **no shutters**, so this cannot be verified here at all; a widget built on scratch group addresses exercises the export and the write path but says nothing about which way an actuator travels. Leave it asserted and keep the README's request to report a mismatch.
- **Cover stop** is not wired up. Narrowed but not closed: raw 1 inbound publishes `increase`, and a member encodes to its DPT bit rather than its list index (2026-11-21), which together imply `increase` = DPT 1.010 Stop. The outbound write on a `dpt.step` datapoint has still not been measured — do that before advertising `STOP`.
- **`fct.se8000` setpoint writes** apply the inverse of its measured F→C read conversion. The read side is measured; the write side has never been seen on a bus — and the owner **does not own an SE 8000** (2026-11-21), so this will stay inferred until a user reports it. Do not plan work that depends on verifying it.
- **`fct.gasSensor` concentrations** (`se-air-quality`'s `no2`/`ozone` published `0.0215` for a raw 21.5 — a factor of 1000, measured but unexplained upstream). Values are passed through untouched and reported in ppm as the controller labels them.
- A 404 was seen once on the *initial* automatic backup (HTTP 404 from a backup endpoint) while the button worked; v0.5.1 names the failing endpoint and retries once. Check the log if it recurs.
- No push: the 3rd-party API offers `POST /subscribe` and a websocket, and the integration polls instead. Push would cut the 10 s latency and the per-poll transfer of the whole datapoint set (collections are never paged) — the biggest remaining win, and the one that needs a live controller to build.
- Not implemented: backup download from the HA UI, copying backups elsewhere (e.g. `/media`), colour temperature, cover stop.
- A **controller-side app is ruled out** (owner decision, 2026-11-21, SMA-106): group objects that no Touch widget exports are reachable **directly over KNX/IP**, which is the one gap that would have justified one. Do not propose an `.ipk` for this integration again without a new reason; the skillset's `wiser-mcp` stays where it is. (The controller's own scenes/schedulers/trends and `rrdtool` history remain out of reach and out of scope.)
- The controller findings come from [wiser-knx-skillset](https://github.com/bartosekpetr/wiser-knx-skillset) (`skills/wiser-knx/homelynk-ha.md` is the HA chapter, `widget-matrix.md` and `widget-api-matrix.json` the per-widget evidence the role map was built from). Check it for newer rounds before re-probing a controller by hand.
- Skillset reviewed up to `9f5485a` (branch `wiser-mcp-phase2`, 2026-11-21). `homelynk-ha.md`, `widget-matrix.md` and `widget-api-matrix.json` are unchanged since `f6b39ac`; everything newer on that branch is about building apps *on* the controller (`.ipk` packaging, the app store, Lua rails, SSH posture) and has no bearing on an integration that only speaks to the two HTTP APIs.
