from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.application.services.music_acquisition_service import MusicAcquisitionService
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode
from app.domain.errors import MusicDownloadError
from app.domain.policies import build_music_search_query


@dataclass(slots=True)
class FakeStrategy:
    name: str
    candidates: list[MusicTrack] = field(default_factory=list)
    resolve_error: MusicDownloadError | None = None
    acquire_errors: dict[str, MusicDownloadError] = field(default_factory=dict)
    skip_value: str | None = None
    resolve_calls: int = 0
    acquire_calls: list[str] = field(default_factory=list)

    async def skip_reason(self) -> str | None:
        return self.skip_value

    async def resolve_candidates(self, query, *, max_candidates: int) -> list[MusicTrack]:
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.candidates[:max_candidates]

    async def acquire(self, candidate: MusicTrack, work_dir: Path) -> Path:
        self.acquire_calls.append(candidate.source_id)
        if candidate.source_id in self.acquire_errors:
            raise self.acquire_errors[candidate.source_id]
        output_path = work_dir / f"{candidate.source_id}.m4a"
        output_path.write_bytes(b"audio")
        return output_path


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


async def test_multi_candidate_resolution_tries_next_candidate_after_failure(tmp_path: Path) -> None:
    strategy = FakeStrategy(
        name="youtube_no_cookies",
        candidates=[_candidate("first", 1), _candidate("second", 2)],
        acquire_errors={
            "first": MusicDownloadError(
                "no formats",
                error_code=MusicFailureCode.NO_FORMATS.value,
            )
        },
    )
    service = MusicAcquisitionService(strategies=(strategy,), max_candidates=3)

    result = await service.acquire(
        build_music_search_query("найти", "after dark"),
        tmp_path,
    )

    assert result.track.source_id == "second"
    assert strategy.acquire_calls == ["first", "second"]


async def test_strategy_fallback_uses_next_strategy_after_auth_failure(tmp_path: Path) -> None:
    cookies_strategy = FakeStrategy(
        name="youtube_cookies",
        candidates=[_candidate("main", 1)],
        acquire_errors={
            "main": MusicDownloadError(
                "login required",
                error_code=MusicFailureCode.LOGIN_REQUIRED.value,
            )
        },
    )
    no_cookie_strategy = FakeStrategy(
        name="youtube_no_cookies",
        candidates=[],
    )
    service = MusicAcquisitionService(
        strategies=(cookies_strategy, no_cookie_strategy),
        max_candidates=3,
    )

    result = await service.acquire(
        build_music_search_query("найти", "rammstein sonne"),
        tmp_path,
    )

    assert result.track.source_id == "main"
    assert cookies_strategy.acquire_calls == ["main"]
    assert no_cookie_strategy.acquire_calls == ["main"]
