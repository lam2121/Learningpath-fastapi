"""consolidate role baseline into single JSON column

Revision ID: d5e4f3a2b1c0
Revises: c0a1b2e3f4a5
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e4f3a2b1c0"
down_revision: str | None = "c0a1b2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the consolidated baseline JSON blob, backfilled from the
    # individual baseline_d/c/t/g columns, then drop the legacy columns.
    op.add_column("job_role", sa.Column("baseline", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE job_role SET baseline = JSON_OBJECT("
        "'D_doc', baseline_d, "
        "'C_comm', baseline_c, "
        "'T_trouble', baseline_t, "
        "'G_custom', baseline_g"
        ")"
    )

    op.alter_column("job_role", "baseline", existing_type=sa.JSON(), nullable=False)

    op.drop_column("job_role", "baseline_g")
    op.drop_column("job_role", "baseline_t")
    op.drop_column("job_role", "baseline_c")
    op.drop_column("job_role", "baseline_d")
    op.drop_column("job_role", "init_weights")
    op.drop_column("job_role", "seed_tier")
    op.drop_column("job_role", "JD")


def downgrade() -> None:
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
    op.add_column("job_role", sa.Column("JD", mysql.LONGTEXT(), nullable=True))
    op.add_column("job_role", sa.Column("seed_tier", sa.JSON(), nullable=True))
    op.add_column("job_role", sa.Column("init_weights", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE job_role SET "
        "baseline_d = JSON_UNQUOTE(JSON_EXTRACT(baseline, '$.D_doc')), "
        "baseline_c = JSON_UNQUOTE(JSON_EXTRACT(baseline, '$.C_comm')), "
        "baseline_t = JSON_UNQUOTE(JSON_EXTRACT(baseline, '$.T_trouble')), "
        "baseline_g = JSON_UNQUOTE(JSON_EXTRACT(baseline, '$.G_custom'))"
    )

    op.drop_column("job_role", "baseline")
