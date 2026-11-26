"""Tests for controller backup helpers."""

import io
import os
import stat
import zipfile
from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.wiser_for_knx.backup_utils import (
    backup_filename,
    is_valid_backup_password,
    list_backups,
    prune_backups,
    safe_host,
    zip_entry_count,
)


def test_password_rule():
    assert is_valid_backup_password("Abcdef12")
    assert is_valid_backup_password("Correct-Horse-9")
    assert not is_valid_backup_password("abcdefg1")  # no uppercase
    assert not is_valid_backup_password("ABCDEFG1")  # no lowercase
    assert not is_valid_backup_password("Abcdefgh")  # no digit
    assert not is_valid_backup_password("Ab1")  # too short
    assert not is_valid_backup_password("")
    assert not is_valid_backup_password(None)


def test_filename_is_safe_and_sortable():
    name = backup_filename("192.168.1.20", "system", datetime(2026, 10, 14, 14, 39, 22))
    assert name == "wiser_192.168.1.20_system_20261014_143922.zip"
    assert "/" not in safe_host("../evil host")
    assert backup_filename("../evil", "project", datetime(2026, 1, 1)).startswith(
        "wiser_.._evil_"
    )


def _touch(directory, name, mtime):
    path = directory / name
    path.write_bytes(b"PK")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_keeps_newest_per_kind_and_only_this_host(tmp_path):
    for i in range(4):
        _touch(tmp_path, f"wiser_1.2.3.4_system_{i}.zip", 1000 + i)
        _touch(tmp_path, f"wiser_1.2.3.4_project_{i}.zip", 1000 + i)
    other = _touch(tmp_path, "wiser_9.9.9.9_system_0.zip", 1)
    note = _touch(tmp_path, "notes.txt", 1)

    removed = prune_backups(tmp_path, "1.2.3.4", ["system", "project"], keep=2)

    assert len(removed) == 4
    remaining = sorted(p.name for p in list_backups(tmp_path, "1.2.3.4"))
    assert remaining == [
        "wiser_1.2.3.4_project_2.zip",
        "wiser_1.2.3.4_project_3.zip",
        "wiser_1.2.3.4_system_2.zip",
        "wiser_1.2.3.4_system_3.zip",
    ]
    assert other.exists() and note.exists()


def test_list_backups_missing_directory(tmp_path):
    assert list_backups(tmp_path / "missing", "1.2.3.4") == []


def _zip_blob(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return buffer.getvalue()


def test_zip_entry_count_counts_entries():
    assert zip_entry_count(_zip_blob(["a.db", "dir/b.lua", "c.json"])) == 3
    # An archive with no entries is still a valid ZIP.
    assert zip_entry_count(_zip_blob([])) == 0


def _store_manager(tmp_path, host="1.2.3.4", keep=7):
    """Return something `WiserKnxBackupManager._store` can run against."""
    from custom_components.wiser_for_knx.backup import WiserKnxBackupManager

    manager = SimpleNamespace(
        directory=tmp_path,
        client=SimpleNamespace(host=host),
        keep=keep,
    )
    return lambda payloads: WiserKnxBackupManager._store(manager, payloads)


def test_store_writes_validated_archives_private(tmp_path):
    store = _store_manager(tmp_path)

    written = store({"system": _zip_blob(["a"]), "project": _zip_blob(["b", "c"])})

    assert len(written) == 2
    for path in written:
        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_store_refuses_a_body_that_is_not_an_archive(tmp_path):
    from homeassistant.exceptions import HomeAssistantError

    existing = _touch(tmp_path, "wiser_1.2.3.4_system_0.zip", 1000)
    store = _store_manager(tmp_path)

    with pytest.raises(HomeAssistantError):
        store({"system": b'{"error": "not a backup"}'})

    # Nothing new stored, nothing half-written, earlier backups untouched.
    assert existing.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [existing.name]


def test_zip_entry_count_rejects_anything_that_is_not_an_archive():
    # A JSON error body or an HTML login page answered with HTTP 200 must not
    # be stored as a backup.
    for blob in (
        b"",
        b'{"error": "unauthorized"}',
        b"<html><body>Login</body></html>",
        b"PK\x03\x04 truncated",
    ):
        with pytest.raises(ValueError):
            zip_entry_count(blob)
