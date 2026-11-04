# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- TLS certificate verification is now enabled by default for new configuration entries. Controllers with a self-signed certificate are supported by confirming the certificate's SHA-256 fingerprint during setup. Existing entries keep their current setting; a repair notice explains how to switch verification on. Verification can be turned off per entry under Configure.
- New configuration entries now connect over HTTPS by default, including entries added through discovery. Plain HTTP is still available through *Use plain HTTP instead of HTTPS (insecure)* during setup and under Configure; while it is on, the controller username and password and the backup password are sent unencrypted, and Home Assistant shows a repair notice. Existing entries keep their current setting.
