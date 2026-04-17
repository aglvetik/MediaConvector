from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.infrastructure.logging import get_logger, log_event


class TempFileManager:
    def __init__(self, temp_root: Path, ttl_minutes: int) -> None:
        self._temp_root = temp_root
        self._ttl = timedelta(minutes=ttl_minutes)
        self._logger = get_logger(__name__)
        self._temp_root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._temp_root

    async def create_work_dir(self, request_id: str) -> Path:
        path = self._temp_root / request_id
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        return path

    async def remove_dir(self, path: Path) -> None:
        if not path.exists():
            return
        await asyncio.to_thread(shutil.rmtree, path, True)

    async def cleanup_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - self._ttl
        removed = 0
        for child in self._temp_root.iterdir():
            try:
                modified = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
            except FileNotFoundError:
                continue
            if modified < cutoff:
                if child.is_dir():
                    await asyncio.to_thread(shutil.rmtree, child, True)
                else:
                    await asyncio.to_thread(child.unlink, True)
                removed += 1
        log_event(self._logger, 20, "temp_cleanup_completed", removed_entries=removed, temp_root=str(self._temp_root))
        return removed

    async def directory_size_bytes(self) -> int:
        total = 0
        for path in self._temp_root.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total
