"""add user_roadmap (Phase A roadmap selection)

Revision ID: d1e2f3a4b5c6
Revises: f0b1c2d3e4f5
Create Date: 2026-08-09

The 8-topic per-user learning roadmap produced by app/core/roadmap.py
(spec §2.C). Pure backend, zero AI. No per-user lesson table is created — the
legacy `user_lesson` table is left untouched; assigned lessons are derived at
runtime from the role pool (deterministic per (user_id, role_id)).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "f0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_roadmap",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(), nullable=False),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "track",
            sa.String(length=20),
            nullable=False,
            comment="basic | intermediate | advanced",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topic.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_user_roadmap_user_topic"),
        comment="8-topic learning roadmap per user (Phase A, zero AI)",
    )
    op.create_index("fk_user_roadmap_user_idx", "user_roadmap", ["user_id"])
    op.create_index("fk_user_roadmap_topic_idx", "user_roadmap", ["topic_id"])


def downgrade() -> None:
    op.drop_index("fk_user_roadmap_topic_idx", table_name="user_roadmap")
    op.drop_index("fk_user_roadmap_user_idx", table_name="user_roadmap")
    op.drop_table("user_roadmap")
