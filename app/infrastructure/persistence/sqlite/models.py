from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.sqlite.base import Base, utcnow


class MediaCacheModel(Base):
    __tablename__ = "media_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    video_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_file_unique_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_file_unique_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    cache_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RequestLogModel(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_request_log_chat_message", "chat_id", "message_id"),
    )


class DownloadJobModel(Base):
    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedMessageModel(Base):
    __tablename__ = "processed_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", "normalized_key", name="uq_processed_message_identity"),
        Index("ix_processed_messages_status", "status"),
    )

