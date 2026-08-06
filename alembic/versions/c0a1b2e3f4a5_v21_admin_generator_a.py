"""v21 admin generator A - schema migration

Revision ID: c0a1b2e3f4a5
Revises: b06326ff0d22
Create Date: 2026-08-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "c0a1b2e3f4a5"
down_revision: Union[str, None] = "b06326ff0d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # job_role: add v2.1 columns, preserve legacy data where possible
    # ------------------------------------------------------------------
    op.add_column(
        "job_role", sa.Column("job_description", mysql.LONGTEXT(), nullable=True)
    )
    op.add_column(
        "job_role",
        sa.Column("baseline_d", sa.Integer(), server_default="25", nullable=False),
    )
    op.add_column(
        "job_role",
        sa.Column("baseline_c", sa.Integer(), server_default="25", nullable=False),
    )
    op.add_column(
        "job_role",
        sa.Column("baseline_t", sa.Integer(), server_default="25", nullable=False),
    )
    op.add_column(
        "job_role",
        sa.Column("baseline_g", sa.Integer(), server_default="25", nullable=False),
    )
    op.add_column(
        "job_role", sa.Column("g_skill_description", mysql.LONGTEXT(), nullable=True)
    )
    op.add_column("job_role", sa.Column("seed_tier_1", mysql.LONGTEXT(), nullable=True))
    op.add_column("job_role", sa.Column("seed_tier_2", mysql.LONGTEXT(), nullable=True))
    op.add_column(
        "job_role",
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
    )
    op.add_column("job_role", sa.Column("created_by", mysql.BIGINT(), nullable=True))

    # Copy legacy JD -> job_description, make legacy columns nullable
    op.execute("UPDATE job_role SET job_description = JD WHERE job_description IS NULL")
    op.alter_column("job_role", "JD", existing_type=mysql.LONGTEXT(), nullable=True)
    op.alter_column("job_role", "seed_tier", existing_type=sa.JSON(), nullable=True)
    op.alter_column("job_role", "init_weights", existing_type=sa.JSON(), nullable=True)
    op.alter_column(
        "job_role", "example_question", existing_type=sa.JSON(), nullable=True
    )

    op.create_foreign_key(
        "fk_job_role_created_by_user",
        "job_role",
        "user",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # placement_test_question: comment update only (String(45) holds v2.1 tags)
    # ------------------------------------------------------------------
    op.alter_column(
        "placement_test_question",
        "skill",
        existing_type=sa.String(length=45),
        comment="v2.1 tag: D_doc | C_comm | T_trouble | G_custom",
        existing_nullable=False,
    )
    op.alter_column(
        "placement_test_question",
        "level",
        existing_type=sa.Integer(),
        comment="1-8",
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # New tables: role_generation, ai_usage_log, rejected_content, system_setting
    # ------------------------------------------------------------------
    op.create_table(
        "role_generation",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("role_id", mysql.BIGINT(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("step", sa.String(length=10), server_default="a", nullable=False),
        sa.Column("step_a_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_a_errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_b1_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_b1_errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_b2_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_b2_errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["job_role.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Trang thai sinh noi dung theo role (Generator A/B1/B2)",
    )
    op.create_index(
        "fk_role_generation_job_role_idx", "role_generation", ["role_id"], unique=False
    )

    op.create_table(
        "ai_usage_log",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("generator", sa.String(length=10), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "completion_tokens", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="success", nullable=False
        ),
        sa.Column("role_id", mysql.BIGINT(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["job_role.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Log chi phi va token cua tung AI call (powers AI Costs page)",
    )
    op.create_index(
        "fk_ai_usage_log_job_role_idx", "ai_usage_log", ["role_id"], unique=False
    )

    op.create_table(
        "rejected_content",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("generator", sa.String(length=10), nullable=False),
        sa.Column("role_id", mysql.BIGINT(), nullable=True),
        sa.Column("input_preview", sa.String(length=500), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=False),
        sa.Column("raw_response", mysql.LONGTEXT(), nullable=True),
        sa.Column("validator_checks", sa.JSON(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["job_role.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Noi dung AI tra ve nhung khong qua duoc quality gates",
    )
    op.create_index(
        "fk_rejected_content_job_role_idx",
        "rejected_content",
        ["role_id"],
        unique=False,
    )

    op.create_table(
        "system_setting",
        sa.Column("id", mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", mysql.LONGTEXT(), nullable=False),
        sa.Column("updated_by", mysql.BIGINT(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
        comment="Key/value settings (single-row per key). ai_generation_enabled = false blocks generation",
    )

    # Seed default kill switch state: generation ENABLED
    op.execute(
        "INSERT INTO system_setting (`key`, value) VALUES ('ai_generation_enabled', 'true') ON DUPLICATE KEY UPDATE `key` = `key`"
    )


def downgrade() -> None:
    op.drop_table("system_setting")
    op.drop_index("fk_rejected_content_job_role_idx", table_name="rejected_content")
    op.drop_table("rejected_content")
    op.drop_index("fk_ai_usage_log_job_role_idx", table_name="ai_usage_log")
    op.drop_table("ai_usage_log")
    op.drop_index("fk_role_generation_job_role_idx", table_name="role_generation")
    op.drop_table("role_generation")

    op.drop_constraint("fk_job_role_created_by_user", "job_role", type_="foreignkey")
    op.drop_column("job_role", "created_by")
    op.drop_column("job_role", "is_active")
    op.drop_column("job_role", "seed_tier_2")
    op.drop_column("job_role", "seed_tier_1")
    op.drop_column("job_role", "g_skill_description")
    op.drop_column("job_role", "baseline_g")
    op.drop_column("job_role", "baseline_t")
    op.drop_column("job_role", "baseline_c")
    op.drop_column("job_role", "baseline_d")
    op.drop_column("job_role", "job_description")
    op.alter_column("job_role", "JD", existing_type=mysql.LONGTEXT(), nullable=False)
    op.alter_column("job_role", "seed_tier", existing_type=sa.JSON(), nullable=False)
    op.alter_column("job_role", "init_weights", existing_type=sa.JSON(), nullable=False)
    op.alter_column(
        "job_role", "example_question", existing_type=sa.JSON(), nullable=False
    )
    op.alter_column(
        "placement_test_question",
        "skill",
        existing_type=sa.String(length=45),
        comment=None,
        existing_comment="v2.1 tag: D_doc | C_comm | T_trouble | G_custom",
        existing_nullable=False,
    )
    op.alter_column(
        "placement_test_question",
        "level",
        existing_type=sa.Integer(),
        comment=None,
        existing_comment="1-8",
        existing_nullable=False,
    )
