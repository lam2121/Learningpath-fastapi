"""add avatar_path column to user table

Revision ID: 0003_user_avatar_path
Revises: 0002_uq_user_lesson
Create Date: 2026-10-08 11:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_user_avatar_path'
down_revision: Union[str, None] = '0002_uq_user_lesson'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user',
        sa.Column('avatar_path', sa.String(500), nullable=True, default=None),
    )


def downgrade() -> None:
    op.drop_column('user', 'avatar_path')
