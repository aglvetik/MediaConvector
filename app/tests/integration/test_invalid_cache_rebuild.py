from app.application.services.process_message_service import IncomingMessage


async def test_invalid_audio_cache_rebuild(service_harness) -> None:
    text = "https://www.tiktok.com/@user/video/123456"
    first = IncomingMessage(chat_id=1, user_id=10, message_id=1, chat_type="private", text=text)
    second = IncomingMessage(chat_id=1, user_id=20, message_id=2, chat_type="private", text=text)

    await service_harness.process_message_service.handle_message(first)
    cache_entry = await service_harness.cache_service.get_entry("tiktok:video:123456")
    assert cache_entry is not None
    old_audio_file_id = cache_entry.audio_file_id
    service_harness.gateway.invalid_file_ids.add(old_audio_file_id)

    await service_harness.process_message_service.handle_message(second)

    refreshed = await service_harness.cache_service.get_entry("tiktok:video:123456")
    assert refreshed is not None
    assert refreshed.audio_file_id != old_audio_file_id
    assert service_harness.provider.download_calls["tiktok:video:123456"] == 2
