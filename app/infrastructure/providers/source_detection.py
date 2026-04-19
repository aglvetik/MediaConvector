from __future__ import annotations

import re

from app.domain.enums.platform import Platform
from app.infrastructure.providers.tiktok.url_utils import is_tiktok_host

URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def extract_candidate_urls(text: str) -> list[str]:
    matches = []
    for raw in URL_PATTERN.findall(text or ""):
        matches.append(raw.rstrip('".,!?;:])}>'))
    return matches


def detect_source_type(url: str) -> Platform | None:
    return Platform.TIKTOK if is_tiktok_host(url) else None


def extract_first_supported_url(text: str, source_type: Platform | None = None) -> str | None:
    for candidate in extract_candidate_urls(text):
        if source_type not in {None, Platform.TIKTOK}:
            return None
        if detect_source_type(candidate) == Platform.TIKTOK:
            return candidate
    return None


def contains_any_url(text: str) -> bool:
    return any(extract_candidate_urls(text))
