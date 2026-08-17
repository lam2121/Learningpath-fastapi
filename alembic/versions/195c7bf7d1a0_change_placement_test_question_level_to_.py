"""change_placement_test_question_level_to_varchar

Revision ID: 195c7bf7d1a0
Revises: d9771538a9ad
Create Date: 2026-08-13 10:53:05.912144

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '195c7bf7d1a0'
down_revision: Union[str, None] = 'd9771538a9ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('placement_test_question', 'level',
               existing_type=mysql.INTEGER(),
               type_=sa.String(length=45),
               existing_comment='1-8',
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('placement_test_question', 'level',
               existing_type=sa.String(length=45),
               type_=mysql.INTEGER(),
               existing_comment='1-8',
               existing_nullable=False)
