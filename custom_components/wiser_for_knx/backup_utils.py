"""Pure helpers for controller backups (no Home Assistant imports)."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

_MIN_PASSWORD_LENGTH = 8


def is_valid_backup_password(password: str | None) -> bool:
    """Return True if the password meets the controller's backup password rule.

    At least 8 characters, with an uppercase letter, a lowercase letter and a digit.
    """
    if not password or len(password) < _MIN_PASSWORD_LENGTH:
        return False
    return (
        re.search(r"[A-Z]", password) is not None
        and re.search(r"[a-z]", password) is not None
        and re.search(r"\d", password) is not None
    )


def zip_entry_count(data: bytes) -> int:
    """Return the number of entries in a backup archive.

    The controller answers a backup request with the ZIP itself: no JSON, no
    `success` key, so the status code is not evidence that the body is an
    archive. Validate by parsing it. The entry count is the invariant worth
    reporting; the byte size drifts upwards as the trend data inside the
    archive grows, so it must never be used as a checksum.

    Raises ValueError if the blob is not a readable ZIP. Entries of a
    password-protected archive are listed without the password (only their
    contents are encrypted), so this never needs the backup password.
    """
    if not data:
        raise ValueError("the archive is empty")
    if not data.startswith(b"PK"):
        raise ValueError("the body does not start with the ZIP magic bytes")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return len(archive.infolist())
    except zipfile.BadZipFile as err:
        raise ValueError(f"the body is not a readable ZIP: {err}") from err


def safe_host(host: str) -> str:
    """Return the host made safe for use in a file name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", host)


def backup_filename(host: str, kind: str, when: datetime) -> str:
    """Return the file name for a backup of the given kind."""
    return f"wiser_{safe_host(host)}_{kind}_{when:%Y%m%d_%H%M%S}.zip"


def list_backups(directory: Path, host: str) -> list[Path]:
    """Return this controller's backup files, newest first."""
    if not directory.is_dir():
        return []
    prefix = f"wiser_{safe_host(host)}_"
    files = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.name.startswith(prefix) and p.suffix == ".zip"
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(
    directory: Path, host: str, kinds: list[str], keep: int
) -> list[Path]:
    """Delete all but the newest `keep` backups of each kind; return the deleted files."""
    removed: list[Path] = []
    if keep < 1:
        return removed
    for kind in kinds:
        marker = f"_{kind}_"
        of_kind = [p for p in list_backups(directory, host) if marker in p.name]
        for old in of_kind[keep:]:
            old.unlink(missing_ok=True)
            removed.append(old)
    return removed
