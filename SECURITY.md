# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: **Security → Report a vulnerability** on
<https://github.com/bartosekpetr/HomelYnk-HA/security/advisories/new>.
Do not open a public issue. Never include controller passwords or backup contents in any report.

## Scope

This integration talks to a Schneider Wiser for KNX controller and can create password-protected
controller backups. In scope: credential handling, backup file creation/storage, unsafe handling of
controller responses, and the build/release pipeline.

## Supported versions

Only the latest release receives fixes.
