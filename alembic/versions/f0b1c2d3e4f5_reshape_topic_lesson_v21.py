"""reshape topic/lesson tables to v2.1 (Generator B1/B2)

Revision ID: f0b1c2d3e4f5
Revises: e6f5a4b3c2d1
Create Date: 2026-08-07

The v1-era topic/lesson tables were left untouched when Generators B1/B2 were
deferred. This revision reshapes them to spec §10 (single primary skill tag,
seed tier, difficulty tier, lazily-generated theory/quiz content).

Both tables were verified EMPTY before this revision was written, so no data
migration is needed and the legacy columns are dropped outright.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0b1c2d3e4f5"
down_revision: str | None = "e6f5a4b3c2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── topic ──────────────────────────────────────────────────────────────
    # Drop the legacy course link (and its auto-created index) first.
    op.drop_constraint("fk_topic_course", "topic", type_="foreignkey")
    op.drop_index("fk_topic_course_idx", table_name="topic")

    op.drop_column("topic", "course_id")
    op.drop_column("topic", "business_level")
    op.drop_column("topic", "skill_weight")
    op.drop_column("topic", "english_level")

    op.add_column("topic", sa.Column("role_id", mysql.BIGINT(), nullable=False))
    op.create_foreign_key(
        "fk_topic_job_role",
        "topic",
        "job_role",
        ["role_id"],
        ["id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_index("fk_topic_job_role_idx", "topic", ["role_id"])

    op.add_column(
        "topic",
        sa.Column(
            "primary_skill",
            sa.String(length=45),
            nullable=False,
            comment="D_doc | C_comm | T_trouble | G_custom",
        ),
    )
    op.add_column(
        "topic",
        sa.Column(
            "seed_tier", sa.String(length=10), nullable=False, comment="tier_1|tier_2"
        ),
    )
    op.add_column("topic", sa.Column("sort_order", sa.Integer(), nullable=False))

    # ─── lesson ─────────────────────────────────────────────────────────────
    op.drop_column("lesson", "business_level")
    op.drop_column("lesson", "english_level")
    op.drop_column("lesson", "skill_weight")
    op.drop_column("lesson", "name")
    op.drop_column("lesson", "theory")

    op.add_column("lesson", sa.Column("title", sa.String(length=255), nullable=False))
    op.add_column(
        "lesson",
        sa.Column(
            "primary_skill",
            sa.String(length=45),
            nullable=False,
            comment="D_doc | C_comm | T_trouble | G_custom",
        ),
    )
    op.add_column(
        "lesson",
        sa.Column(
            "difficulty_tier",
            sa.String(length=20),
            nullable=False,
            comment="basic|intermediate|advanced",
        ),
    )
    op.add_column("lesson", sa.Column("theory_content", sa.JSON(), nullable=True))
    op.add_column("lesson", sa.Column("quiz_content", sa.JSON(), nullable=True))
    op.add_column(
        "lesson",
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    # ─── lesson (restore legacy v1 columns, best-effort) ────────────────────
    op.drop_column("lesson", "is_generated")
    op.drop_column("lesson", "quiz_content")
    op.drop_column("lesson", "theory_content")
    op.drop_column("lesson", "difficulty_tier")
    op.drop_column("lesson", "primary_skill")
    op.drop_column("lesson", "title")
    op.add_column("lesson", sa.Column("theory", sa.JSON(), nullable=True))
    op.add_column(
        "lesson",
        sa.Column("name", sa.String(length=45), nullable=False, server_default=""),
    )
    op.add_column("lesson", sa.Column("skill_weight", sa.JSON(), nullable=True))
    op.add_column(
        "lesson",
        sa.Column("english_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lesson",
        sa.Column("business_level", sa.Integer(), nullable=False, server_default="0"),
    )

    # ─── topic (restore legacy v1 columns, best-effort) ─────────────────────
    op.drop_index("fk_topic_job_role_idx", table_name="topic")
    op.drop_constraint("fk_topic_job_role", "topic", type_="foreignkey")
    op.drop_column("topic", "sort_order")
    op.drop_column("topic", "seed_tier")
    op.drop_column("topic", "primary_skill")
    op.drop_column("topic", "role_id")
    op.add_column(
        "topic",
        sa.Column("english_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("topic", sa.Column("skill_weight", sa.JSON(), nullable=True))
    op.add_column(
        "topic",
        sa.Column("business_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("topic", sa.Column("course_id", mysql.BIGINT(), nullable=True))
    op.create_foreign_key(
        "fk_topic_course",
        "topic",
        "course",
        ["course_id"],
        ["id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_index("fk_topic_course_idx", "topic", ["course_id"])
