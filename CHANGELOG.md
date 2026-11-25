# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- **The lowest brightness on the slider no longer switches a dimmer off.** Home
  Assistant's minimum brightness is 1 of 255, which is 0.4 % and was being
  truncated to 0 % — and 0 % is off, so asking a dimmer for its faintest setting
  turned the light out instead. Any non-zero brightness now reaches the
  controller as at least 1 %.

## 0.8.0 - 2026-11-22

Everything the controller exports now becomes an entity. Built on measured
per-widget evidence — 47 widget types, each built three ways and read back over
the local API — recorded in a private research repository, so the findings this
project relies on are written up in `docs/controller-api.md` instead of linked.

- **Covers, thermostats, locks, binary sensors and readings are back, and there is more of them.**
  Shutters and blinds become `cover` entities with position and slat tilt; thermostats become
  `climate` with a setpoint, heating/cooling, the KNX operation mode as a preset and a fan mode
  where one exists; smart locks become `lock`; alarms, window and door contacts and motion
  detectors become `binary_sensor` with a matching device class; temperatures, humidity, CO2 and
  the other air-quality readings, illuminance, wind speed, a socket's active power and battery
  levels become `sensor`. Lights gained RGB and RGBW colour.
- **Nothing the controller publishes stays invisible.** Each device's remaining channels — its
  battery level and low-battery alert, its online/offline device status, a valve drive's heating
  demand, a shutter's "is moving" and last direction — become their own entities, and any other
  writable channel becomes a `select` (when the controller publishes a list of accepted values) or
  a `number`. KNX scenes become one button per scene number.
- **New devices appear without restarting Home Assistant.** The controller publishes a device a
  few seconds — and during heavy reconfiguration, minutes — before its channels, so entities are
  now added as soon as they show up instead of only when the integration starts.
- **Which channel is which is no longer guessed from its name.** Every datapoint carries a type
  archetype that identifies the Touch widget slot it came from, which is the only way to tell a
  shutter's height from its slats, a battery level from its low-battery alert, or a thermostat's
  on/off from its fan manual mode — each pair looks identical otherwise, and the names are
  whatever the installer typed. Among other things this means turning a thermostat off no longer
  risks stopping its fan instead.
- **The integration no longer deletes entities on startup.** Versions 0.5.0 to 0.7.x removed
  covers, thermostats, binary sensors and function sensors from the entity registry on every
  setup; those platforms exist again, so the sweep is gone. Upgrading restores your previous
  lights and switches unchanged. Sensors from before 0.5.0 are *not* re-adopted — they are keyed
  per channel now — so delete any that stay unavailable.
- **More of the controller itself is visible**: CPU load over 5 and 15 minutes (disabled by
  default), and how many functions and datapoints the controller is currently exporting — the
  only in-band signal that a widget stopped being exported.
- An SE 8000 thermostat's temperatures are corrected: that function type reports every temperature
  through a Fahrenheit-to-Celsius conversion while still labelling it Celsius.
- **Covers have a stop button**, and which value stops a shutter was measured rather than
  inferred: the controller publishes a shutter's stop object with the values `increase` and
  `decrease`, and `decrease` is the one that puts a 0 on the group object — the same value the
  controller's own Touch shutter widgets send from their stop button. The stop object is no longer
  a separate entity sitting next to the cover. What is still unverified is the *actuator*: an
  actuator wired to stop on 1 would move instead, and the README asks for a report. A stop object
  whose value list this project has never measured gets no stop button rather than a guess.
- Two more corrections that came out of the same session on a real controller: a shutter widget's
  *invert height* setting cannot change which way Home Assistant reads a position (it exports no
  channel at all, and the controller's own front end ignores it), and a device-status channel
  reports `online` for a clear bit, which is the opposite of what a KNX error object invites you
  to assume — the integration already had it that way, and it is now measured.
- The README now explains two things that were previously undiagnosable from Home Assistant: what
  to do when the integration asks you to confirm a changed controller certificate (submit the
  *Controller certificate changed* card — deleting and re-adding the entry also works but gives
  you a fresh set of entities and loses their history), and what it means when a newly configured
  Touch widget never appears (the controller's export daemon can stop regenerating the export
  while the API keeps answering normally; the two export-count sensors are the only in-band
  signal).

Also in this release, from the earlier round of measurements on a real controller (the findings that matter here are summarised in [docs/controller-api.md](docs/controller-api.md)):

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
