from __future__ import annotations

from pathlib import Path

import pytest

from app import messages
from app.domain.entities.media_result import DeliveryReceipt, MediaMetadata, MediaResult
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.delivery_status import DeliveryStatus
from app.domain.enums.platform import Platform


def _build_music_request(*, source_video_url: str | None = None, source_video_id: str | None = None) -> MediaRequest:
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
            source_video_url=source_video_url,
            source_video_id=source_video_id,
            source_resolution_strategy="original_source_video" if source_video_url is not None else None,
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
    assert asset.source_audio_extension == "m4a"
    assert asset.container_extension == "mp3"
    assert asset.final_audio_path.exists()
    assert service_harness.ffmpeg.calls["transcode:tiktok:music_only:123456"] == 1


@pytest.mark.asyncio
async def test_music_only_preparation_result_contains_non_null_final_audio_path(service_harness, tmp_path: Path) -> None:
    request = _build_music_request()
    source_path = tmp_path / "fallback-source.m4a"
    source_path.write_bytes(b"m4a-bytes")

    result = await service_harness.media_pipeline_service._prepare_audio_delivery_asset(  # type: ignore[attr-defined]
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
        fatal_on_failure=True,
        missing_notice=messages.TEMPORARY_DOWNLOAD_ERROR,
        failure_notice=messages.TEMPORARY_DOWNLOAD_ERROR,
    )

    assert result.is_prepared is True
    assert result.asset is not None
    assert result.asset.final_audio_path.exists()
    assert result.asset.final_audio_path.suffix.lower() == ".mp3"
    assert result.asset.telegram_filename.endswith(".mp3")


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
    assert asset.source_audio_extension == "m4a"
    assert asset.container_extension == "m4a"
    assert service_harness.ffmpeg.calls.get("transcode:tiktok:music_only:123456", 0) == 0


@pytest.mark.asyncio
async def test_music_only_pipeline_routes_final_prepared_audio_to_audio_delivery(service_harness) -> None:
    request = _build_music_request(
        source_video_url="https://www.tiktok.com/@creator/video/9876543210123456789",
        source_video_id="9876543210123456789",
    )
    captured: dict[str, object] = {}

    async def fake_deliver_audio_only(request_arg, audio_path, **kwargs):
        captured["resource_type"] = request_arg.normalized_resource.resource_type
        captured["audio_path"] = audio_path
        captured["filename"] = kwargs["filename"]
        captured["source_audio_extension"] = kwargs["source_audio_extension"]
        captured["final_audio_extension"] = kwargs["final_audio_extension"]
        return MediaResult(
            delivery_status=DeliveryStatus.SENT_AUDIO,
            cache_status=CacheStatus.READY,
            video_receipt=None,
            audio_receipt=DeliveryReceipt(file_id="audio:ok", file_unique_id="audio-unique:ok", size_bytes=123),
            has_audio=True,
            cache_hit=False,
        )

    service_harness.delivery_service.deliver_audio_only = fake_deliver_audio_only  # type: ignore[method-assign]

    result = await service_harness.media_pipeline_service.process(request, service_harness.provider)

    assert result.audio_receipt is not None
    assert captured["resource_type"] == "music_only"
    assert isinstance(captured["audio_path"], Path)
    assert captured["audio_path"].suffix.lower() == ".mp3"
    assert str(captured["filename"]).endswith(".mp3")
    assert captured["source_audio_extension"] == "mp4"
    assert captured["final_audio_extension"] == "mp3"


@pytest.mark.asyncio
async def test_music_only_runtime_path_prefers_source_video_and_logs_it(service_harness, monkeypatch) -> None:
    request = _build_music_request(
        source_video_url="https://www.tiktok.com/@creator/video/9876543210123456790",
        source_video_id="9876543210123456790",
    )
    events: list[tuple[str, dict[str, object]]] = []

    def fake_log_event(logger, level, event_name, **fields) -> None:
        del logger, level
        events.append((event_name, fields))

    monkeypatch.setattr("app.application.services.media_pipeline_service.log_event", fake_log_event)

    result = await service_harness.media_pipeline_service.process(request, service_harness.provider)

    assert result.audio_receipt is not None
    assert service_harness.provider.download_calls["tiktok:music_only:123456"] == 1
    assert service_harness.provider.audio_download_calls["tiktok:music_only:123456"] == 0
    event_names = [event_name for event_name, _ in events]
    assert "tiktok_music_pipeline_using_source_video" in event_names
    assert "tiktok_music_audio_extracted_from_source_video" in event_names


@pytest.mark.asyncio
async def test_music_only_transcode_failure_does_not_emit_prepared_metadata_and_logs_unavailable_asset(
    service_harness, monkeypatch
) -> None:
    request = _build_music_request()
    service_harness.ffmpeg.transcode_fail_keys.add("tiktok:music_only:123456")
    events: list[tuple[str, dict[str, object]]] = []

    def fake_log_event(logger, level, event_name, **fields) -> None:
        del logger, level
        events.append((event_name, fields))

    monkeypatch.setattr("app.application.services.media_pipeline_service.log_event", fake_log_event)

    result = await service_harness.media_pipeline_service.process(request, service_harness.provider)

    assert result.audio_receipt is None
    assert result.delivery_status == DeliveryStatus.FAILED
    event_names = [event_name for event_name, _ in events]
    assert "audio_metadata_prepared" not in event_names
    unavailable_events = [fields for event_name, fields in events if event_name == "audio_delivery_asset_unavailable"]
    assert len(unavailable_events) == 1
    unavailable = unavailable_events[0]
    assert unavailable["resource_type"] == "music_only"
    assert str(unavailable["audio_filename"]).endswith(".mp3")
    assert unavailable["source_audio_extension"] == "m4a"
    assert unavailable["final_audio_extension"] == "mp3"


@pytest.mark.asyncio
async def test_music_only_delivery_logs_started_and_finished(service_harness, tmp_path: Path, monkeypatch) -> None:
    request = _build_music_request()
    audio_path = tmp_path / "prepared.mp3"
    audio_path.write_bytes(b"mp3-bytes")
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
        source_audio_extension="m4a",
        final_audio_extension="mp3",
    )

    assert result.audio_receipt is not None
    event_names = [event_name for event_name, _ in events]
    assert "telegram_audio_validation_started" in event_names
    assert "telegram_send_audio_started" in event_names
    assert "telegram_send_audio_finished" in event_names


@pytest.mark.asyncio
async def test_music_only_validation_failure_logs_context(service_harness, tmp_path: Path, monkeypatch) -> None:
    request = _build_music_request()
    audio_path = tmp_path / "prepared.m4a"
    audio_path.write_bytes(b"m4a-bytes")
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
        source_audio_extension="m4a",
        final_audio_extension="mp3",
    )

    assert result.audio_receipt is None
    validation_events = [fields for event_name, fields in events if event_name == "telegram_audio_validation_failed"]
    assert len(validation_events) == 1
    failure = validation_events[0]
    assert failure["normalized_key"] == "tiktok:music_only:123456"
    assert failure["resource_type"] == "music_only"
    assert failure["final_audio_path"] == str(audio_path)
    assert failure["audio_file_exists"] is True
    assert failure["audio_file_size"] == audio_path.stat().st_size
    assert failure["telegram_filename"] == "Creator - Original sound.mp3"
    assert failure["source_audio_extension"] == "m4a"
    assert failure["final_audio_extension"] == "mp3"
    assert failure["mismatch_reason"] == "extension_mismatch"
    assert "telegram_send_audio_started" not in [event_name for event_name, _ in events]


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
        source_audio_extension="m4a",
        final_audio_extension="mp3",
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
