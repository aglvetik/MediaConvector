"""add tiktok resource type and photo cache fields

Revision ID: 20260418_0006
Revises: 20260418_0005
Create Date: 2026-04-18 23:59:30.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0006"
down_revision = "20260418_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_cache") as batch_op:
        batch_op.add_column(sa.Column("resource_type", sa.String(length=32), nullable=False, server_default="video"))
        batch_op.add_column(sa.Column("photo_file_ids", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("photo_file_unique_ids", sa.Text(), nullable=True))
        batch_op.create_index("ix_media_cache_resource_type", ["resource_type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("media_cache") as batch_op:
        batch_op.drop_index("ix_media_cache_resource_type")
        batch_op.drop_column("photo_file_unique_ids")
        batch_op.drop_column("photo_file_ids")
        batch_op.drop_column("resource_type")
