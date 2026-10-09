"""dedupe user_lesson and add unique constraint on (user_id, lesson_id)

Revision ID: 0002_uq_user_lesson
Revises: 0001_initial_schema
Create Date: 2026-10-07 16:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_uq_user_lesson'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Deduplicate any existing duplicate rows:
    #    Keep the row with highest progress, latest completed_at, and newest id.
    op.execute(
        """
        CREATE TEMPORARY TABLE user_lesson_keep AS
        SELECT id AS keep_id
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, lesson_id
                       ORDER BY progress DESC, completed_at DESC, id DESC
                   ) AS rn
            FROM user_lesson
        ) ranked
        WHERE rn = 1
        """
    )
    op.execute(
        """
        DELETE FROM user_lesson
        WHERE id NOT IN (SELECT keep_id FROM user_lesson_keep)
        """
    )
    op.execute("DROP TEMPORARY TABLE user_lesson_keep")

    # 2. Check and add unique constraint on (user_id, lesson_id) if not already existing
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_uqs = {c['name'] for c in insp.get_unique_constraints('user_lesson') if c.get('name')}
    existing_idxs = {idx['name'] for idx in insp.get_indexes('user_lesson') if idx.get('unique')}
    if 'uq_user_lesson_user_lesson' not in existing_uqs and 'uq_user_lesson_user_lesson' not in existing_idxs:
        op.create_unique_constraint(
            'uq_user_lesson_user_lesson', 'user_lesson', ['user_id', 'lesson_id']
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_uqs = {c['name'] for c in insp.get_unique_constraints('user_lesson') if c.get('name')}
    if 'uq_user_lesson_user_lesson' in existing_uqs:
        op.drop_constraint('uq_user_lesson_user_lesson', 'user_lesson', type_='unique')
