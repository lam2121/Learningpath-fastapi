"""Add expanded_skill column to placement_test_question

Revision ID: b4c5d6e7f8a9
Revises: a3f1d2e4c5b6
Create Date: 2026-08-17

Adds a nullable VARCHAR(45) column `expanded_skill` to the
`placement_test_question` table. Valid values are:
  - 'Context_layer'
  - 'Language_layer'
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3f1d2e4c5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'placement_test_question',
        sa.Column(
            'expanded_skill',
            sa.String(length=45),
            nullable=True,
            comment='Context_layer|Language_layer',
        ),
    )


def downgrade() -> None:
    op.drop_column('placement_test_question', 'expanded_skill')
