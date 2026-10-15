# AGENTS.md – guide for AI agents and contributors

Home Assistant custom integration **Wiser for KNX** (domain `wiser_for_knx`), repo `bartosekpetr/HomelYnk-HA`, branch `main`, MIT licensed, distributed through HACS.
Unofficial project, not affiliated with Schneider Electric or the KNX Association. The icon in `brand/` is an original design; never add Schneider/KNX logos.

Read this file first. Deeper references:
- [docs/controller-api.md](docs/controller-api.md) – the two controller APIs, real-data findings, backup facts
- [docs/development.md](docs/development.md) – setup, tests, tools, release process, Windows/proxy notes
- [README.md](README.md) – user-facing documentation (keep it in sync with behaviour changes)

## 1. Purpose and scope

The project is **backup-focused**:
1. **Controller backups** (main feature): download the password-protected *system* and *project* ZIP backups from the controller's management API, store them in `<HA config>/wiser_backups/`, schedule them, prune old ones, and take a fresh one before every Home Assistant backup.
2. **Light and switch import**: only `light` and `switch` entities are created from the controller's functions.

Deliberately **removed in v0.5.0** (do not re-add without being asked): sensor, binary_sensor, cover and climate platforms. The only sensor left is the diagnostic **Last backup** sensor. `widgets.py` still *classifies* covers/climate/sensors so they can be skipped correctly, and `__init__.py` deletes leftover registry entities of the removed types.

Deliberately **not exposed**: restore, admin password change, hostname change, KNX/BACnet patches, log clearing. The BACnet settings contain a `Password` field; redact it if diagnostics are ever added.

## 2. Repository layout

```
custom_components/wiser_for_knx/
  __init__.py       setup/unload, backup manager wiring, controller device registration,
                    create_backup service, initial backup, cleanup of removed entity types
  api.py            WiserKnxClient: discovery, auth, locations/functions/datapoints, writes, backup download
  backup.py         WiserKnxBackupManager (lock, schedule, store atomically, prune) + HA pre/post backup hooks
  backup_utils.py   pure helpers (password rule, filenames, list/prune) – no HA imports, unit-tested
  button.py         "Create backup" button (config category)
  config_flow.py    user + zeroconf/dhcp credentials steps, then a "backup" step; options flow
  const.py          constants, PLATFORMS, KNX function URNs, backup endpoints
  coordinator.py    DataUpdateCoordinator (polling locations/functions/datapoints); holds backup_manager
  entity.py         base entity + controller_device_info()
  light.py, switch.py  entity platforms
  sensor.py         only the "Last backup" diagnostic sensor
  widgets.py        classification (Touch widget id -> KNX URN -> datapoints -> title); pure, no HA imports
  services.yaml, strings.json, translations/en.json (strings.json and en.json must stay identical)
  manifest.json     version, zeroconf/dhcp matchers   | brand/ icon.svg + icon.png
tests/              pytest; conftest.py mocks the homeassistant package
tools/              dump_controller.py, probe_management.py (run by hand against a real controller)
hacs.json           min HA version 2024.12.0
```

Files in the repo root that must never be committed (git-ignored): `wiser_dump_*.json`, `wiser_backup_*.bin`, `wiser_mgmt_probe.json`. They contain private installation data. `schneider_knx_iot_3rdparty_v1_openapi.json` is the vendor's public 3rd-party API spec.

## 3. How it works

**Config flow** (`config_flow.py`): `user` (manual) or `zeroconf`/`dhcp` → `credentials` → verify (`discover_endpoints` + `authenticate`) → `backup` step (password, interval hours default 24, keep default 7, "create a backup right away" default on) → entry created with `data` (host, port, ssl, verify_ssl, username, password, api_base) and `options` (backup_*). The "backup now" flag is passed to setup through `hass.data[DATA_INITIAL_BACKUP]` (a set of unique ids). An empty password means backups are skipped until set in Configure. The options flow keeps the existing password if the field is left empty and validates new ones. `OptionsFlow.config_entry` comes from the base class (HA ≥ 2024.12); do not set it in `__init__`.

**Setup** (`__init__.py`): builds `WiserKnxClient`, coordinator, first refresh (failure → `ConfigEntryNotReady`), `WiserKnxBackupManager` (stored as `coordinator.backup_manager`), registers the controller device, registers the `wiser_for_knx.create_backup` service once, forwards platforms, removes entities of removed types, and runs the initial backup in a background task (one retry after 60 s). Options changes reload the entry.

**Polling/classification**: `coordinator._async_update_data` fetches locations, functions, datapoints every `scan_interval` seconds (default 10). `classify_function` is a staticmethod delegating to `widgets.classify_function`. `light.py`/`switch.py` create one entity per function with category `light`/`switch`. Datapoint selection is by KNX datapoint type (`dpt.switch`, `dpt.scaling`, `417.70`, `418.61`, `418.63`), then title heuristics, then first writable.

**Writes**: `PUT {api_base}/datapoints/values` with JSON:API body; HTTP 200/201/202/204 = success (the controller answers 202 Accepted).

**Backups**: `POST /api/management/v1/flashsys/system/backupConfiguration` and `/scada-main/general/backup` with JSON `{"data":{"password": "..."}}`. Returns a password-protected ZIP. Files are written to a temp name and renamed; pruning is per kind and per host. Errors raise `HomeAssistantError` and are stored in `last_error`. HA hooks `async_pre_backup`/`async_post_backup` in `backup.py` refresh the backups before each HA backup and never block it.

## 4. Controller facts agents must know (details in docs/controller-api.md)

- HTTPS, self-signed certificate (hence `verify_ssl` defaults to off), HTTP Basic auth, user `admin`.
- The 3rd-party API at `/api/w4knx/3rdparty/v1` **requires** `Accept: application/vnd.api+json, application/json`; plain `application/json` gives **HTTP 406**.
- The management API `/api/management/v1` uses the same host, port and credentials.
- Touch widget ids (`se-light-switch`, …) are **not** in the API; classification works from KNX function URNs (`switchingLight`, `dimming`, `switchingSocket`, `switching`, …).
- Backup password rule: ≥ 8 characters with an upper-case letter, a lower-case letter and a digit.

## 5. Working rules

- Run `py -3 -m pytest -q tests` and `py -3 -m compileall -q custom_components tools tests` before every commit. The tests mock Home Assistant (see `tests/conftest.py`), so anything touching HA runtime behaviour (config flow, scheduling, registries, hooks) is **not** covered; say so and ask the user to test in a real HA.
- Keep `widgets.py` and `backup_utils.py` free of Home Assistant imports so they stay unit-testable. When adding an HA import to code that tests import, extend the mocks in `tests/conftest.py` and the stub list in `tools/dump_controller.py`.
- Keep `strings.json` and `translations/en.json` identical. Update `README.md` when behaviour or options change.
- Never print or commit passwords, backup files, raw dumps or the Touch backup JSON. Use `wiser_dump_anon.json` or counts when analysing real data.
- Commits: author `bartosekpetr`; end every commit message with `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.
- Version bumps: edit `manifest.json` `version`, commit "Release vX.Y.Z: …", annotated tag `vX.Y.Z`. See docs/development.md for the push/release steps.
- Do not "fix" HA-version deprecations without checking `hacs.json` minimum (2024.12.0). Known cosmetic warning: `via_device` in `entity.py` should become `via_device_id` eventually.

## 6. Status and open items

Released: v0.1.0 → v0.5.1 (see GitHub releases). Validated against real controller data: classification (unit tests use real URNs/types), management API calls (probe), backups end-to-end in HA, light/switch control (HTTP 202 handling).

Open / unverified:
- Multi-channel Touch widgets (e.g. a light-switch widget with 3 channels, a horizontal dimmer with 2): the latest dump shows 8 light/switch functions for 6 widgets, so not every channel may be exposed as its own function. Investigate with `tools/dump_controller.py`.
- A 404 was seen once on the *initial* automatic backup (HTTP 404 from a backup endpoint) while the button worked; v0.5.1 names the failing endpoint and retries once. Check the log if it recurs.
- Socket-switch power datapoints (`dpt.power`, W) are ignored now that sensors were removed.
- RGB/RGBW and DALI lights are classified as lights but only on/off and brightness are implemented (no colour control).
- Not implemented: backup download from the HA UI, copying backups elsewhere (e.g. `/media`), diagnostic sensors from `/custom/deviceInfo` and `/flashsys/Status/SystemStatus`, CI workflow (HACS/hassfest validation), changelog file.
