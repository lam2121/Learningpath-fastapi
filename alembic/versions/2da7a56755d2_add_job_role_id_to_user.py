"""Add job_role_id and is_finished_placement_test to user; drop is_finished_survey

Revision ID: 2da7a56755d2
Revises: 748e32f22e5c
Create Date: 2026-07-30 10:21:02.761174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '2da7a56755d2'
down_revision: Union[str, None] = '748e32f22e5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add job_role_id column to user table
    op.add_column('user', sa.Column(
        'job_role_id',
        sa.BigInteger(),
        sa.ForeignKey('job_role.id', ondelete='SET NULL'),
        nullable=True,
        comment='Selected job role from placement test'
    ))
    # Add is_finished_placement_test column
    op.add_column('user', sa.Column(
        'is_finished_placement_test',
        sa.Boolean(),
        server_default=sa.text('0'),
        nullable=False,
        comment='Whether user has completed the placement test'
    ))
    # Drop old is_finished_survey column
    op.drop_column('user', 'is_finished_survey')
    # Fix answer column type (already JSON from earlier migration)
    op.alter_column('survey_user', 'answer',
               existing_type=mysql.JSON(),
               nullable=False)
    op.alter_column('user', 'hashed_password',
               existing_type=mysql.VARCHAR(length=256),
               type_=sa.String(length=255),
               existing_nullable=False)


def downgrade() -> None:
    # Restore is_finished_survey
    op.add_column('user', sa.Column(
        'is_finished_survey',
        mysql.TINYINT(display_width=1),
        server_default=sa.text('0'),
        nullable=False
    ))
    # Drop is_finished_placement_test
    op.drop_column('user', 'is_finished_placement_test')
    # Drop job_role_id
    op.drop_column('user', 'job_role_id')
    op.alter_column('user', 'hashed_password',
               existing_type=sa.String(length=255),
               type_=mysql.VARCHAR(length=256),
               existing_nullable=False)
    op.alter_column('survey_user', 'answer',
               existing_type=mysql.JSON(),
               nullable=True)
