"""placement_test_question level column: int -> varchar(45)

Revision ID: a3f1d2e4c5b6
Revises: b9cdd3bc64c4
Create Date: 2026-08-17

The level column was originally created as INTEGER (values 1-8).
It should store plain difficulty strings: 'Easy' | 'Medium' | 'Hard' | 'Expert'
so the frontend adaptive engine can match them directly without any mapping.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'a3f1d2e4c5b6'
down_revision: Union[str, None] = 'b9cdd3bc64c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'placement_test_question',
        'level',
        existing_type=mysql.INTEGER(),
        type_=sa.String(length=45),
        comment='Easy|Medium|Hard|Expert',
        existing_comment='1-8',
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'placement_test_question',
        'level',
        existing_type=sa.String(length=45),
        type_=mysql.INTEGER(),
        comment='1-8',
        existing_comment='Easy|Medium|Hard|Expert',
        existing_nullable=False,
    )
