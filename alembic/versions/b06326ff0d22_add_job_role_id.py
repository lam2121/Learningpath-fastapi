"""add job_role_id columns (user, course, placement_test_question)

Revision ID: b06326ff0d22
Revises: fe13e2a137d7
Create Date: 2026-08-06

NOTE: This revision was referenced by c0a1b2e3f4a5 (v2.1 admin generator A)
as its parent but the file was never committed to the repository, which broke
the migration chain (`alembic upgrade head` could not resolve it). The schema
changes it originally contained (`job_role_id` on `user`, `course`,
`placement_test_question`) are ALREADY present via the base migration
`66b193382d66` and the live database, so this revision is intentionally a
no-op. It exists only to repair the chain so `alembic upgrade head` works on
fresh installs and on this machine after `alembic stamp b06326ff0d22`.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b06326ff0d22"
down_revision: Union[str, None] = "fe13e2a137d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: job_role_id columns already exist (base migration + live DB).
    pass


def downgrade() -> None:
    # No-op: nothing to reverse.
    pass
