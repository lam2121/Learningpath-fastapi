"""add_job_role_id_to_user

Revision ID: 2da7a56755d2
Revises: 
Create Date: 2026-07-30 10:21:02.761174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '2da7a56755d2'
down_revision: Union[str, None] = None
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
    op.alter_column('survey_user', 'answer',
               existing_type=mysql.JSON(),
               nullable=False)
    op.alter_column('user', 'hashed_password',
               existing_type=mysql.VARCHAR(length=256),
               type_=sa.String(length=255),
               existing_nullable=False)


def downgrade() -> None:
    op.drop_column('user', 'job_role_id')
    op.alter_column('user', 'hashed_password',
               existing_type=sa.String(length=255),
               type_=mysql.VARCHAR(length=256),
               existing_nullable=False)
    op.alter_column('survey_user', 'answer',
               existing_type=mysql.JSON(),
               nullable=True)
