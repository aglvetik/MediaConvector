from app.application.services.process_message_service import IncomingMessage


async def test_music_audio_cache_reuse(service_harness) -> None:
    query = "найти after dark"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=501, message_id=1, chat_type="private", text=query)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=601, message_id=2, chat_type="private", text=query)
    )
    assert service_harness.audio_downloader.download_calls["after_dark"] == 1


async def test_music_invalid_cached_file_id_rebuild(service_harness) -> None:
    query = "найти after dark"
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
    assert service_harness.audio_downloader.download_calls["after_dark"] == 2


async def test_music_thumbnail_is_optional(service_harness) -> None:
    service_harness.audio_downloader.fail_thumbnail_ids.add("after_dark")
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=503, message_id=5, chat_type="private", text="найти after dark")
    )
    assert service_harness.gateway.audio_sends[-1].has_thumbnail is False


async def test_music_audio_send_metadata_and_filename(service_harness) -> None:
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=504, message_id=6, chat_type="private", text="найти after dark")
    )
    audio_send = service_harness.gateway.audio_sends[-1]
    assert audio_send.title == "After Dark"
    assert audio_send.performer == "Test Artist"
    assert audio_send.file_name == "Test Artist - After Dark.mp3"
