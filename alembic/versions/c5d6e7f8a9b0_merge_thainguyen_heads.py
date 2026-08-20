"""merge thainguyen heads

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9, d9771538a9ad
Create Date: 2026-08-20

Joins the two divergent heads created by the thainguyen merge:
  - b4c5d6e7f8a9 (dung: level→VARCHAR + expanded_skill)
  - d9771538a9ad (thainguyen: user_radar_score + column comment cleanup)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = ['b4c5d6e7f8a9', 'd9771538a9ad']
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
