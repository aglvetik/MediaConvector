from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.application.services.music_acquisition_service import MusicAcquisitionService
from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode
from app.domain.errors import MusicDownloadError
from app.domain.policies import build_music_search_query


@dataclass(slots=True)
class FakeResolverStrategy:
    name: str
    candidates: list[MusicTrack] = field(default_factory=list)
    resolve_error: MusicDownloadError | None = None
    skip_value: str | None = None
    resolve_calls: int = 0

    async def skip_reason(self) -> str | None:
        return self.skip_value

    async def resolve_candidates(self, query, *, max_candidates: int) -> list[MusicTrack]:
        del query
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.candidates[:max_candidates]


@dataclass(slots=True)
class FakeDownloadStrategy:
    name: str
    supported_sources: tuple[str, ...] = ()
    skip_value: str | None = None
    acquire_errors: dict[str, MusicDownloadError] = field(default_factory=dict)
    acquire_calls: list[str] = field(default_factory=list)

    async def skip_reason(self) -> str | None:
        return self.skip_value

    def supports_candidate(self, candidate: MusicTrack) -> bool:
        if not self.supported_sources:
            return True
        return candidate.source_name in self.supported_sources

    async def acquire(self, query, candidate: MusicTrack, work_dir: Path) -> MusicDownloadArtifact:
        del query
        self.acquire_calls.append(candidate.source_id)
        if candidate.source_id in self.acquire_errors:
            raise self.acquire_errors[candidate.source_id]
        output_path = work_dir / f"{self.name}-{candidate.source_id}.m4a"
        output_path.write_bytes(b"audio")
        return MusicDownloadArtifact(
            source_audio_path=output_path,
            provider_name=self.name,
            source_id=f"{self.name}-{candidate.source_id}",
            source_name=self.name,
        )


def _candidate(source_id: str, ranking: int) -> MusicTrack:
    return MusicTrack(
        source_id=source_id,
        source_url=f"https://catalog.example/jamendo/{source_id}",
        canonical_url=f"https://catalog.example/jamendo/{source_id}",
        title=f"Track {source_id}",
        performer="Artist",
        duration_sec=180,
        thumbnail_url=None,
        resolver_name="test",
        source_name="jamendo",
        ranking=ranking,
    )


async def test_multi_candidate_resolution_tries_next_candidate_inside_same_provider(tmp_path: Path) -> None:
    resolver = FakeResolverStrategy(
        name="jamendo",
        candidates=[_candidate("first", 1), _candidate("second", 2)],
    )
    jamendo_downloader = FakeDownloadStrategy(
        name="jamendo",
        supported_sources=("jamendo",),
        acquire_errors={
            "first": MusicDownloadError(
                "download unavailable",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            ),
        },
    )
    service = MusicAcquisitionService(
        resolver_strategies=(resolver,),
        download_strategies=(jamendo_downloader,),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "after dark"),
        tmp_path,
    )

    assert result.track.source_id == "jamendo-second"
    assert jamendo_downloader.acquire_calls == ["first", "second"]


async def test_provider_order_falls_back_to_next_resolver_when_jamendo_downloads_fail(tmp_path: Path) -> None:
    jamendo_resolver = FakeResolverStrategy(
        name="jamendo",
        candidates=[_candidate("main", 1)],
    )
    internet_archive_candidate = MusicTrack(
        source_id="archive-main",
        source_url="https://archive.org/download/archive-main/audio.mp3",
        canonical_url="https://archive.org/details/archive-main",
        title="Archive Main",
        performer="Archive Artist",
        duration_sec=180,
        thumbnail_url=None,
        resolver_name="test",
        source_name="internet_archive",
        ranking=1,
    )
    archive_resolver = FakeResolverStrategy(
        name="internet_archive",
        candidates=[internet_archive_candidate],
    )
    jamendo_downloader = FakeDownloadStrategy(
        name="jamendo",
        supported_sources=("jamendo",),
        acquire_errors={
            "main": MusicDownloadError(
                "jamendo unavailable",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            ),
        },
    )
    archive_downloader = FakeDownloadStrategy(
        name="internet_archive",
        supported_sources=("internet_archive",),
    )
    service = MusicAcquisitionService(
        resolver_strategies=(jamendo_resolver, archive_resolver),
        download_strategies=(jamendo_downloader, archive_downloader),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "rammstein sonne"),
        tmp_path,
    )

    assert result.track.source_id == "internet_archive-archive-main"
    assert jamendo_resolver.resolve_calls == 1
    assert archive_resolver.resolve_calls == 1
    assert jamendo_downloader.acquire_calls == ["main"]
    assert archive_downloader.acquire_calls == ["archive-main"]


async def test_unconfigured_primary_provider_is_skipped_without_blocking_archive_fallback(tmp_path: Path) -> None:
    jamendo_resolver = FakeResolverStrategy(
        name="jamendo",
        candidates=[_candidate("main", 1)],
        skip_value="provider_not_configured",
    )
    archive_candidate = MusicTrack(
        source_id="archive-track",
        source_url="https://archive.org/download/archive-track/audio.mp3",
        canonical_url="https://archive.org/details/archive-track",
        title="Archive Track",
        performer="Archive Artist",
        duration_sec=180,
        thumbnail_url=None,
        resolver_name="test",
        source_name="internet_archive",
        ranking=1,
    )
    archive_resolver = FakeResolverStrategy(
        name="internet_archive",
        candidates=[archive_candidate],
    )
    jamendo_downloader = FakeDownloadStrategy(
        name="jamendo",
        supported_sources=("jamendo",),
        skip_value="provider_not_configured",
    )
    archive_downloader = FakeDownloadStrategy(
        name="internet_archive",
        supported_sources=("internet_archive",),
    )
    service = MusicAcquisitionService(
        resolver_strategies=(jamendo_resolver, archive_resolver),
        download_strategies=(jamendo_downloader, archive_downloader),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "depeche mode enjoy the silence"),
        tmp_path,
    )

    assert result.track.source_id == "internet_archive-archive-track"
    assert jamendo_downloader.acquire_calls == []
    assert archive_downloader.acquire_calls == ["archive-track"]
