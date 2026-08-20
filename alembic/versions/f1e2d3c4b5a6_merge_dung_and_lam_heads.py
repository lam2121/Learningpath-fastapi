"""merge dung and lam heads

Revision ID: f1e2d3c4b5a6
Revises: c5d6e7f8a9b0, 9c00f28fc86d
Create Date: 2026-08-20

This revision resolves the post-merge Alembic split between:
  - the dung branch (AI content generators + SSL fixes)
  - the lam branch (radar score + quiz scoring)

It is intentionally a no-op schema merge. The actual DDL lives in the parent
revisions; this file only collapses the migration graph back to a single head.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, tuple[str, str], None] = ("c5d6e7f8a9b0", "9c00f28fc86d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
