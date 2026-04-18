"""add music cache metadata fields

Revision ID: 20260418_0002
Revises: 20260417_0001
Create Date: 2026-04-18 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0002"
down_revision = "20260417_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_cache", sa.Column("raw_query", sa.Text(), nullable=True))
    op.add_column("media_cache", sa.Column("source_id", sa.String(length=128), nullable=True))
    op.add_column("media_cache", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("media_cache", sa.Column("performer", sa.Text(), nullable=True))
    op.add_column("media_cache", sa.Column("thumbnail_url", sa.Text(), nullable=True))
    op.add_column("media_cache", sa.Column("has_thumbnail", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("media_cache", sa.Column("file_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_cache", "file_name")
    op.drop_column("media_cache", "has_thumbnail")
    op.drop_column("media_cache", "thumbnail_url")
    op.drop_column("media_cache", "performer")
    op.drop_column("media_cache", "title")
    op.drop_column("media_cache", "source_id")
    op.drop_column("media_cache", "raw_query")
