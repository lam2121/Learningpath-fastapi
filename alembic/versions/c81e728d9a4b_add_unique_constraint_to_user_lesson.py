"""add unique constraint to user_lesson

Revision ID: c81e728d9a4b
Revises: 824a0395a07f
Create Date: 2026-09-10 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c81e728d9a4b'
down_revision: Union[str, None] = '824a0395a07f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_user_lesson_user_lesson', 'user_lesson', ['user_id', 'lesson_id'])


def downgrade() -> None:
    op.drop_constraint('uq_user_lesson_user_lesson', 'user_lesson', type_='unique')
