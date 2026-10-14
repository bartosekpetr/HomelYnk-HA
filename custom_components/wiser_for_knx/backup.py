"""Backup manager for Wiser for KNX controllers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import WiserKnxClient
from .backup_utils import backup_filename, is_valid_backup_password, list_backups, prune_backups
from .const import BACKUP_DIR, BACKUP_KINDS

_LOGGER = logging.getLogger(__name__)


class WiserKnxBackupManager:
    """Create, store and prune controller backups, optionally on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: WiserKnxClient,
        password: str | None,
        interval_hours: int,
        keep: int,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.client = client
        self.password = password
        self.interval_hours = interval_hours
        self.keep = keep
        self.last_backup: datetime | None = None
        self.last_error: str | None = None
        self.last_files: list[str] = []
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsub_timer: Callable[[], None] | None = None

    @property
    def directory(self) -> Path:
        """Return the backup directory inside the Home Assistant config folder."""
        return Path(self.hass.config.path(BACKUP_DIR))

    @property
    def configured(self) -> bool:
        """Return True if a valid backup password is configured."""
        return is_valid_backup_password(self.password)

    async def async_start(self) -> None:
        """Load the last backup time and start the schedule."""
        existing = await self.hass.async_add_executor_job(
            list_backups, self.directory, self.client.host
        )
        if existing:
            self.last_backup = dt_util.utc_from_timestamp(existing[0].stat().st_mtime)

        if self.interval_hours > 0 and self.configured:
            self._unsub_timer = async_track_time_interval(
                self.hass, self._scheduled_backup, timedelta(hours=self.interval_hours)
            )

    def async_stop(self) -> None:
        """Stop the schedule."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state listener and return a remover."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def _scheduled_backup(self, _now: datetime) -> None:
        try:
            await self.async_create_backup()
        except HomeAssistantError as err:
            _LOGGER.warning("Scheduled controller backup failed: %s", err)

    async def async_create_backup(self) -> list[Path]:
        """Download every backup kind and store the files; raise HomeAssistantError on failure."""
        if not self.configured:
            raise HomeAssistantError(
                "Set a backup password first: Settings > Devices & services > Wiser for KNX > "
                "Configure (gear icon). Use at least 8 characters with an uppercase letter, "
                "a lowercase letter and a digit"
            )

        async with self._lock:
            try:
                payloads = {
                    kind: await self.client.async_get_backup(path, self.password)
                    for kind, path in BACKUP_KINDS.items()
                }
                written = await self.hass.async_add_executor_job(self._store, payloads)
            except Exception as err:
                self.last_error = str(err)
                self._notify()
                raise HomeAssistantError(f"Controller backup failed: {err}") from err

            self.last_backup = dt_util.utcnow()
            self.last_error = None
            self.last_files = [p.name for p in written]
            self._notify()
            _LOGGER.info("Created controller backup: %s", ", ".join(self.last_files))
            return written

    def _store(self, payloads: dict[str, bytes]) -> list[Path]:
        """Write backups atomically and prune old ones (runs in the executor)."""
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        written: list[Path] = []
        for kind, data in payloads.items():
            if not data:
                raise HomeAssistantError(f"Controller returned an empty {kind} backup")
            target = directory / backup_filename(self.client.host, kind, now)
            temp = target.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(target)
            written.append(target)
        prune_backups(directory, self.client.host, list(BACKUP_KINDS), self.keep)
        return written
