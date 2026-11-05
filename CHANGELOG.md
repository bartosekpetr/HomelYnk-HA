# Changelog

All notable changes to this project are documented in this file.

## 0.7.0-beta.1 - 2026-11-05

- TLS certificate verification is now enabled by default for new configuration entries. Controllers with a self-signed certificate are supported by confirming the certificate's SHA-256 fingerprint during setup. Existing entries keep their current setting; a repair notice explains how to switch verification on. Verification can be turned off per entry under Configure.
- New configuration entries now connect over HTTPS by default, including entries added through discovery. Plain HTTP is still available through *Use plain HTTP instead of HTTPS (insecure)* during setup and under Configure; while it is on, the controller username and password and the backup password are sent unencrypted, and Home Assistant shows a repair notice. Existing entries keep their current setting.
- The controller is now polled for datapoints only. Locations and functions (names, rooms, which datapoint belongs to which function) are fetched once at setup and refreshed hourly, which cuts requests to the controller from three per poll to one. Names, rooms and function-to-datapoint mapping changed on the controller can take up to an hour to show up; the new *Rescan devices* button on the controller device refreshes them immediately, and a datapoint that refers to an unknown function triggers a refresh by itself. If refreshing keeps failing, the last known layout is used for up to three hours and then the integration reports the controller as unavailable. Entities for newly added functions still require reloading the integration, as before.
