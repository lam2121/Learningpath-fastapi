"""remove_user_age

Revision ID: 748e32f22e5c
Revises: fe13e2a137d7
Create Date: 2026-07-30 08:53:10.578297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '748e32f22e5c'
down_revision: Union[str, None] = 'fe13e2a137d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user', 'age')


def downgrade() -> None:
    op.add_column('user', sa.Column('age', mysql.VARCHAR(length=150), nullable=True))
