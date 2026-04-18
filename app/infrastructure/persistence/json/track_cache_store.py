from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.domain.entities.track_cache_entry import TrackCacheEntry


class JsonTrackCacheStore:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._tracks_dir = cache_dir / "tracks"
        self._index_path = cache_dir / "track_cache.json"
        self._lock = asyncio.Lock()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._tracks_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, normalized_query: str) -> TrackCacheEntry | None:
        payload = await self._read_index()
        raw = payload.get(normalized_query)
        if not isinstance(raw, dict):
            return None
        return TrackCacheEntry(
            normalized_query=normalized_query,
            file_path=str(raw.get("file_path") or ""),
            title=str(raw.get("title") or ""),
            uploader=str(raw.get("uploader") or ""),
            source_url=str(raw.get("source_url") or ""),
        )

    async def set(self, entry: TrackCacheEntry) -> None:
        async with self._lock:
            payload = await self._read_index()
            payload[entry.normalized_query] = {
                "file_path": entry.file_path,
                "title": entry.title,
                "uploader": entry.uploader,
                "source_url": entry.source_url,
            }
            self._index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_target_path(self, normalized_query: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "_", normalized_query.casefold()).strip("_") or "track"
        return self._tracks_dir / f"{slug}.mp3"

    def resolve_cached_file(self, entry: TrackCacheEntry) -> Path:
        path = Path(entry.file_path)
        if path.is_absolute():
            return path
        return Path.cwd() / path

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    async def _read_index(self) -> dict[str, object]:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
