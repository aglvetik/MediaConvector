from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app import messages
from app.application.services.delivery_service import DeliveryService
from app.application.services.media_pipeline_service import MediaPipelineService
from app.application.services.metrics_service import MetricsService
from app.application.services.rate_limit_service import RateLimitService
from app.application.services.user_request_guard_service import UserRequestGuardService
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaResult
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.errors import AppError
from app.domain.interfaces.provider import DownloaderProvider
from app.domain.interfaces.repositories import ProcessedMessageRepository, RequestLogRepository
from app.infrastructure.logging import get_logger, log_event


@dataclass(slots=True, frozen=True)
class IncomingMessage:
    chat_id: int
    user_id: int
    message_id: int
    chat_type: Literal["private", "group", "supergroup", "channel"]
    text: str


class ProcessMessageService:
    def __init__(
        self,
        *,
        providers: tuple[DownloaderProvider, ...],
        delivery_service: DeliveryService,
        media_pipeline_service: MediaPipelineService,
        rate_limit_service: RateLimitService,
        user_request_guard_service: UserRequestGuardService,
        processed_message_repository: ProcessedMessageRepository,
        request_log_repository: RequestLogRepository,
        metrics_service: MetricsService,
    ) -> None:
        self._providers = providers
        self._delivery_service = delivery_service
        self._media_pipeline_service = media_pipeline_service
        self._rate_limit_service = rate_limit_service
        self._user_request_guard_service = user_request_guard_service
        self._processed_message_repository = processed_message_repository
        self._request_log_repository = request_log_repository
        self._metrics = metrics_service
        self._logger = get_logger(__name__)

    async def handle_message(self, incoming: IncomingMessage) -> bool:
        request_id = uuid4().hex
        normalized_key: str | None = None
        log_event(
            self._logger,
            logging.INFO,
            "incoming_message",
            request_id=request_id,
            chat_id=incoming.chat_id,
            user_id=incoming.user_id,
            message_id=incoming.message_id,
            chat_type=incoming.chat_type,
        )
        try:
            provider, detected_url = self._detect_provider(incoming.text)
            if provider is not None and detected_url is not None:
                log_event(
                    self._logger,
                    logging.INFO,
                    "url_detected",
                    request_id=request_id,
                    chat_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    detected_url=detected_url,
                )
                normalized = await provider.normalize(detected_url)
                normalized_key = normalized.normalized_key
                return await self._execute_flow(
                    request_id=request_id,
                    incoming=incoming,
                    normalized=normalized,
                    loading_text=messages.LOADING_MESSAGE,
                    pipeline_runner=lambda request: self._media_pipeline_service.process(request, provider),
                )

            return False
        except AppError as exc:
            if exc.user_message:
                await self._safe_send_user_message(incoming.chat_id, exc.user_message, incoming.message_id)
            log_event(
                self._logger,
                logging.ERROR,
                "request_failed",
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                normalized_key=normalized_key,
                error_code=exc.error_code,
            )
            return True
        except Exception:
            self._logger.exception("unexpected_error_traceback")
            await self._safe_send_user_message(incoming.chat_id, messages.UNKNOWN_ERROR, incoming.message_id)
            log_event(
                self._logger,
                logging.ERROR,
                "request_failed",
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                normalized_key=normalized_key,
                error_code="unexpected_error",
            )
            return True

    async def _execute_flow(
        self,
        *,
        request_id: str,
        incoming: IncomingMessage,
        normalized: NormalizedResource,
        loading_text: str,
        pipeline_runner: Callable[[MediaRequest], Awaitable[MediaResult]],
    ) -> bool:
        loading_message_id: int | None = None
        success = False
        delivery_status = "failed"
        cache_hit = False
        error_code: str | None = None
        claimed_message = False
        request_logged = False
        user_slot_acquired = False

        try:
            if await self._processed_message_repository.exists(incoming.chat_id, incoming.message_id, normalized.normalized_key):
                return True

            user_request_decision = await self._user_request_guard_service.try_acquire(incoming.user_id)
            if not user_request_decision.allowed:
                log_event(
                    self._logger,
                    logging.INFO,
                    "request_blocked",
                    request_id=request_id,
                    chat_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    normalized_key=normalized.normalized_key,
                    reason=user_request_decision.reason,
                )
                if user_request_decision.should_notify:
                    await self._safe_send_user_message(incoming.chat_id, messages.REQUEST_COOLDOWN, incoming.message_id)
                return True
            user_slot_acquired = True

            self._rate_limit_service.ensure_allowed(incoming.user_id)
            self._metrics.increment("requests_total")
            if not await self._processed_message_repository.claim(incoming.chat_id, incoming.message_id, normalized.normalized_key):
                return True
            claimed_message = True

            await self._request_log_repository.log_started(
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                message_id=incoming.message_id,
                normalized_key=normalized.normalized_key,
                original_url=normalized.original_url,
            )
            request_logged = True

            request = MediaRequest(
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                message_id=incoming.message_id,
                chat_type=incoming.chat_type,
                message_text=incoming.text,
                normalized_resource=normalized,
            )
            loading_message_id = await self._delivery_service.send_loading_text(incoming.chat_id, loading_text, incoming.message_id)
            result = await pipeline_runner(request)
            success = result.delivery_status.value != "failed"
            delivery_status = result.delivery_status.value
            cache_hit = result.cache_hit
            return True
        except AppError as exc:
            error_code = exc.error_code
            if exc.user_message:
                await self._safe_send_user_message(incoming.chat_id, exc.user_message, incoming.message_id)
            log_event(
                self._logger,
                logging.ERROR,
                "request_failed",
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                normalized_key=normalized.normalized_key,
                error_code=exc.error_code,
            )
            return True
        except Exception:
            self._logger.exception("unexpected_error_traceback")
            error_code = "unexpected_error"
            await self._safe_send_user_message(incoming.chat_id, messages.UNKNOWN_ERROR, incoming.message_id)
            log_event(
                self._logger,
                logging.ERROR,
                "request_failed",
                request_id=request_id,
                chat_id=incoming.chat_id,
                user_id=incoming.user_id,
                normalized_key=normalized.normalized_key,
                error_code=error_code,
            )
            return True
        finally:
            if loading_message_id is not None:
                try:
                    await self._delivery_service.delete_loading(incoming.chat_id, loading_message_id)
                except Exception:
                    pass
            if claimed_message:
                try:
                    await self._processed_message_repository.mark_finished(
                        incoming.chat_id,
                        incoming.message_id,
                        normalized.normalized_key,
                        success=success,
                    )
                except Exception as exc:
                    log_event(
                        self._logger,
                        logging.ERROR,
                        "processed_message_finalize_failed",
                        request_id=request_id,
                        chat_id=incoming.chat_id,
                        user_id=incoming.user_id,
                        normalized_key=normalized.normalized_key,
                        error=str(exc),
                    )
            if request_logged:
                try:
                    await self._request_log_repository.log_finished(
                        request_id,
                        success=success,
                        delivery_status=delivery_status,
                        cache_hit=cache_hit,
                        error_code=error_code,
                    )
                except Exception as exc:
                    log_event(
                        self._logger,
                        logging.ERROR,
                        "request_log_finalize_failed",
                        request_id=request_id,
                        chat_id=incoming.chat_id,
                        user_id=incoming.user_id,
                        normalized_key=normalized.normalized_key,
                        error=str(exc),
                    )
            if user_slot_acquired:
                try:
                    await self._user_request_guard_service.release(incoming.user_id)
                except Exception as exc:
                    log_event(
                        self._logger,
                        logging.ERROR,
                        "user_slot_release_failed",
                        request_id=request_id,
                        chat_id=incoming.chat_id,
                        user_id=incoming.user_id,
                        normalized_key=normalized.normalized_key,
                        error=str(exc),
                    )

    def _detect_provider(self, text: str) -> tuple[DownloaderProvider | None, str | None]:
        for provider in self._providers:
            detected_url = provider.extract_first_url(text)
            if detected_url:
                return provider, detected_url
        return None, None

    async def _safe_send_user_message(self, chat_id: int, text: str, reply_to_message_id: int | None) -> None:
        try:
            await self._delivery_service.send_text(chat_id, text, reply_to_message_id)
        except Exception as exc:
            log_event(
                self._logger,
                logging.ERROR,
                "user_message_send_failed",
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                error=str(exc),
            )
