"""add user.learning_status; drop is_finished_placement_test

Revision ID: a1b2c3d4e5f6
Revises: d1e2f3a4b5c6
Create Date: 2026-08-10

Replaces the overloaded `is_finished_placement_test` boolean with a proper
learner-enrollment status. States:
  - 'none'     no track enrolled / placement not completed
  - 'enrolled' placement complete + track assigned + roadmap built
'graduated' can be added later when the study flow lands (docs/07 deviation #23).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEARNING_NONE = "none"
LEARNING_ENROLLED = "enrolled"


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "learning_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text(f"'{LEARNING_NONE}'"),
        ),
    )
    op.execute(
        sa.text(
            f"UPDATE `user` SET learning_status = '{LEARNING_ENROLLED}' "
            "WHERE is_finished_placement_test = 1"
        )
    )
    op.drop_column("user", "is_finished_placement_test")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "is_finished_placement_test",
            mysql.TINYINT(display_width=1),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
    )
    op.execute(
        sa.text(
            f"UPDATE `user` SET is_finished_placement_test = 1 "
            f"WHERE learning_status = '{LEARNING_ENROLLED}'"
        )
    )
    op.drop_column("user", "learning_status")
