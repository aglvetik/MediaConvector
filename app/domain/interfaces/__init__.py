from app.domain.interfaces.provider import DownloaderProvider
from app.domain.interfaces.repositories import (
    CacheRepository,
    DownloadJobRepository,
    ProcessedMessageRepository,
    RequestLogRepository,
)
from app.domain.interfaces.telegram_gateway import TelegramGateway

__all__ = [
    "CacheRepository",
    "DownloadJobRepository",
    "DownloaderProvider",
    "ProcessedMessageRepository",
    "RequestLogRepository",
    "TelegramGateway",
]
