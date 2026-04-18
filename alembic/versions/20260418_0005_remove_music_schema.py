"""remove music-specific schema

Revision ID: 20260418_0005
Revises: 20260418_0004
Create Date: 2026-04-18 23:59:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0005"
down_revision = "20260418_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_cache") as batch_op:
        batch_op.drop_column("raw_query")
        batch_op.drop_column("source_id")
        batch_op.drop_column("title")
        batch_op.drop_column("performer")
        batch_op.drop_column("thumbnail_url")
        batch_op.drop_column("has_thumbnail")
        batch_op.drop_column("file_name")
        batch_op.drop_column("acquisition_backend")

    op.drop_index("ix_music_source_states_degraded_until", table_name="music_source_states")
    op.drop_index("ix_music_source_states_status", table_name="music_source_states")
    op.drop_table("music_source_states")


def downgrade() -> None:
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

    with op.batch_alter_table("media_cache") as batch_op:
        batch_op.add_column(sa.Column("raw_query", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("title", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("performer", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("thumbnail_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("has_thumbnail", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("file_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("acquisition_backend", sa.String(length=64), nullable=True))
