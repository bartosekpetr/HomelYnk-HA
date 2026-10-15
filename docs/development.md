# Development guide

## Environment

- Windows + PowerShell is the primary environment; Python via `py -3` (3.14 tested), pytest.
- No Home Assistant is installed for tests: `tests/conftest.py` injects mock `homeassistant.*` modules. Only pure code (`widgets.py`, `backup_utils.py`, parts of `api.py`) is really exercised.
- Git: `$git = "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"`. The user's terminal needs a corporate proxy for pushes (see below). Every new terminal needs `$git` defined again.

## Tests and checks

```
py -3 -m pytest -q tests
py -3 -m compileall -q custom_components tools tests
```

Remove `__pycache__/` and `.pytest_cache/` afterwards (they are git-ignored but clutter the OneDrive folder).

| Test file | Covers |
|---|---|
| `tests/test_widgets.py` | classification with real URNs/datapoint types, binary-datapoint detection |
| `tests/test_backup.py` | password rule, filenames, pruning (`tmp_path`) |
| `tests/test_api.py` | classification of sample functions, live-data parsing |

Anything involving the config flow, scheduler, device/entity registries, services or HA backup hooks can only be verified in a real Home Assistant. Ask the user to test and to send the HA log (Settings → System → Logs → Download).

## Tools (run by hand on the user's machine, against a real controller)

```
py -3 tools\dump_controller.py <controller-ip>     # prompts for user and password
py -3 tools\probe_management.py <controller-ip>    # tests the management API, writes both backups
```

- `dump_controller.py` writes `wiser_dump_raw.json` (private) and `wiser_dump_anon.json`, then prints the classification summary using the integration's own `widgets.py`. It bypasses the corporate proxy for LAN access.
- `probe_management.py` writes `wiser_mgmt_probe.json` and `wiser_backup_*.bin` (all private, git-ignored).
- To re-classify an existing dump offline, load `tools/dump_controller.py` as a module and call `parse(raw)` (it stubs Home Assistant itself); run from the repo root.

## Manual test checklist (real HA + controller)

1. Add the integration: the "Controller backups" step appears; weak passwords are rejected; empty password skips backups.
2. With "create a backup right away" ticked, two ZIPs appear in `/config/wiser_backups/` and the **Last backup** sensor updates.
3. **Create backup** button and `wiser_for_knx.create_backup` service work; Configure shows the password/interval/keep options.
4. Lights and switches: control from HA, and from the Touch/wall switch (state updates within the polling interval); dimmers expose brightness.
5. A Home Assistant backup triggers a fresh controller backup; with the controller offline the HA backup still completes and a warning is logged.
6. Scheduled backups run at the configured interval and old files are pruned to "keep" per kind.
7. Restoring a ZIP in the Wiser web UI with the password (use a spare controller if possible; the integration itself never restores).

## Release process

1. Update code, `README.md` and, if needed, `AGENTS.md`/docs.
2. Bump `custom_components/wiser_for_knx/manifest.json` `version` (semver: features → minor, fixes → patch).
3. Run the checks above, commit with the Co-authored-by trailer, then `git tag -a vX.Y.Z -m vX.Y.Z`.
4. The user pushes from their own terminal (the agent cannot, because of the proxy and the browser sign-in):
   ```
   $git = "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"
   & $git -c http.proxy=http://127.0.0.1:9000 push
   & $git -c http.proxy=http://127.0.0.1:9000 push origin vX.Y.Z
   ```
5. Publish the GitHub release for the tag (no `gh` CLI is installed): open `https://github.com/bartosekpetr/HomelYnk-HA/releases/new?tag=vX.Y.Z` in the browser tools (the user must be signed in), fill title and description, click **Publish release**. Use a normal release, not a draft or pre-release, otherwise HACS will not offer the update.
6. In Home Assistant: HACS → Wiser for KNX → ⋮ → *Update information*, update, then **restart** Home Assistant.

HACS only offers updates when the tag, the published release and `manifest.json` version agree. If HACS installed from the `main` branch (shows a commit hash instead of a version), use ⋮ → *Redownload* and pick a release version.

## Conventions

- Minimal, surgical changes; comment only code that needs explanation.
- Entity unique ids: `wiser_for_knx_<entry_id>_<function_id>`; the backup sensor uses `..._last_backup`, and its suffix is how cleanup distinguishes it from stale sensors.
- Backup file names: `wiser_<host>_<system|project>_<YYYYMMDD_HHMMSS>.zip` in `<config>/wiser_backups/`.
- Options keys: `scan_interval`, `backup_password`, `backup_interval_hours` (0 = off, default 24), `backup_keep` (default 7).
