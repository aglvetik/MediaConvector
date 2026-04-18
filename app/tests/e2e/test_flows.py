import asyncio

from app import messages
from app.application.services.process_message_service import IncomingMessage


async def test_private_chat_success_flow(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=100,
            message_id=1,
            chat_type="private",
            text="https://www.tiktok.com/@user/video/111",
        )
    )
    assert handled is True
    assert len(service_harness.gateway.sent_video_receipts) == 1
    assert len(service_harness.gateway.sent_audio_receipts) == 1
    assert len(service_harness.gateway.deleted_messages) == 1


async def test_group_chat_success_flow(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=-100,
            user_id=200,
            message_id=2,
            chat_type="group",
            text="https://www.tiktok.com/@user/video/222",
        )
    )
    assert handled is True
    assert len(service_harness.gateway.sent_video_receipts) == 1
    assert len(service_harness.gateway.sent_audio_receipts) == 1


async def test_cache_miss_flow(service_harness) -> None:
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=3, chat_type="private", text="https://www.tiktok.com/@user/video/333")
    )
    assert service_harness.provider.download_calls["tiktok:video:333"] == 1


async def test_cache_hit_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/444"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=4, chat_type="private", text=url)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=202, message_id=5, chat_type="private", text=url)
    )
    assert service_harness.provider.download_calls["tiktok:video:444"] == 1
    assert len(service_harness.gateway.sent_video_receipts) == 2


async def test_repeated_same_url_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/555"
    first = IncomingMessage(chat_id=1, user_id=101, message_id=6, chat_type="private", text=url)
    duplicate = IncomingMessage(chat_id=1, user_id=101, message_id=6, chat_type="private", text=url)
    await service_harness.process_message_service.handle_message(first)
    handled = await service_harness.process_message_service.handle_message(duplicate)
    assert handled is True
    assert service_harness.provider.download_calls["tiktok:video:555"] == 1
    assert len(service_harness.gateway.sent_video_receipts) == 1


async def test_parallel_same_url_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/666"
    await asyncio.gather(
        service_harness.process_message_service.handle_message(
            IncomingMessage(chat_id=1, user_id=101, message_id=7, chat_type="private", text=url)
        ),
        service_harness.process_message_service.handle_message(
            IncomingMessage(chat_id=2, user_id=102, message_id=8, chat_type="private", text=url)
        ),
    )
    assert service_harness.provider.download_calls["tiktok:video:666"] == 1
    assert len(service_harness.gateway.sent_video_receipts) == 2


async def test_invalid_url_flow(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=9, chat_type="private", text="hello world")
    )
    assert handled is False


async def test_no_audio_track_flow(service_harness) -> None:
    normalized_key = "tiktok:video:777"
    service_harness.provider.has_audio[normalized_key] = False
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=10, chat_type="private", text="https://www.tiktok.com/@user/video/777")
    )
    assert len(service_harness.gateway.sent_audio_receipts) == 0
    assert service_harness.gateway.text_messages[-1].text == messages.NO_AUDIO_TRACK


async def test_too_large_file_flow(service_harness) -> None:
    service_harness.gateway.max_file_size_bytes = 1
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=11, chat_type="private", text="https://www.tiktok.com/@user/video/888")
    )
    assert service_harness.gateway.text_messages[-1].text == messages.FILE_TOO_LARGE


async def test_invalid_cached_video_file_id_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/999"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=12, chat_type="private", text=url)
    )
    cache_entry = await service_harness.cache_service.get_entry("tiktok:video:999")
    assert cache_entry is not None
    service_harness.gateway.invalid_file_ids.add(cache_entry.video_file_id)
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=202, message_id=13, chat_type="private", text=url)
    )
    assert service_harness.provider.download_calls["tiktok:video:999"] == 2


async def test_audio_extraction_failure_recovers_on_next_cached_request(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/1001"
    normalized_key = "tiktok:video:1001"
    service_harness.ffmpeg.fail_keys.add(normalized_key)

    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=14, chat_type="private", text=url)
    )
    first_cache_entry = await service_harness.cache_service.get_entry(normalized_key)
    assert first_cache_entry is not None
    assert first_cache_entry.has_audio is True
    assert first_cache_entry.audio_file_id is None
    assert service_harness.gateway.text_messages[-1].text == messages.AUDIO_EXTRACTION_FAILED

    service_harness.ffmpeg.fail_keys.clear()
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=202, message_id=15, chat_type="private", text=url)
    )
    refreshed_cache_entry = await service_harness.cache_service.get_entry(normalized_key)
    assert refreshed_cache_entry is not None
    assert refreshed_cache_entry.audio_file_id is not None
    assert service_harness.provider.download_calls[normalized_key] == 2
    assert len(service_harness.gateway.sent_audio_receipts) == 1
