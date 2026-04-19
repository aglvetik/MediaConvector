from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse, urlunparse

TIKTOK_HOST_SUFFIXES = (
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
)

URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
VIDEO_ID_PATTERNS = [
    re.compile(r"/@[^/]+/video/(?P<video_id>\d+)", re.IGNORECASE),
    re.compile(r"/embed/v2/(?P<video_id>\d+)", re.IGNORECASE),
    re.compile(r"/video/(?P<video_id>\d+)", re.IGNORECASE),
]
PHOTO_ID_PATTERNS = [
    re.compile(r"/@[^/]+/photo/(?P<photo_id>\d+)", re.IGNORECASE),
    re.compile(r"/photo/(?P<photo_id>\d+)", re.IGNORECASE),
]


def extract_candidate_urls(text: str) -> list[str]:
    matches = []
    for raw in URL_PATTERN.findall(text or ""):
        cleaned = raw.rstrip('".,!?;:])}>')
        matches.append(cleaned)
    return matches


def is_tiktok_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in TIKTOK_HOST_SUFFIXES)


def extract_first_tiktok_url(text: str) -> str | None:
    for candidate in extract_candidate_urls(text):
        if is_tiktok_host(candidate):
            return candidate
    return None


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", "", ""))


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    for pattern in VIDEO_ID_PATTERNS:
        match = pattern.search(parsed.path)
        if match:
            return match.group("video_id")
    query = parse_qs(parsed.query)
    for key in ("item_id", "share_item_id"):
        values = query.get(key)
        if values:
            return values[0]
    return None


def extract_photo_id(url: str) -> str | None:
    parsed = urlparse(url)
    for pattern in PHOTO_ID_PATTERNS:
        match = pattern.search(parsed.path)
        if match:
            return match.group("photo_id")
    return None
