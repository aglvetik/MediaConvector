from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app import messages
from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode, is_auth_related_music_failure
from app.domain.errors import MusicDownloadError, MusicNotFoundError
from app.domain.interfaces.music_cookie_provider import MusicCookieProvider
from app.domain.interfaces.music_provider import MusicDownloadProvider, MusicMetadataProvider, MusicSearchProvider
from app.infrastructure.logging import get_logger, log_event


@dataclass(slots=True, frozen=True)
class MusicAcquisitionFailure:
    strategy_name: str
    stage: str
    error_code: str
    source_id: str | None = None
    message: str | None = None


@dataclass(slots=True, frozen=True)
class MusicAcquisitionResult:
    track: MusicTrack
    source_audio_path: Path
    strategy_name: str
    attempts: tuple[MusicAcquisitionFailure, ...]


class MusicResolverStrategy(Protocol):
    name: str

    async def skip_reason(self) -> str | None:
        ...

    async def resolve_candidates(self, query: MusicSearchQuery, *, max_candidates: int) -> list[MusicTrack]:
        ...


class MusicDownloadStrategy(Protocol):
    name: str

    async def skip_reason(self) -> str | None:
        ...

    async def acquire(self, query: MusicSearchQuery, candidate: MusicTrack, work_dir: Path) -> MusicDownloadArtifact:
        ...


SkipProbe = Callable[[], Awaitable[str | None]]


class MusicProviderResolverStrategy:
    def __init__(
        self,
        *,
        name: str,
        provider: MusicSearchProvider,
        cookie_provider: MusicCookieProvider | None = None,
        respect_health_state: bool = True,
        skip_probe: SkipProbe | None = None,
    ) -> None:
        self.name = name
        self._provider = provider
        self._cookie_provider = cookie_provider
        self._respect_health_state = respect_health_state
        self._skip_probe = skip_probe
        self._logger = get_logger(__name__)

    async def skip_reason(self) -> str | None:
        state_reason = await self._cookie_skip_reason()
        if state_reason is not None:
            return state_reason
        if self._skip_probe is None:
            return None
        return await self._skip_probe()

    async def resolve_candidates(self, query: MusicSearchQuery, *, max_candidates: int) -> list[MusicTrack]:
        cookies_file = await self._resolve_cookie_file()
        if self._cookie_provider is not None and cookies_file is None:
            raise MusicDownloadError(
                "Music cookies file is unavailable for resolver step.",
                error_code=MusicFailureCode.COOKIES_MISSING.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
            )
        try:
            candidates = await self._provider.resolve_candidates(
                query.raw_query,
                max_candidates=max_candidates,
                cookies_file=cookies_file,
            )
        except MusicDownloadError as exc:
            raise await self._translate_failure(exc) from exc
        await self._mark_success()
        return candidates

    async def _cookie_skip_reason(self) -> str | None:
        if self._cookie_provider is None or not self._respect_health_state:
            return None
        state = await self._cookie_provider.current_state()
        if state.is_degraded():
            return f"degraded:{state.status.value}"
        return None

    async def _resolve_cookie_file(self) -> Path | None:
        if self._cookie_provider is None:
            return None
        return await self._cookie_provider.get_cookie_file()

    async def _mark_success(self) -> None:
        if self._cookie_provider is None:
            return
        await self._cookie_provider.mark_success()

    async def _translate_failure(self, exc: MusicDownloadError) -> MusicDownloadError:
        if self._cookie_provider is None:
            return exc
        translated = exc
        if exc.error_code in {
            MusicFailureCode.LOGIN_REQUIRED.value,
            MusicFailureCode.PO_TOKEN_REQUIRED.value,
        }:
            translated = MusicDownloadError(
                str(exc),
                error_code=MusicFailureCode.COOKIES_SUSPECT.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
                context={**exc.context, "original_error_code": exc.error_code},
            )
        await self._cookie_provider.mark_failure(
            translated.error_code,
            error_message=str(exc),
        )
        log_event(
            self._logger,
            logging.WARNING,
            "music_strategy_failure_recorded",
            strategy_name=self.name,
            error_code=translated.error_code,
            stage="resolver",
        )
        return translated


class MusicProviderDownloadStrategy:
    def __init__(
        self,
        *,
        name: str,
        provider: MusicDownloadProvider,
        cookie_provider: MusicCookieProvider | None = None,
        respect_health_state: bool = True,
        skip_probe: SkipProbe | None = None,
    ) -> None:
        self.name = name
        self._provider = provider
        self._cookie_provider = cookie_provider
        self._respect_health_state = respect_health_state
        self._skip_probe = skip_probe
        self._logger = get_logger(__name__)

    async def skip_reason(self) -> str | None:
        state_reason = await self._cookie_skip_reason()
        if state_reason is not None:
            return state_reason
        if self._skip_probe is None:
            return None
        return await self._skip_probe()

    async def acquire(self, query: MusicSearchQuery, candidate: MusicTrack, work_dir: Path) -> MusicDownloadArtifact:
        cookies_file = await self._resolve_cookie_file()
        if self._cookie_provider is not None and cookies_file is None:
            raise MusicDownloadError(
                "Music cookies file is unavailable for download step.",
                error_code=MusicFailureCode.COOKIES_MISSING.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
            )
        try:
            artifact = await self._provider.download_track_audio(
                query,
                candidate,
                work_dir,
                cookies_file=cookies_file,
            )
        except MusicDownloadError as exc:
            raise await self._translate_failure(exc) from exc
        await self._mark_success()
        return artifact

    async def _cookie_skip_reason(self) -> str | None:
        if self._cookie_provider is None or not self._respect_health_state:
            return None
        state = await self._cookie_provider.current_state()
        if state.is_degraded():
            return f"degraded:{state.status.value}"
        return None

    async def _resolve_cookie_file(self) -> Path | None:
        if self._cookie_provider is None:
            return None
        return await self._cookie_provider.get_cookie_file()

    async def _mark_success(self) -> None:
        if self._cookie_provider is None:
            return
        await self._cookie_provider.mark_success()

    async def _translate_failure(self, exc: MusicDownloadError) -> MusicDownloadError:
        if self._cookie_provider is None:
            return exc
        translated = exc
        if exc.error_code in {
            MusicFailureCode.LOGIN_REQUIRED.value,
            MusicFailureCode.PO_TOKEN_REQUIRED.value,
        }:
            translated = MusicDownloadError(
                str(exc),
                error_code=MusicFailureCode.COOKIES_SUSPECT.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
                context={**exc.context, "original_error_code": exc.error_code},
            )
        await self._cookie_provider.mark_failure(
            translated.error_code,
            error_message=str(exc),
        )
        log_event(
            self._logger,
            logging.WARNING,
            "music_strategy_failure_recorded",
            strategy_name=self.name,
            error_code=translated.error_code,
            stage="download",
        )
        return translated


class MusicAcquisitionService:
    def __init__(
        self,
        *,
        resolver_strategies: tuple[MusicResolverStrategy, ...],
        download_strategies: tuple[MusicDownloadStrategy, ...],
        metadata_provider: MusicMetadataProvider | None,
        max_candidates: int,
    ) -> None:
        self._resolver_strategies = resolver_strategies
        self._download_strategies = download_strategies
        self._metadata_provider = metadata_provider
        self._max_candidates = max_candidates
        self._logger = get_logger(__name__)

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        if self._metadata_provider is None:
            return None
        return await self._metadata_provider.download_thumbnail(
            thumbnail_url,
            work_dir,
            fallback_stem=fallback_stem,
        )

    async def acquire(self, query: MusicSearchQuery, work_dir: Path) -> MusicAcquisitionResult:
        failures: list[MusicAcquisitionFailure] = []
        blocked_resolver_strategies: set[str] = set()
        blocked_download_strategies: set[str] = set()
        candidates = await self._resolve_candidates(
            query,
            failures=failures,
            blocked_resolver_strategies=blocked_resolver_strategies,
        )

        for candidate in candidates:
            for strategy in self._download_strategies:
                if strategy.name in blocked_download_strategies:
                    continue

                skip_reason = await strategy.skip_reason()
                if skip_reason is not None:
                    failures.append(
                        MusicAcquisitionFailure(
                            strategy_name=strategy.name,
                            stage="download",
                            error_code=_skip_reason_error_code(skip_reason),
                            source_id=candidate.source_id,
                            message=skip_reason,
                        )
                    )
                    log_event(
                        self._logger,
                        logging.INFO,
                        "music_strategy_skipped",
                        strategy_name=strategy.name,
                        normalized_key=query.normalized_resource.normalized_key,
                        source_id=candidate.source_id,
                        stage="download",
                        reason=skip_reason,
                    )
                    continue

                try:
                    artifact = await strategy.acquire(query, candidate, work_dir)
                except MusicDownloadError as exc:
                    failures.append(
                        MusicAcquisitionFailure(
                            strategy_name=strategy.name,
                            stage="download",
                            error_code=exc.error_code,
                            source_id=candidate.source_id,
                            message=str(exc),
                        )
                    )
                    if is_auth_related_music_failure(exc.error_code):
                        blocked_download_strategies.add(strategy.name)
                    log_event(
                        self._logger,
                        logging.WARNING,
                        "music_acquisition_attempt_failed",
                        strategy_name=strategy.name,
                        normalized_key=query.normalized_resource.normalized_key,
                        source_id=candidate.source_id,
                        error_code=exc.error_code,
                    )
                    continue

                resolved_track = artifact.apply_to_track(candidate)
                log_event(
                    self._logger,
                    logging.INFO,
                    "music_acquisition_succeeded",
                    strategy_name=strategy.name,
                    normalized_key=query.normalized_resource.normalized_key,
                    source_id=resolved_track.source_id,
                    attempts=len(failures),
                )
                return MusicAcquisitionResult(
                    track=resolved_track,
                    source_audio_path=artifact.source_audio_path,
                    strategy_name=strategy.name,
                    attempts=tuple(failures),
                )

        raise self._build_exhausted_error(query, failures)

    async def _resolve_candidates(
        self,
        query: MusicSearchQuery,
        *,
        failures: list[MusicAcquisitionFailure],
        blocked_resolver_strategies: set[str],
    ) -> list[MusicTrack]:
        for strategy in self._resolver_strategies:
            if strategy.name in blocked_resolver_strategies:
                continue

            skip_reason = await strategy.skip_reason()
            if skip_reason is not None:
                failures.append(
                    MusicAcquisitionFailure(
                        strategy_name=strategy.name,
                        stage="resolver",
                        error_code=_skip_reason_error_code(skip_reason),
                        message=skip_reason,
                    )
                )
                log_event(
                    self._logger,
                    logging.INFO,
                    "music_strategy_skipped",
                    strategy_name=strategy.name,
                    normalized_key=query.normalized_resource.normalized_key,
                    stage="resolver",
                    reason=skip_reason,
                )
                continue

            try:
                candidates = await strategy.resolve_candidates(query, max_candidates=self._max_candidates)
            except MusicDownloadError as exc:
                failures.append(
                    MusicAcquisitionFailure(
                        strategy_name=strategy.name,
                        stage="resolver",
                        error_code=exc.error_code,
                        message=str(exc),
                    )
                )
                if is_auth_related_music_failure(exc.error_code):
                    blocked_resolver_strategies.add(strategy.name)
                log_event(
                    self._logger,
                    logging.WARNING,
                    "music_resolver_failed",
                    strategy_name=strategy.name,
                    normalized_key=query.normalized_resource.normalized_key,
                    error_code=exc.error_code,
                )
                continue

            if candidates:
                log_event(
                    self._logger,
                    logging.INFO,
                    "music_resolver_selected_candidates",
                    strategy_name=strategy.name,
                    normalized_key=query.normalized_resource.normalized_key,
                    candidate_ids=[candidate.source_id for candidate in candidates],
                )
                return candidates[: self._max_candidates]

            log_event(
                self._logger,
                logging.INFO,
                "music_resolver_empty",
                strategy_name=strategy.name,
                normalized_key=query.normalized_resource.normalized_key,
            )

        if failures:
            raise self._build_exhausted_error(query, failures)
        raise MusicNotFoundError()

    def _build_exhausted_error(
        self,
        query: MusicSearchQuery,
        failures: list[MusicAcquisitionFailure],
    ) -> MusicDownloadError:
        failure_codes = {failure.error_code for failure in failures}
        auth_only = bool(failure_codes) and all(is_auth_related_music_failure(code) for code in failure_codes)
        user_message = messages.MUSIC_SOURCE_DEGRADED if auth_only else messages.MUSIC_DOWNLOAD_FAILED
        return MusicDownloadError(
            "All music acquisition attempts failed.",
            error_code=MusicFailureCode.ACQUISITION_EXHAUSTED.value,
            user_message=user_message,
            context={
                "normalized_key": query.normalized_resource.normalized_key,
                "attempts": [asdict(failure) for failure in failures],
            },
        )


def _skip_reason_error_code(skip_reason: str) -> str:
    if skip_reason.startswith("degraded:"):
        return MusicFailureCode.COOKIES_SUSPECT.value
    return MusicFailureCode.SOURCE_UNAVAILABLE.value
