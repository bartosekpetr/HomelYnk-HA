"""Tests for controller backup helpers."""

import os
from datetime import datetime

from custom_components.wiser_for_knx.backup_utils import (
    backup_filename,
    is_valid_backup_password,
    list_backups,
    prune_backups,
    safe_host,
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
    name = backup_filename("192.168.0.104", "system", datetime(2026, 10, 14, 14, 39, 22))
    assert name == "wiser_192.168.0.104_system_20261014_143922.zip"
    assert "/" not in safe_host("../evil host")
    assert backup_filename("../evil", "project", datetime(2026, 1, 1)).startswith("wiser_.._evil_")


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
