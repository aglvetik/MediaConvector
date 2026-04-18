from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.entities.music_source_state import MusicSourceState


class MusicCookieProvider(Protocol):
    source_name: str

    async def get_cookie_file(self) -> Path | None:
        ...

    async def mark_success(self) -> None:
        ...

    async def mark_failure(self, error_code: str, *, error_message: str | None = None) -> None:
        ...

    async def current_state(self) -> MusicSourceState:
        ...
