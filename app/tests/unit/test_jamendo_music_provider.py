from __future__ import annotations

import asyncio

from app.infrastructure.providers.music.jamendo_music_provider import JamendoMusicProvider


async def test_jamendo_search_parses_downloadable_tracks_only() -> None:
    provider = JamendoMusicProvider(
        client_id="jamendo-client",
        timeout_seconds=15,
        semaphore=asyncio.Semaphore(1),
    )

    async def fake_request_json(params):
        assert params["client_id"] == "jamendo-client"
        return {
            "headers": {"status": "success"},
            "results": [
                {
                    "id": "100",
                    "name": "After Dark",
                    "artist_name": "Test Artist",
                    "duration": 180,
                    "image": "https://img.example/100.jpg",
                    "shareurl": "https://www.jamendo.com/track/100",
                    "audiodownload_allowed": True,
                    "audiodownload": "https://cdn.jamendo.com/100.mp3",
                },
                {
                    "id": "200",
                    "name": "Blocked Track",
                    "artist_name": "Hidden Artist",
                    "audiodownload_allowed": False,
                    "audiodownload": "",
                },
            ],
        }

    provider._request_json = fake_request_json  # type: ignore[method-assign]

    candidates = await provider.resolve_candidates("after dark", max_candidates=3)

    assert len(candidates) == 1
    assert candidates[0].source_id == "100"
    assert candidates[0].title == "After Dark"
    assert candidates[0].performer == "Test Artist"
    assert candidates[0].source_url == "https://cdn.jamendo.com/100.mp3"
    assert candidates[0].source_name == "jamendo"


async def test_jamendo_skip_reason_requires_client_id() -> None:
    provider = JamendoMusicProvider(
        client_id=None,
        timeout_seconds=15,
        semaphore=asyncio.Semaphore(1),
    )

    assert await provider.skip_reason() == "provider_not_configured"
