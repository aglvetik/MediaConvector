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
    skip_value: str | None = None
    acquire_errors: dict[str, MusicDownloadError] = field(default_factory=dict)
    acquire_calls: list[str] = field(default_factory=list)

    async def skip_reason(self) -> str | None:
        return self.skip_value

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
        source_url=f"https://www.youtube.com/watch?v={source_id}",
        canonical_url=f"https://music.youtube.com/watch?v={source_id}",
        title=f"Track {source_id}",
        performer="Artist",
        duration_sec=180,
        thumbnail_url=None,
        resolver_name="test",
        source_name="youtube",
        ranking=ranking,
    )


async def test_multi_candidate_resolution_tries_next_candidate_after_all_download_strategies_fail(tmp_path: Path) -> None:
    resolver = FakeResolverStrategy(
        name="youtube_cookies",
        candidates=[_candidate("first", 1), _candidate("second", 2)],
    )
    remote = FakeDownloadStrategy(
        name="remote_http",
        acquire_errors={
            "first": MusicDownloadError(
                "remote unavailable",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            ),
        },
    )
    youtube_direct = FakeDownloadStrategy(
        name="youtube_cookies",
        acquire_errors={
            "first": MusicDownloadError(
                "no formats",
                error_code=MusicFailureCode.NO_FORMATS.value,
            ),
        },
    )
    service = MusicAcquisitionService(
        resolver_strategies=(resolver,),
        download_strategies=(remote, youtube_direct),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "after dark"),
        tmp_path,
    )

    assert result.track.source_id == "remote_http-second"
    assert remote.acquire_calls == ["first", "second"]
    assert youtube_direct.acquire_calls == ["first"]


async def test_strategy_fallback_uses_next_download_strategy_after_remote_failure(tmp_path: Path) -> None:
    resolver = FakeResolverStrategy(
        name="youtube_cookies",
        candidates=[_candidate("main", 1)],
    )
    remote = FakeDownloadStrategy(
        name="remote_http",
        acquire_errors={
            "main": MusicDownloadError(
                "remote unavailable",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            ),
        },
    )
    youtube_direct = FakeDownloadStrategy(name="youtube_cookies")
    service = MusicAcquisitionService(
        resolver_strategies=(resolver,),
        download_strategies=(remote, youtube_direct),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "rammstein sonne"),
        tmp_path,
    )

    assert result.track.source_id == "youtube_cookies-main"
    assert remote.acquire_calls == ["main"]
    assert youtube_direct.acquire_calls == ["main"]


async def test_unconfigured_primary_download_strategy_is_skipped_without_blocking_fallback(tmp_path: Path) -> None:
    resolver = FakeResolverStrategy(
        name="youtube_cookies",
        candidates=[_candidate("main", 1)],
    )
    remote = FakeDownloadStrategy(
        name="remote_http",
        skip_value="provider_not_configured",
    )
    youtube_direct = FakeDownloadStrategy(name="youtube_cookies")
    service = MusicAcquisitionService(
        resolver_strategies=(resolver,),
        download_strategies=(remote, youtube_direct),
        metadata_provider=None,
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("\u043d\u0430\u0439\u0442\u0438", "depeche mode enjoy the silence"),
        tmp_path,
    )

    assert result.track.source_id == "youtube_cookies-main"
    assert remote.acquire_calls == []
    assert youtube_direct.acquire_calls == ["main"]
