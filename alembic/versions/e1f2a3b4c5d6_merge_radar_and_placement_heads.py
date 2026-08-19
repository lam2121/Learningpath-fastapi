"""merge radar-score head with placement-question head

Revision ID: e1f2a3b4c5d6
Revises: d9771538a9ad, b4c5d6e7f8a9
Create Date: 2026-08-18

This revision resolves the post-merge Alembic split between:
  - the radar-score/schema cleanup branch
  - the placement-question level/expanded-skill branch

It is intentionally a no-op schema merge. The actual DDL lives in the parent
revisions; this file only collapses the migration graph back to a single head.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, tuple[str, str], None] = ("d9771538a9ad", "b4c5d6e7f8a9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
