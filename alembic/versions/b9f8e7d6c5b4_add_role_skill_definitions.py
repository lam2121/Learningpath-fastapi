"""add role skill definitions

Revision ID: b9f8e7d6c5b4
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14 15:30:00.000000
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b9f8e7d6c5b4"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


DEFAULT_SKILL_DESCRIPTIONS = {
    "D_doc": (
        "Ability to read and write clear, concise, and structured "
        "technical documentation."
    ),
    "C_comm": (
        "Effective verbal and written communication in professional "
        "IT contexts."
    ),
    "T_trouble": (
        "Skills in identifying, analyzing, and resolving technical issues."
    ),
    "G_custom": "Specific domain knowledge and expertise required for this role.",
}


def upgrade() -> None:
    op.add_column("job_role", sa.Column("skill_definitions", sa.JSON(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, g_skill_description, example_question FROM job_role ORDER BY id"
        )
    ).mappings()

    for row in rows:
        # `example_question` is a MySQL JSON column; a raw SELECT returns it as
        # a JSON-encoded string, so parse it back to a Python list before
        # embedding it in the new JSON blob (avoids double-encoding).
        raw_examples = row["example_question"] or []
        if isinstance(raw_examples, str):
            try:
                raw_examples = json.loads(raw_examples)
            except (ValueError, TypeError):
                raw_examples = []
        if not isinstance(raw_examples, list):
            raw_examples = []

        skill_definitions = {
            "D_doc": {
                "description": DEFAULT_SKILL_DESCRIPTIONS["D_doc"],
                "example_questions": [],
            },
            "C_comm": {
                "description": DEFAULT_SKILL_DESCRIPTIONS["C_comm"],
                "example_questions": [],
            },
            "T_trouble": {
                "description": DEFAULT_SKILL_DESCRIPTIONS["T_trouble"],
                "example_questions": [],
            },
            "G_custom": {
                "description": (
                    row["g_skill_description"]
                    or DEFAULT_SKILL_DESCRIPTIONS["G_custom"]
                ),
                "example_questions": raw_examples,
            },
        }
        conn.execute(
            sa.text(
                "UPDATE job_role SET skill_definitions = :skill_definitions WHERE id = :id"
            ),
            {
                "id": row["id"],
                "skill_definitions": json.dumps(skill_definitions, ensure_ascii=False),
            },
        )

    op.alter_column(
        "job_role", "skill_definitions", existing_type=sa.JSON(), nullable=False
    )
    op.drop_column("job_role", "example_question")
    op.drop_column("job_role", "g_skill_description")


def downgrade() -> None:
    op.add_column("job_role", sa.Column("g_skill_description", sa.Text(), nullable=True))
    op.add_column("job_role", sa.Column("example_question", sa.JSON(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, skill_definitions FROM job_role ORDER BY id")
    ).mappings()

    for row in rows:
        raw = row["skill_definitions"] or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        g_custom = raw.get("G_custom") or {}
        examples = g_custom.get("example_questions") or []
        if isinstance(examples, str):
            try:
                examples = json.loads(examples)
            except (ValueError, TypeError):
                examples = []
        if not isinstance(examples, list):
            examples = []
        conn.execute(
            sa.text(
                "UPDATE job_role "
                "SET g_skill_description = :g_skill_description, "
                "example_question = :example_question "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "g_skill_description": g_custom.get(
                    "description", DEFAULT_SKILL_DESCRIPTIONS["G_custom"]
                ),
                "example_question": json.dumps(examples, ensure_ascii=False),
            },
        )

    op.alter_column(
        "job_role", "g_skill_description", existing_type=sa.Text(), nullable=False
    )
    op.drop_column("job_role", "skill_definitions")
