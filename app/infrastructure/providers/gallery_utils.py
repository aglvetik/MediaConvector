from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.domain.entities.source_media_artifact import SourceMediaArtifact
from app.domain.entities.visual_media_entry import VisualMediaEntry
from app.domain.enums.platform import Platform

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "ogg", "opus", "wav", "flac"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "mkv", "m4v", "avi"}


@dataclass(slots=True, frozen=True)
class PreparedCollection:
    all_files: tuple[Path, ...]
    image_files: tuple[Path, ...]
    audio_files: tuple[Path, ...]
    video_files: tuple[Path, ...]


def build_artifact_from_gallery_probe(
    *,
    platform: Platform,
    original_url: str,
    probe_entries: Sequence[dict[str, object]],
    canonical_url: str | None = None,
    source_id: str | None = None,
    fallback_title: str | None = None,
    fallback_uploader: str | None = None,
) -> SourceMediaArtifact | None:
    cleaned_canonical_url = canonical_url or _clean_url(original_url)
    resolved_source_id = source_id or _extract_probe_scalar(
        probe_entries,
        {"id", "post_id", "media_id", "shortcode", "pin_id", "item_id"},
    )
    if resolved_source_id is None:
        resolved_source_id = _fallback_source_id(cleaned_canonical_url)

    title = fallback_title or _extract_probe_scalar(
        probe_entries,
        {"title", "description", "caption", "post_title", "item_title"},
    )
    uploader = fallback_uploader or _extract_probe_scalar(
        probe_entries,
        {"author", "username", "uploader", "channel", "owner", "user", "account"},
    )
    duration_sec = _extract_probe_int(probe_entries, {"duration", "duration_sec"})

    image_entries: list[VisualMediaEntry] = []
    image_sources: list[str] = []
    audio_source: str | None = None
    video_source: str | None = None

    for index, entry in enumerate(probe_entries, start=1):
        media_url = _extract_probe_media_url(entry)
        extension = _extract_probe_extension(entry, media_url)
        media_kind = _classify_probe_entry(entry, media_url, extension)

        if media_kind == "image":
            source_url = media_url or f"{cleaned_canonical_url}#image-{index}"
            image_sources.append(source_url)
            image_entries.append(
                VisualMediaEntry(
                    source_url=source_url,
                    order=index,
                    mime_type_hint=_mime_type_hint_from_extension(extension),
                )
            )
            continue

        if media_kind == "audio" and audio_source is None and media_url is not None:
            audio_source = media_url
            continue

        if media_kind == "video" and video_source is None and media_url is not None:
            video_source = media_url

    if image_entries:
        return SourceMediaArtifact(
            source_type=platform,
            canonical_url=cleaned_canonical_url,
            media_kind="gallery" if len(image_entries) > 1 else "photo",
            source_id=resolved_source_id,
            engine_name="gallery-dl",
            title=title,
            uploader=uploader,
            duration_sec=duration_sec,
            audio_source=audio_source,
            has_expected_audio=audio_source is not None,
            image_sources=tuple(image_sources),
            image_entries=tuple(image_entries),
        )

    if video_source is not None:
        return SourceMediaArtifact(
            source_type=platform,
            canonical_url=cleaned_canonical_url,
            media_kind="video",
            source_id=resolved_source_id,
            engine_name="gallery-dl",
            title=title,
            uploader=uploader,
            duration_sec=duration_sec,
            has_expected_audio=True if audio_source is not None else None,
            audio_source=audio_source,
        )

    if audio_source is not None:
        return SourceMediaArtifact(
            source_type=platform,
            canonical_url=cleaned_canonical_url,
            media_kind="audio",
            source_id=resolved_source_id,
            engine_name="gallery-dl",
            title=title,
            uploader=uploader,
            duration_sec=duration_sec,
            audio_source=audio_source,
            has_expected_audio=True,
        )

    return None


def prepare_collection_from_files(paths: Iterable[Path]) -> PreparedCollection:
    all_files = tuple(sorted((path for path in paths if path.is_file()), key=lambda item: str(item)))
    image_files: list[Path] = []
    audio_files: list[Path] = []
    video_files: list[Path] = []
    for path in all_files:
        suffix = path.suffix.lower().lstrip(".")
        if suffix in IMAGE_EXTENSIONS:
            image_files.append(path)
        elif suffix in AUDIO_EXTENSIONS:
            audio_files.append(path)
        elif suffix in VIDEO_EXTENSIONS:
            video_files.append(path)
    return PreparedCollection(
        all_files=all_files,
        image_files=tuple(image_files),
        audio_files=tuple(audio_files),
        video_files=tuple(video_files),
    )


def clean_url(url: str) -> str:
    return _clean_url(url)


def fallback_source_id(url: str) -> str:
    return _fallback_source_id(url)


def _clean_url(url: str) -> str:
    stripped = url.strip()
    return stripped.split("#", 1)[0].split("?", 1)[0]


def _fallback_source_id(canonical_url: str) -> str:
    path = Path(urlparse(canonical_url).path)
    if path.stem:
        return path.stem
    return canonical_url.rstrip("/").rsplit("/", 1)[-1] or "resource"


def _extract_probe_scalar(entries: Sequence[dict[str, object]], keys: set[str]) -> str | None:
    for entry in entries:
        value = _find_scalar(entry, keys)
        if value:
            return value
    return None


def _extract_probe_int(entries: Sequence[dict[str, object]], keys: set[str]) -> int | None:
    raw_value = _extract_probe_scalar(entries, keys)
    try:
        return int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None


def _find_scalar(payload: object, keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys:
                scalar = _stringify_scalar(value)
                if scalar is not None:
                    return scalar
            nested = _find_scalar(value, keys)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_scalar(item, keys)
            if nested is not None:
                return nested
    return None


def _stringify_scalar(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = " ".join(value.split()).strip()
        return cleaned or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _extract_probe_media_url(entry: dict[str, object]) -> str | None:
    for key in ("url", "content", "image", "image_url", "display_url", "video_url", "audio_url", "src"):
        candidate = entry.get(key)
        extracted = _collect_first_http_url(candidate)
        if extracted is not None:
            return extracted
    return _collect_first_http_url(entry)


def _collect_first_http_url(payload: object) -> str | None:
    if isinstance(payload, str):
        cleaned = payload.strip()
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return cleaned
        return None
    if isinstance(payload, dict):
        for value in payload.values():
            extracted = _collect_first_http_url(value)
            if extracted is not None:
                return extracted
    elif isinstance(payload, list):
        for item in payload:
            extracted = _collect_first_http_url(item)
            if extracted is not None:
                return extracted
    return None


def _extract_probe_extension(entry: dict[str, object], media_url: str | None) -> str | None:
    for key in ("extension", "ext"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value.lower().lstrip(".")
    filename = entry.get("filename")
    if isinstance(filename, str) and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    if media_url is not None:
        suffix = Path(urlparse(media_url).path).suffix.lower().lstrip(".")
        return suffix or None
    return None


def _classify_probe_entry(entry: dict[str, object], media_url: str | None, extension: str | None) -> str | None:
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in VIDEO_EXTENSIONS:
        return "video"

    for key in ("type", "mediatype", "media_type", "filetype"):
        value = entry.get(key)
        if isinstance(value, str):
            lowered = value.lower()
            if "image" in lowered or "photo" in lowered:
                return "image"
            if "audio" in lowered or "sound" in lowered:
                return "audio"
            if "video" in lowered:
                return "video"

    if media_url is not None:
        path = urlparse(media_url).path.lower()
        if any(path.endswith(f".{extension}") for extension in IMAGE_EXTENSIONS):
            return "image"
        if any(path.endswith(f".{extension}") for extension in AUDIO_EXTENSIONS):
            return "audio"
        if any(path.endswith(f".{extension}") for extension in VIDEO_EXTENSIONS):
            return "video"
    return None


def _mime_type_hint_from_extension(extension: str | None) -> str | None:
    if extension is None:
        return None
    if extension in IMAGE_EXTENSIONS:
        return f"image/{'jpeg' if extension == 'jpg' else extension}"
    return None
