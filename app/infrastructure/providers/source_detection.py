from __future__ import annotations

import re
from urllib.parse import urlparse

from app.domain.enums.platform import Platform

URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

SOURCE_HOST_SUFFIXES: dict[Platform, tuple[str, ...]] = {
    Platform.TIKTOK: ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
    Platform.YOUTUBE: ("youtube.com", "youtu.be", "m.youtube.com", "www.youtube.com"),
    Platform.INSTAGRAM: ("instagram.com", "www.instagram.com"),
    Platform.FACEBOOK: ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"),
    Platform.PINTEREST: ("pinterest.com", "www.pinterest.com", "pin.it"),
    Platform.RUTUBE: ("rutube.ru", "www.rutube.ru"),
    Platform.LIKEE: ("likee.video", "www.likee.video"),
}


def extract_candidate_urls(text: str) -> list[str]:
    matches = []
    for raw in URL_PATTERN.findall(text or ""):
        matches.append(raw.rstrip('".,!?;:])}>'))
    return matches


def detect_source_type(url: str) -> Platform:
    host = (urlparse(url).hostname or "").lower()
    for source_type, suffixes in SOURCE_HOST_SUFFIXES.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return source_type
    return Platform.UNKNOWN


def extract_first_supported_url(text: str, source_type: Platform) -> str | None:
    for candidate in extract_candidate_urls(text):
        if detect_source_type(candidate) == source_type:
            return candidate
    return None


def contains_any_url(text: str) -> bool:
    return any(extract_candidate_urls(text))
