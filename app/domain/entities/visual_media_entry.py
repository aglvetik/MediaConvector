from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class VisualMediaEntry:
    source_url: str
    order: int
    mime_type_hint: str | None = None
    local_path: Path | None = None
