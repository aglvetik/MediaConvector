from __future__ import annotations

import asyncio

from app.infrastructure.providers.music.internet_archive_music_provider import InternetArchiveMusicProvider


async def test_internet_archive_search_parses_downloadable_audio_items() -> None:
    provider = InternetArchiveMusicProvider(
        timeout_seconds=20,
        semaphore=asyncio.Semaphore(1),
    )

    async def fake_request_json(url: str, *, params=None):
        if "advancedsearch.php" in url:
            return {
                "response": {
                    "docs": [
                        {
                            "identifier": "archive-item",
                            "title": "Archive Song",
                            "creator": "Archive Artist",
                        }
                    ]
                }
            }
        return {
            "metadata": {
                "title": "Archive Song",
                "creator": "Archive Artist",
            },
            "files": [
                {
                    "name": "cover.jpg",
                    "format": "JPEG",
                    "source": "original",
                },
                {
                    "name": "archive-song.mp3",
                    "format": "VBR MP3",
                    "source": "original",
                    "length": "03:12",
                },
            ],
        }

    provider._request_json = fake_request_json  # type: ignore[method-assign]

    candidates = await provider.resolve_candidates("archive song", max_candidates=2)

    assert len(candidates) == 1
    assert candidates[0].source_id == "archive-item"
    assert candidates[0].title == "Archive Song"
    assert candidates[0].performer == "Archive Artist"
    assert candidates[0].duration_sec == 192
    assert candidates[0].source_url.endswith("/archive-song.mp3")
    assert candidates[0].canonical_url == "https://archive.org/details/archive-item"
    assert candidates[0].source_name == "internet_archive"


async def test_internet_archive_search_skips_items_without_audio_files() -> None:
    provider = InternetArchiveMusicProvider(
        timeout_seconds=20,
        semaphore=asyncio.Semaphore(1),
    )

    async def fake_request_json(url: str, *, params=None):
        if "advancedsearch.php" in url:
            return {
                "response": {
                    "docs": [
                        {
                            "identifier": "archive-item",
                            "title": "Archive Song",
                            "creator": "Archive Artist",
                        }
                    ]
                }
            }
        return {
            "metadata": {
                "title": "Archive Song",
                "creator": "Archive Artist",
            },
            "files": [
                {
                    "name": "cover.jpg",
                    "format": "JPEG",
                    "source": "original",
                }
            ],
        }

    provider._request_json = fake_request_json  # type: ignore[method-assign]

    candidates = await provider.resolve_candidates("archive song", max_candidates=2)

    assert candidates == []
