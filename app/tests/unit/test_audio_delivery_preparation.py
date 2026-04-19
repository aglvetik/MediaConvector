from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform


def _build_music_request() -> MediaRequest:
    return MediaRequest(
        request_id="req-audio",
        chat_id=1,
        user_id=10,
        message_id=100,
        chat_type="private",
        message_text="https://www.tiktok.com/music/original-sound-123456",
        normalized_resource=NormalizedResource(
            platform=Platform.TIKTOK,
            resource_type="music_only",
            resource_id="123456",
            normalized_key="tiktok:music_only:123456",
            original_url="https://www.tiktok.com/music/original-sound-123456",
            canonical_url="https://www.tiktok.com/music/original-sound-123456",
            media_kind="audio",
            title="Original sound",
            author="Creator",
            duration_sec=15,
        ),
    )


@pytest.mark.asyncio
async def test_tiktok_music_fallback_m4a_is_prepared_as_real_mp3(service_harness, tmp_path: Path) -> None:
    request = _build_music_request()
    source_path = tmp_path / "fallback-source.m4a"
    source_path.write_bytes(b"m4a-bytes")

    asset = await service_harness.media_pipeline_service._build_audio_delivery_asset(  # type: ignore[attr-defined]
        request=request,
        metadata=MediaMetadata(
            title="Original sound",
            duration_sec=15,
            author="Creator",
            description=None,
            size_bytes=123,
            has_audio=True,
        ),
        source_path=source_path,
        work_dir=tmp_path,
    )

    assert asset.final_audio_path.suffix.lower() == ".mp3"
    assert asset.telegram_filename.endswith(".mp3")
    assert asset.container_extension == "mp3"
    assert asset.final_audio_path.exists()
    assert service_harness.ffmpeg.calls["transcode:tiktok:music_only:123456"] == 1


@pytest.mark.asyncio
async def test_tiktok_music_fallback_can_keep_consistent_m4a_when_conversion_disabled(service_harness, tmp_path: Path) -> None:
    request = _build_music_request()
    source_path = tmp_path / "fallback-source.m4a"
    source_path.write_bytes(b"m4a-bytes")

    asset = await service_harness.media_pipeline_service._build_audio_delivery_asset(  # type: ignore[attr-defined]
        request=request,
        metadata=MediaMetadata(
            title="Original sound",
            duration_sec=15,
            author="Creator",
            description=None,
            size_bytes=123,
            has_audio=True,
        ),
        source_path=source_path,
        work_dir=tmp_path,
        preferred_container="source",
    )

    assert asset.final_audio_path.suffix.lower() == ".m4a"
    assert asset.telegram_filename.endswith(".m4a")
    assert asset.container_extension == "m4a"
    assert service_harness.ffmpeg.calls.get("transcode:tiktok:music_only:123456", 0) == 0


@pytest.mark.asyncio
async def test_audio_delivery_failure_logging_includes_exception_and_file_context(service_harness, tmp_path: Path, monkeypatch) -> None:
    request = _build_music_request()
    audio_path = tmp_path / "prepared.mp3"
    audio_path.write_bytes(b"mp3-bytes")
    service_harness.gateway.fail_audio_upload = True
    events: list[tuple[str, dict[str, object]]] = []

    def fake_log_event(logger, level, event_name, **fields) -> None:
        del logger, level
        events.append((event_name, fields))

    monkeypatch.setattr("app.application.services.delivery_service.log_event", fake_log_event)

    result = await service_harness.delivery_service.deliver_audio_only(
        request,
        audio_path,
        title="Original sound",
        performer="Creator",
        duration_sec=15,
        filename="Creator - Original sound.mp3",
    )

    assert result.audio_receipt is None
    failure_events = [fields for event_name, fields in events if event_name == "telegram_send_audio_failed"]
    assert len(failure_events) == 1
    failure = failure_events[0]
    assert failure["exception_type"] == "TelegramDeliveryError"
    assert failure["exception_message"] == "audio upload failed"
    assert failure["audio_file_path"] == str(audio_path)
    assert failure["audio_file_exists"] is True
    assert failure["audio_file_size"] == audio_path.stat().st_size
    assert failure["audio_filename"] == "Creator - Original sound.mp3"
