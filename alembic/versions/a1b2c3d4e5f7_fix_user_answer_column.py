"""dedupe user_lesson and add unique constraint on (user_id, lesson_id)

Revision ID: a1b2c3d4e5f7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-20
"""
from alembic import op


revision = "a1b2c3d4e5f7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) For any (user_id, lesson_id) with duplicate rows, keep the "best"
    #    one — highest progress, then most recently completed, then newest
    #    id — and delete the rest. This is a one-time cleanup for rows that
    #    were created before the unique constraint existed (e.g. from the
    #    race condition where a blank duplicate submit created a second row
    #    instead of updating the real one).
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

    # 2) Enforce one row per (user_id, lesson_id) going forward.
    op.create_unique_constraint(
        "uq_user_lesson_user_lesson", "user_lesson", ["user_id", "lesson_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_lesson_user_lesson", "user_lesson", type_="unique")