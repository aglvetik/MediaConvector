import asyncio

from app import messages
from app.application.services.process_message_service import IncomingMessage
from app.domain.enums.platform import Platform


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


async def test_plain_music_trigger_like_text_is_ignored(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=102, message_id=10, chat_type="private", text="найти faint")
    )
    assert handled is False
    assert service_harness.gateway.text_messages == []


async def test_no_audio_track_flow(service_harness) -> None:
    normalized_key = "tiktok:video:777"
    service_harness.provider.has_audio[normalized_key] = False
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=11, chat_type="private", text="https://www.tiktok.com/@user/video/777")
    )
    assert len(service_harness.gateway.sent_audio_receipts) == 0
    assert service_harness.gateway.text_messages[-1].text == messages.NO_AUDIO_TRACK


async def test_too_large_file_flow(service_harness) -> None:
    service_harness.gateway.max_file_size_bytes = 1
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=12, chat_type="private", text="https://www.tiktok.com/@user/video/888")
    )
    assert service_harness.gateway.text_messages[-1].text == messages.FILE_TOO_LARGE


async def test_invalid_cached_video_file_id_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/999"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=13, chat_type="private", text=url)
    )
    cache_entry = await service_harness.cache_service.get_entry("tiktok:video:999")
    assert cache_entry is not None
    service_harness.gateway.invalid_file_ids.add(cache_entry.video_file_id)
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=202, message_id=14, chat_type="private", text=url)
    )
    assert service_harness.provider.download_calls["tiktok:video:999"] == 2


async def test_audio_extraction_failure_recovers_on_next_cached_request(service_harness) -> None:
    url = "https://www.tiktok.com/@user/video/1001"
    normalized_key = "tiktok:video:1001"
    service_harness.ffmpeg.fail_keys.add(normalized_key)

    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=101, message_id=15, chat_type="private", text=url)
    )
    first_cache_entry = await service_harness.cache_service.get_entry(normalized_key)
    assert first_cache_entry is not None
    assert first_cache_entry.has_audio is True
    assert first_cache_entry.audio_file_id is None
    assert service_harness.gateway.text_messages[-1].text == messages.AUDIO_EXTRACTION_FAILED

    service_harness.ffmpeg.fail_keys.clear()
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=202, message_id=16, chat_type="private", text=url)
    )
    refreshed_cache_entry = await service_harness.cache_service.get_entry(normalized_key)
    assert refreshed_cache_entry is not None
    assert refreshed_cache_entry.audio_file_id is not None
    assert service_harness.provider.download_calls[normalized_key] == 2
    assert len(service_harness.gateway.sent_audio_receipts) == 1


async def test_tiktok_photo_post_flow(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=301,
            message_id=17,
            chat_type="private",
            text="https://www.tiktok.com/@user/photo/12345",
        )
    )
    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 3
    assert len(service_harness.gateway.sent_audio_receipts) == 1


async def test_tiktok_photo_post_download_first_gallery_flow(service_harness) -> None:
    normalized_key = "tiktok:photo_post:777700"
    service_harness.provider.download_first_gallery_keys.add(normalized_key)
    service_harness.provider.photo_counts[normalized_key] = 3

    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=399,
            message_id=170,
            chat_type="private",
            text="https://www.tiktok.com/@user/photo/777700",
        )
    )

    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 3
    assert service_harness.provider.image_download_calls[normalized_key] == 1


async def test_tiktok_photo_group_falls_back_to_sequential_photos(service_harness) -> None:
    service_harness.gateway.fail_photo_group_upload = True
    await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=302,
            message_id=18,
            chat_type="private",
            text="https://www.tiktok.com/@user/photo/54321",
        )
    )
    assert len(service_harness.gateway.sent_photo_receipts) == 3
    assert len(service_harness.gateway.sent_audio_receipts) == 1


async def test_tiktok_photo_post_cache_hit_flow(service_harness) -> None:
    url = "https://www.tiktok.com/@user/photo/123450"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=305, message_id=19, chat_type="private", text=url)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=2, user_id=306, message_id=20, chat_type="private", text=url)
    )
    assert service_harness.provider.image_download_calls["tiktok:photo_post:123450"] == 1
    assert len(service_harness.gateway.sent_photo_receipts) == 6


async def test_tiktok_music_only_flow(service_harness) -> None:
    url = "https://www.tiktok.com/music/original-sound-777777"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=303, message_id=21, chat_type="private", text=url)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=2, user_id=304, message_id=22, chat_type="private", text=url)
    )
    assert len(service_harness.gateway.sent_video_receipts) == 0
    assert len(service_harness.gateway.sent_audio_receipts) == 2
    assert service_harness.provider.audio_download_calls["tiktok:music_only:777777"] == 1


async def test_unsupported_url_flow_returns_user_message(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=401, message_id=23, chat_type="private", text="https://example.com/resource")
    )
    assert handled is True
    assert service_harness.gateway.text_messages[-1].text == messages.INVALID_TIKTOK_LINK


async def test_youtube_video_url_flow(service_harness) -> None:
    url = "https://youtu.be/video-123"
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=402, message_id=24, chat_type="private", text=url)
    )
    assert handled is True
    assert len(service_harness.gateway.sent_video_receipts) == 1
    assert len(service_harness.gateway.sent_audio_receipts) == 1
    assert service_harness.generic_providers[Platform.YOUTUBE].download_calls["youtube:video:video-123"] == 1


async def test_youtube_video_cache_hit_flow(service_harness) -> None:
    url = "https://youtu.be/video-cache-1"
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=403, message_id=25, chat_type="private", text=url)
    )
    await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=2, user_id=404, message_id=26, chat_type="private", text=url)
    )
    assert service_harness.generic_providers[Platform.YOUTUBE].download_calls["youtube:video:video-cache-1"] == 1
    assert len(service_harness.gateway.sent_video_receipts) == 2


async def test_instagram_gallery_flow_sends_photos_without_no_audio_notice(service_harness) -> None:
    url = "https://www.instagram.com/p/gallery-123/"
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=405, message_id=27, chat_type="private", text=url)
    )
    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 3
    assert len(service_harness.gateway.sent_audio_receipts) == 0
    assert service_harness.gateway.text_messages == []
    assert service_harness.generic_providers[Platform.INSTAGRAM].image_download_calls["instagram:photo_post:gallery-123"] == 1


async def test_gallery_with_one_broken_entry_still_sends_remaining_images(service_harness) -> None:
    normalized_key = "instagram:photo_post:gallery-broken-1"
    service_harness.generic_providers[Platform.INSTAGRAM].broken_image_entries[normalized_key].add(2)

    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=409,
            message_id=31,
            chat_type="private",
            text="https://www.instagram.com/p/gallery-broken-1/",
        )
    )

    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 2
    assert service_harness.gateway.text_messages == []


async def test_gallery_with_all_broken_entries_fails_cleanly(service_harness) -> None:
    normalized_key = "facebook:photo_post:gallery-all-broken"
    service_harness.generic_providers[Platform.FACEBOOK].broken_image_entries[normalized_key].update({1, 2, 3})

    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=410,
            message_id=32,
            chat_type="private",
            text="https://www.facebook.com/gallery-all-broken",
        )
    )

    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 0
    assert service_harness.gateway.text_messages[-1].text == messages.VIDEO_UNAVAILABLE


async def test_visual_post_with_optional_audio_failure_still_sends_images(service_harness) -> None:
    normalized_key = "instagram:photo_post:gallery-with-audio-777"
    service_harness.generic_providers[Platform.INSTAGRAM].audio_fail_keys.add(normalized_key)

    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=411,
            message_id=33,
            chat_type="private",
            text="https://www.instagram.com/p/gallery-with-audio-777/",
        )
    )

    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 3
    assert len(service_harness.gateway.sent_audio_receipts) == 0
    assert service_harness.gateway.text_messages[-1].text == messages.SEPARATE_AUDIO_SEND_FAILED


async def test_single_photo_source_sends_single_photo(service_harness) -> None:
    url = "https://www.pinterest.com/pin/single-42/"
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=406, message_id=28, chat_type="private", text=url)
    )
    assert handled is True
    assert len(service_harness.gateway.sent_photo_receipts) == 1
    assert len(service_harness.gateway.sent_audio_receipts) == 0
    assert service_harness.gateway.text_messages == []


async def test_download_first_gallery_images_are_converted_to_jpg_before_delivery(service_harness) -> None:
    normalized_key = "pinterest:photo_post:single-webp-42"
    provider = service_harness.generic_providers[Platform.PINTEREST]
    provider.download_first_gallery_keys.add(normalized_key)
    provider.photo_counts[normalized_key] = 1
    provider.photo_extensions[normalized_key] = ("webp",)

    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=4060, message_id=281, chat_type="private", text="https://www.pinterest.com/pin/single-webp-42/")
    )

    assert handled is True
    assert len(service_harness.gateway.sent_photo_paths) == 1
    assert service_harness.gateway.sent_photo_paths[0].suffix.lower() == ".jpg"


async def test_audio_only_source_flow(service_harness) -> None:
    url = "https://likee.video/@user/audio/audio-555"
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(chat_id=1, user_id=407, message_id=29, chat_type="private", text=url)
    )
    assert handled is True
    assert len(service_harness.gateway.sent_video_receipts) == 0
    assert len(service_harness.gateway.sent_audio_receipts) == 1
    assert service_harness.generic_providers[Platform.LIKEE].audio_download_calls["likee:music_only:audio-555"] == 1


async def test_audio_delivery_includes_metadata_and_human_readable_filename(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=4070,
            message_id=290,
            chat_type="private",
            text="https://www.tiktok.com/@user/video/123456",
        )
    )

    assert handled is True
    audio_request = service_harness.gateway.sent_audio_requests[-1]
    assert audio_request.title == "video"
    assert audio_request.performer == "author"
    assert audio_request.duration == 10
    assert audio_request.filename is not None
    assert audio_request.filename.endswith(".mp3")
    assert "video" in audio_request.filename.lower()


async def test_supported_url_later_in_message_is_processed(service_harness) -> None:
    handled = await service_harness.process_message_service.handle_message(
        IncomingMessage(
            chat_id=1,
            user_id=408,
            message_id=30,
            chat_type="private",
            text="bad https://example.com/thing and then https://youtu.be/multi-999",
        )
    )
    assert handled is True
    assert service_harness.generic_providers[Platform.YOUTUBE].download_calls["youtube:video:multi-999"] == 1
