from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.entities.media_result import DeliveryReceipt


class TelegramGateway(Protocol):
    @property
    def is_ready(self) -> bool:
        ...

    async def send_loading_message(self, chat_id: int, reply_to_message_id: int | None = None) -> int:
        ...

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        ...

    async def send_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        ...

    async def send_video_by_file_id(self, chat_id: int, file_id: str, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        ...

    async def send_audio_by_file_id(self, chat_id: int, file_id: str, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        ...

    async def send_video_by_upload(self, chat_id: int, file_path: Path, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        ...

    async def send_audio_by_upload(self, chat_id: int, file_path: Path, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        ...
