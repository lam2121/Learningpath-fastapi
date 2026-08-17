"""merge lam (lesson/user minutes) and dung (skill definitions)

Revision ID: b9cdd3bc64c4
Revises: b9f8e7d6c5b4, c9d8e7f6a5b4
Create Date: 2026-08-14 14:34:44.414935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9cdd3bc64c4'
down_revision: Union[str, None] = ('b9f8e7d6c5b4', 'c9d8e7f6a5b4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
