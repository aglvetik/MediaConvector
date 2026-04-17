"""initial schema

Revision ID: 20260417_0001
Revises:
Create Date: 2026-04-17 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("video_file_id", sa.Text(), nullable=True),
        sa.Column("audio_file_id", sa.Text(), nullable=True),
        sa.Column("video_file_unique_id", sa.Text(), nullable=True),
        sa.Column("audio_file_unique_id", sa.Text(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("video_size_bytes", sa.Integer(), nullable=True),
        sa.Column("audio_size_bytes", sa.Integer(), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cache_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_key"),
    )
    op.create_index("ix_media_cache_platform", "media_cache", ["platform"])
    op.create_index("ix_media_cache_normalized_key", "media_cache", ["normalized_key"])
    op.create_index("ix_media_cache_status", "media_cache", ["status"])
    op.create_index("ix_media_cache_is_valid", "media_cache", ["is_valid"])

    op.create_table(
        "request_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_request_log_request_id", "request_log", ["request_id"])
    op.create_index("ix_request_log_chat_id", "request_log", ["chat_id"])
    op.create_index("ix_request_log_user_id", "request_log", ["user_id"])
    op.create_index("ix_request_log_normalized_key", "request_log", ["normalized_key"])
    op.create_index("ix_request_log_chat_message", "request_log", ["chat_id", "message_id"])

    op.create_table(
        "download_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_download_jobs_request_id", "download_jobs", ["request_id"])
    op.create_index("ix_download_jobs_normalized_key", "download_jobs", ["normalized_key"])
    op.create_index("ix_download_jobs_status", "download_jobs", ["status"])

    op.create_table(
        "processed_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("normalized_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "message_id", "normalized_key", name="uq_processed_message_identity"),
    )
    op.create_index("ix_processed_messages_status", "processed_messages", ["status"])


def downgrade() -> None:
    op.drop_index("ix_processed_messages_status", table_name="processed_messages")
    op.drop_table("processed_messages")

    op.drop_index("ix_download_jobs_status", table_name="download_jobs")
    op.drop_index("ix_download_jobs_normalized_key", table_name="download_jobs")
    op.drop_index("ix_download_jobs_request_id", table_name="download_jobs")
    op.drop_table("download_jobs")

    op.drop_index("ix_request_log_chat_message", table_name="request_log")
    op.drop_index("ix_request_log_normalized_key", table_name="request_log")
    op.drop_index("ix_request_log_user_id", table_name="request_log")
    op.drop_index("ix_request_log_chat_id", table_name="request_log")
    op.drop_index("ix_request_log_request_id", table_name="request_log")
    op.drop_table("request_log")

    op.drop_index("ix_media_cache_is_valid", table_name="media_cache")
    op.drop_index("ix_media_cache_status", table_name="media_cache")
    op.drop_index("ix_media_cache_normalized_key", table_name="media_cache")
    op.drop_index("ix_media_cache_platform", table_name="media_cache")
    op.drop_table("media_cache")
