"""add music source state tracking

Revision ID: 20260418_0003
Revises: 20260418_0002
Create Date: 2026-04-18 19:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0003"
down_revision = "20260418_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "music_source_states",
        sa.Column("source_name", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("consecutive_auth_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_auth_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("degraded_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_music_source_states_status", "music_source_states", ["status"])
    op.create_index("ix_music_source_states_degraded_until", "music_source_states", ["degraded_until"])


def downgrade() -> None:
    op.drop_index("ix_music_source_states_degraded_until", table_name="music_source_states")
    op.drop_index("ix_music_source_states_status", table_name="music_source_states")
    op.drop_table("music_source_states")
