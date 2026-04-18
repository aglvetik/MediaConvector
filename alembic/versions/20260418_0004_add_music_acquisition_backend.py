"""add music acquisition backend to media cache

Revision ID: 20260418_0004
Revises: 20260418_0003
Create Date: 2026-04-18 23:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0004"
down_revision = "20260418_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_cache", sa.Column("acquisition_backend", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("media_cache", "acquisition_backend")
