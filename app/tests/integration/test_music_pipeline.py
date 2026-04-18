from app.application.services.process_message_service import IncomingMessage
from app.domain.entities.music_track import MusicTrack


async def test_music_audio_cache_reuse(service_harness) -> None:
    query = "\u043d\u0430\u0439\u0442\u0438 after dark"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=501, message_id=1, chat_type="private", text=query)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=601, message_id=2, chat_type="private", text=query)
    )
    assert service_harness.remote_downloader.download_calls["after_dark"] == 1


async def test_music_invalid_cached_file_id_rebuild(service_harness) -> None:
    query = "\u043d\u0430\u0439\u0442\u0438 after dark"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=502, message_id=3, chat_type="private", text=query)
    )
    cache_entry = await service_harness.cache_service.get_entry("music:ytm:after dark")
    assert cache_entry is not None
    old_file_id = cache_entry.audio_file_id
    service_harness.gateway.invalid_file_ids.add(old_file_id)

    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=602, message_id=4, chat_type="private", text=query)
    )
    refreshed = await service_harness.cache_service.get_entry("music:ytm:after dark")
    assert refreshed is not None
    assert refreshed.audio_file_id != old_file_id
    assert service_harness.remote_downloader.download_calls["after_dark"] == 2


async def test_music_thumbnail_is_optional(service_harness) -> None:
    service_harness.audio_downloader.fail_thumbnail_ids.add("after_dark")
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=503, message_id=5, chat_type="private", text="\u043d\u0430\u0439\u0442\u0438 after dark")
    )
    assert service_harness.gateway.audio_sends[-1].has_thumbnail is False


async def test_music_audio_send_metadata_and_filename(service_harness) -> None:
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=504, message_id=6, chat_type="private", text="\u043d\u0430\u0439\u0442\u0438 after dark")
    )
    audio_send = service_harness.gateway.audio_sends[-1]
    assert audio_send.title == "After Dark"
    assert audio_send.performer == "Test Artist"
    assert audio_send.file_name == "Test Artist - After Dark.mp3"


async def test_music_strategy_fallback_uses_youtube_direct_when_remote_provider_fails(service_harness) -> None:
    query = "\u043d\u0430\u0439\u0442\u0438 fallback anthem"
    service_harness.remote_downloader.fail_download_ids.add("fallback_anthem")

    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=505, message_id=7, chat_type="private", text=query)
    )

    assert service_harness.remote_downloader.download_attempts == ["fallback_anthem"]
    assert service_harness.audio_downloader.download_attempts == [("fallback_anthem", True)]
    assert service_harness.gateway.audio_sends[-1].title == "Fallback Anthem"
    cache_entry = await service_harness.cache_service.get_entry("music:ytm:fallback anthem")
    assert cache_entry is not None
    assert cache_entry.acquisition_backend == "youtube_cookies"


async def test_music_pipeline_tries_next_candidate_when_first_candidate_fails(service_harness) -> None:
    query = "\u043d\u0430\u0439\u0442\u0438 complex fallback"
    service_harness.music_provider.results["complex fallback"] = [
        MusicTrack(
            source_id="first_candidate",
            source_url="https://www.youtube.com/watch?v=first_candidate",
            canonical_url="https://music.youtube.com/watch?v=first_candidate",
            title="First Candidate",
            performer="Artist",
            duration_sec=180,
            thumbnail_url=None,
            resolver_name="fake_provider",
            source_name="youtube",
            ranking=1,
        ),
        MusicTrack(
            source_id="second_candidate",
            source_url="https://www.youtube.com/watch?v=second_candidate",
            canonical_url="https://music.youtube.com/watch?v=second_candidate",
            title="Second Candidate",
            performer="Artist",
            duration_sec=180,
            thumbnail_url=None,
            resolver_name="fake_provider",
            source_name="youtube",
            ranking=2,
        ),
    ]
    service_harness.remote_downloader.fail_download_ids.add("first_candidate")
    service_harness.audio_downloader.fail_download_ids.add("first_candidate")

    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=506, message_id=8, chat_type="private", text=query)
    )

    assert service_harness.gateway.audio_sends[-1].title == "Second Candidate"
    assert service_harness.remote_downloader.download_attempts == ["first_candidate", "second_candidate"]


async def test_music_cache_persists_primary_acquisition_backend(service_harness) -> None:
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=507, message_id=9, chat_type="private", text="\u043d\u0430\u0439\u0442\u0438 after dark")
    )

    cache_entry = await service_harness.cache_service.get_entry("music:ytm:after dark")
    assert cache_entry is not None
    assert cache_entry.acquisition_backend == "remote_http"
