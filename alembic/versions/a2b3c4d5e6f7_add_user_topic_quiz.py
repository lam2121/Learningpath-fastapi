"""add user_topic_quiz (spec §4.2)

Revision ID: a2b3c4d5e6f7
Revises: f1e2d3c4b5a6
Create Date: 2026-09-07

User topic quiz attempts and pass state (§4.2, zero AI).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1e2d3c4b5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_topic",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(), nullable=False),
        sa.Column("topic_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="unlocked",
            comment="unlocked | passed | failed",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_score_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_score_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "weakest_lesson_ids",
            sa.JSON(),
            nullable=True,
            comment="[lesson_id_1, lesson_id_2] for review flag",
        ),
        sa.Column(
            "user_answers",
            sa.JSON(),
            nullable=True,
            comment="Latest attempt snapshot and active question bank",
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
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
        sa.UniqueConstraint("user_id", "topic_id", name="uq_user_topic_quiz_user_topic"),
        comment="User topic quiz attempts and pass state (§4.2, zero AI)",
    )
    op.create_index("fk_user_topic_quiz_user_idx", "user_topic_quiz", ["user_id"])
    op.create_index("fk_user_topic_quiz_topic_idx", "user_topic_quiz", ["topic_id"])


def downgrade() -> None:
    op.drop_index("fk_user_topic_quiz_topic_idx", table_name="user_topic_quiz")
    op.drop_index("fk_user_topic_quiz_user_idx", table_name="user_topic_quiz")
    op.drop_table("user_topic")
