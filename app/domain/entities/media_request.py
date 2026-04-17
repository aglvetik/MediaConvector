from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.entities.normalized_resource import NormalizedResource


@dataclass(slots=True, frozen=True)
class MediaRequest:
    request_id: str
    chat_id: int
    user_id: int
    message_id: int
    chat_type: Literal["private", "group", "supergroup", "channel"]
    message_text: str
    normalized_resource: NormalizedResource

