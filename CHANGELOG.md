# Changelog

All notable changes to this project are documented in this file.

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
