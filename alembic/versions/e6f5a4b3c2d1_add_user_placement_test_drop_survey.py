"""add user_placement_test and drop survey tables

Revision ID: e6f5a4b3c2d1
Revises: d5e4f3a2b1c0
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f5a4b3c2d1"
down_revision: str | None = "d5e4f3a2b1c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Record user placement-test results (one row per answered question).
    op.create_table(
        "user_placement_test",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column(
            "placement_test_question_id",
            mysql.BIGINT(),
            nullable=False,
        ),
        sa.Column("user_id", mysql.BIGINT(), nullable=False),
        sa.Column("user_answer", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["placement_test_question_id"],
            ["placement_test_question.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "fk_user_placement_test_1_idx",
        "user_placement_test",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "fk_user_placement_test_2",
        "user_placement_test",
        ["placement_test_question_id"],
        unique=False,
    )

    # Survey has been removed from the product — drop its tables.
    # (Indexes are dropped implicitly with the tables; dropping them first
    # would fail while the FK constraints still reference them.)
    op.drop_table("survey_user")
    op.drop_table("survey")


def downgrade() -> None:
    op.create_table(
        "survey",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("content", mysql.LONGTEXT(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="Cau hoi Survey rating 1-10, ho tro deep-dive branching",
    )
    op.create_table(
        "survey_user",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("survey_id", mysql.BIGINT(), nullable=False),
        sa.Column("answer", sa.Integer(), nullable=False),
        sa.Column("user_id", mysql.BIGINT(), nullable=False),
        sa.ForeignKeyConstraint(["survey_id"], ["survey.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "fk_survey_user_survey_idx",
        "survey_user",
        ["survey_id"],
        unique=False,
    )
    op.create_index(
        "fk_survey_user_user_idx",
        "survey_user",
        ["user_id"],
        unique=False,
    )

    op.drop_index("fk_user_placement_test_2", table_name="user_placement_test")
    op.drop_index("fk_user_placement_test_1_idx", table_name="user_placement_test")
    op.drop_table("user_placement_test")
