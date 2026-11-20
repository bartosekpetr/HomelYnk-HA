# Changelog

All notable changes to this project are documented in this file.

## Unreleased

Brought in line with a new round of measurements on a real controller (written up in [wiser-knx-skillset](https://github.com/bartosekpetr/wiser-knx-skillset); the findings that matter here are summarised in [docs/controller-api.md](docs/controller-api.md)).

- A read of the controller's datapoint or function list is now retried up to three times with a growing delay when the controller answers an HTTP 5xx. The controller does this now and then while it recomputes which group objects to export, and a single unretried failure made every entity unavailable (or, at startup, looked like an empty installation). A failed poll is still never treated as "the installation is empty" and never removes entities.
- After about 30 seconds of the controller refusing to list its datapoints, the log explains the one known permanent cause: a Wiser Touch *Danfoss thermostat* (floor heating) widget whose *device status* object is configured makes that endpoint fail for as long as the widget exists. Nothing looks wrong in Home Assistant in that case, so it was previously undiagnosable.
- Values written to a datapoint that publishes a list of accepted values now use that list's own spelling (`on` is sent as `On` where that is what the controller published). The controller accepts any well-formed write with HTTP 202 and then silently discards a value it does not recognise, so these writes were being dropped without any error. A value that matches nothing is now logged instead of disappearing.
- A light or switch whose function has no datapoints yet is reported as unavailable instead of reading "off" and ignoring commands. The controller publishes a function up to a few minutes before its datapoints after a configuration change, so this is a normal, temporary state that recovers on a later poll.
- A light or switch no longer picks a measurement as its control datapoint. A socket's active power (`W`) or a dimmer's brightness (`%`) could be chosen instead of the switch, depending on the order the controller listed them, which made the entity read a wattage as its on/off state. The datapoint type now decides before the user-defined group object name in all cases.
- The README has a troubleshooting section for missing devices, entities that all become unavailable at once, and commands that appear to do nothing.
- A downloaded backup is now parsed as a ZIP archive before it is stored. The controller answers a backup request with the archive itself — no JSON, no status field — so an error page or an error document returned with HTTP 200 used to be saved as a `.zip` that could not be opened, and it counted as a successful backup. Such a response is now reported as a failure on the *Last backup* sensor and the previously stored backups are left untouched. The number of entries in the archive is written to the debug log; the file size is deliberately not checked, because the project backup keeps growing as the controller's trend data grows.
- Stored backup files are created with file mode `0600` (readable by Home Assistant only) instead of at the system default. They contain the whole controller configuration.
- A backup download that times out is now reported as a connection failure instead of raising an unhandled timeout.

## 0.7.0-beta.2 - 2026-11-05

- Optimistic datapoint state now uses the same value format as the request sent to the controller (`on`/`off` for booleans). No current control writes a boolean, so this does not change behaviour today; it keeps the local state and the write from diverging.
- The options flow now has a *Port* field, prefilled from the stored port and validated to 1–65535. Opening and saving options without changes leaves the entry as it was. Switching *Use plain HTTP* moves a port that was at the old default (443 or 80) to the new one (80 or 443); any other port is kept as entered. The options flow still makes no connection to the controller.
- `manifest.json` declares the integration category `hubs_protocols.building_automation`.
- The README install section covers the Home Assistant Marketplace (2026.11 and newer) and HACS (earlier versions), with an *Open in Marketplace* badge.
- The validation workflow also runs nightly and can be started manually.

## 0.7.0-beta.1 - 2026-11-05

- TLS certificate verification is now enabled by default for new configuration entries. Controllers with a self-signed certificate are supported by confirming the certificate's SHA-256 fingerprint during setup. Existing entries keep their current setting; a repair notice explains how to switch verification on. Verification can be turned off per entry under Configure.
- New configuration entries now connect over HTTPS by default, including entries added through discovery. Plain HTTP is still available through *Use plain HTTP instead of HTTPS (insecure)* during setup and under Configure; while it is on, the controller username and password and the backup password are sent unencrypted, and Home Assistant shows a repair notice. Existing entries keep their current setting.
- The controller is now polled for datapoints only. Locations and functions (names, rooms, which datapoint belongs to which function) are fetched once at setup and refreshed hourly, which cuts requests to the controller from three per poll to one. Names, rooms and function-to-datapoint mapping changed on the controller can take up to an hour to show up; the new *Rescan devices* button on the controller device refreshes them immediately, and a datapoint that refers to an unknown function triggers a refresh by itself. If refreshing keeps failing, the last known layout is used for up to three hours and then the integration reports the controller as unavailable. Entities for newly added functions still require reloading the integration, as before.
