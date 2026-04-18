from __future__ import annotations

import re

from app.domain.entities.music_track import MusicTrack

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def build_track_file_name(track: MusicTrack) -> str:
    performer = _clean_filename_part(track.performer)
    title = _clean_filename_part(track.title)
    if performer and title:
        return f"{performer} - {title}.mp3"
    if title:
        return f"{title}.mp3"
    if performer:
        return f"{performer}.mp3"
    return f"{track.source_id}.mp3"


def build_safe_file_stem(value: str, *, fallback: str) -> str:
    cleaned = _clean_filename_part(value)
    return cleaned or fallback


def _clean_filename_part(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", value)
    cleaned = " ".join(cleaned.split()).strip().strip(".")
    return cleaned[:120]
