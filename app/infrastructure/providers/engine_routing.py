from __future__ import annotations

from urllib.parse import urlparse

from app.domain.enums.platform import Platform


def select_engine_name(platform: Platform, url: str) -> str:
    path = urlparse(url).path.lower()
    host = (urlparse(url).hostname or "").lower()

    if platform == Platform.TIKTOK:
        return "gallery-dl" if "/photo/" in path else "yt-dlp"
    if platform in {Platform.YOUTUBE, Platform.RUTUBE, Platform.LIKEE}:
        return "yt-dlp"
    if platform == Platform.PINTEREST:
        return "gallery-dl"
    if platform == Platform.INSTAGRAM:
        if any(marker in path for marker in ("/reel/", "/reels/", "/tv/")):
            return "yt-dlp"
        return "gallery-dl"
    if platform == Platform.FACEBOOK:
        if host == "fb.watch" or any(marker in path for marker in ("/watch", "/reel", "/videos")):
            return "yt-dlp"
        return "gallery-dl"
    return "yt-dlp"
