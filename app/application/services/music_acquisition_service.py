from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app import messages
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode, is_auth_related_music_failure
from app.domain.errors import MusicDownloadError, MusicNotFoundError
from app.domain.interfaces.music_cookie_provider import MusicCookieProvider
from app.domain.interfaces.music_provider import MusicSearchProvider
from app.infrastructure.downloaders.audio_download_client import AudioDownloadClient
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


class MusicAcquisitionStrategy(Protocol):
    name: str

    async def skip_reason(self) -> str | None:
        ...

    async def resolve_candidates(self, query: MusicSearchQuery, *, max_candidates: int) -> list[MusicTrack]:
        ...

    async def acquire(self, candidate: MusicTrack, work_dir: Path) -> Path:
        ...


class YoutubeAcquisitionStrategy:
    def __init__(
        self,
        *,
        name: str,
        provider: MusicSearchProvider,
        downloader: AudioDownloadClient,
        cookie_provider: MusicCookieProvider | None = None,
        respect_health_state: bool = True,
    ) -> None:
        self.name = name
        self._provider = provider
        self._downloader = downloader
        self._cookie_provider = cookie_provider
        self._respect_health_state = respect_health_state
        self._logger = get_logger(__name__)

    async def skip_reason(self) -> str | None:
        if self._cookie_provider is None or not self._respect_health_state:
            return None
        state = await self._cookie_provider.current_state()
        if state.is_degraded():
            return f"degraded:{state.status.value}"
        return None

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

    async def acquire(self, candidate: MusicTrack, work_dir: Path) -> Path:
        cookies_file = await self._resolve_cookie_file()
        if self._cookie_provider is not None and cookies_file is None:
            raise MusicDownloadError(
                "Music cookies file is unavailable for download step.",
                error_code=MusicFailureCode.COOKIES_MISSING.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
            )
        try:
            output_path = await self._downloader.download_audio_source(
                candidate,
                work_dir,
                cookies_file=cookies_file,
            )
        except MusicDownloadError as exc:
            raise await self._translate_failure(exc) from exc
        await self._mark_success()
        return output_path

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        return await self._downloader.download_thumbnail(
            thumbnail_url,
            work_dir,
            fallback_stem=fallback_stem,
        )

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
        )
        return translated


class MusicAcquisitionService:
    def __init__(
        self,
        *,
        strategies: tuple[MusicAcquisitionStrategy, ...],
        max_candidates: int,
    ) -> None:
        self._strategies = strategies
        self._max_candidates = max_candidates
        self._logger = get_logger(__name__)

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        primary_strategy = self._strategies[0]
        if isinstance(primary_strategy, YoutubeAcquisitionStrategy):
            return await primary_strategy.download_thumbnail(
                thumbnail_url,
                work_dir,
                fallback_stem=fallback_stem,
            )
        return None

    async def acquire(self, query: MusicSearchQuery, work_dir: Path) -> MusicAcquisitionResult:
        failures: list[MusicAcquisitionFailure] = []
        blocked_strategies: set[str] = set()
        candidates = await self._resolve_candidates(query, failures=failures, blocked_strategies=blocked_strategies)

        for candidate in candidates:
            for strategy in self._strategies:
                if strategy.name in blocked_strategies:
                    continue

                skip_reason = await strategy.skip_reason()
                if skip_reason is not None:
                    failures.append(
                        MusicAcquisitionFailure(
                            strategy_name=strategy.name,
                            stage="download",
                            error_code=MusicFailureCode.COOKIES_SUSPECT.value,
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
                    source_audio_path = await strategy.acquire(candidate, work_dir)
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
                        blocked_strategies.add(strategy.name)
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

                log_event(
                    self._logger,
                    logging.INFO,
                    "music_acquisition_succeeded",
                    strategy_name=strategy.name,
                    normalized_key=query.normalized_resource.normalized_key,
                    source_id=candidate.source_id,
                    attempts=len(failures),
                )
                return MusicAcquisitionResult(
                    track=candidate,
                    source_audio_path=source_audio_path,
                    strategy_name=strategy.name,
                    attempts=tuple(failures),
                )

        raise self._build_exhausted_error(query, failures)

    async def _resolve_candidates(
        self,
        query: MusicSearchQuery,
        *,
        failures: list[MusicAcquisitionFailure],
        blocked_strategies: set[str],
    ) -> list[MusicTrack]:
        for strategy in self._strategies:
            if strategy.name in blocked_strategies:
                continue

            skip_reason = await strategy.skip_reason()
            if skip_reason is not None:
                failures.append(
                    MusicAcquisitionFailure(
                        strategy_name=strategy.name,
                        stage="resolver",
                        error_code=MusicFailureCode.COOKIES_SUSPECT.value,
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
                    blocked_strategies.add(strategy.name)
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
