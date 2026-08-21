"""update database

Revision ID: d9771538a9ad
Revises: a1b2c3d4e5f6
Create Date: 2026-08-12 16:32:07.487404

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'd9771538a9ad'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _has_foreign_key(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return constraint_name in {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, 'user_radar_score'):
        op.create_table('user_radar_score',
        sa.Column('id', mysql.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', mysql.BIGINT(), nullable=False),
        sa.Column('start_vector', sa.JSON(), nullable=False, comment='Diem goc luc bat dau course nay'),
        sa.Column('current_vector', sa.JSON(), nullable=True, comment='Diem hien tai thuoc ve lesson moi nhat'),
        sa.Column('prev_stack', sa.JSON(), nullable=False, comment='Mang luu cac lesson vector truoc do trong course'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], onupdate='CASCADE', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        inspector = inspect(bind)

    if not _has_index(inspector, 'user_radar_score', 'uq_user_radar_score'):
        op.create_index('uq_user_radar_score', 'user_radar_score', ['user_id'], unique=True)

    if _has_foreign_key(inspector, 'user_course_skill_vector', 'fk_ucsv_user_course'):
        op.drop_constraint('fk_ucsv_user_course', 'user_course_skill_vector', type_='foreignkey')
    if _has_index(inspector, 'user_course_skill_vector', 'uq_user_course_vector'):
        op.drop_index('uq_user_course_vector', table_name='user_course_skill_vector')
    if _has_table(inspector, 'user_course_skill_vector'):
        op.drop_table('user_course_skill_vector')

    op.alter_column('ai_usage_log', 'generator',
               existing_type=mysql.VARCHAR(length=10),
               comment='A/B1/B2',
               existing_nullable=False)
    op.alter_column('ai_usage_log', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment='success/retry/fallback/rejected',
               existing_nullable=False,
               existing_server_default=sa.text("'success'"))
    op.alter_column('job_role', 'name',
               existing_type=mysql.VARCHAR(length=100),
               type_=sa.String(length=45),
               existing_nullable=False)
    if _has_column(inspector, 'job_role', 'job_description'):
        op.alter_column('job_role', 'job_description',
                   existing_type=mysql.LONGTEXT(),
                   nullable=False)
    if _has_column(inspector, 'job_role', 'g_skill_description'):
        op.alter_column('job_role', 'g_skill_description',
                   existing_type=mysql.LONGTEXT(),
                   nullable=False)
    if _has_column(inspector, 'job_role', 'seed_tier_1'):
        op.alter_column('job_role', 'seed_tier_1',
                   existing_type=mysql.LONGTEXT(),
                   nullable=False)
    if _has_column(inspector, 'job_role', 'seed_tier_2'):
        op.alter_column('job_role', 'seed_tier_2',
                   existing_type=mysql.LONGTEXT(),
                   nullable=False)
    op.alter_column('lesson', 'difficulty_tier',
               existing_type=mysql.VARCHAR(length=20),
               comment='basic | intermediate | advanced',
               existing_comment='basic|intermediate|advanced',
               existing_nullable=False)
    op.create_table_comment(
        'lesson',
        'Lesson shells / Role, sinh boi Generator B2',
        existing_comment=None,
        schema=None
    )
    op.alter_column('rejected_content', 'generator',
               existing_type=mysql.VARCHAR(length=10),
               comment='A/B1/B2',
               existing_nullable=False)
    op.alter_column('rejected_content', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment='pending/fixed/ignored',
               existing_nullable=False,
               existing_server_default=sa.text("'pending'"))
    op.alter_column('role_generation', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment='pending/in_progress/completed/failed',
               existing_nullable=False,
               existing_server_default=sa.text("'pending'"))
    op.alter_column('role_generation', 'step',
               existing_type=mysql.VARCHAR(length=10),
               comment='a/b1/b2',
               existing_nullable=False,
               existing_server_default=sa.text("'a'"))
    op.alter_column('role_generation', 'step_a_count',
               existing_type=mysql.INTEGER(),
               comment='so cau hoi placement da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_a_errors',
               existing_type=mysql.INTEGER(),
               comment='so lan loi khi tao placement',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_b1_count',
               existing_type=mysql.INTEGER(),
               comment='so topics da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_b2_count',
               existing_type=mysql.INTEGER(),
               comment='so lesson shells da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('topic', 'seed_tier',
               existing_type=mysql.VARCHAR(length=10),
               comment='tier_1 | tier_2',
               existing_comment='tier_1|tier_2',
               existing_nullable=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('topic', 'seed_tier',
               existing_type=mysql.VARCHAR(length=10),
               comment='tier_1|tier_2',
               existing_comment='tier_1 | tier_2',
               existing_nullable=False)
    op.alter_column('role_generation', 'step_b2_count',
               existing_type=mysql.INTEGER(),
               comment=None,
               existing_comment='so lesson shells da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_b1_count',
               existing_type=mysql.INTEGER(),
               comment=None,
               existing_comment='so topics da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_a_errors',
               existing_type=mysql.INTEGER(),
               comment=None,
               existing_comment='so lan loi khi tao placement',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step_a_count',
               existing_type=mysql.INTEGER(),
               comment=None,
               existing_comment='so cau hoi placement da tao',
               existing_nullable=False,
               existing_server_default=sa.text("'0'"))
    op.alter_column('role_generation', 'step',
               existing_type=mysql.VARCHAR(length=10),
               comment=None,
               existing_comment='a/b1/b2',
               existing_nullable=False,
               existing_server_default=sa.text("'a'"))
    op.alter_column('role_generation', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment=None,
               existing_comment='pending/in_progress/completed/failed',
               existing_nullable=False,
               existing_server_default=sa.text("'pending'"))
    op.alter_column('rejected_content', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment=None,
               existing_comment='pending/fixed/ignored',
               existing_nullable=False,
               existing_server_default=sa.text("'pending'"))
    op.alter_column('rejected_content', 'generator',
               existing_type=mysql.VARCHAR(length=10),
               comment=None,
               existing_comment='A/B1/B2',
               existing_nullable=False)
    op.drop_table_comment(
        'lesson',
        existing_comment='Lesson shells / Role, sinh boi Generator B2',
        schema=None
    )
    op.alter_column('lesson', 'difficulty_tier',
               existing_type=mysql.VARCHAR(length=20),
               comment='basic|intermediate|advanced',
               existing_comment='basic | intermediate | advanced',
               existing_nullable=False)
    op.alter_column('job_role', 'seed_tier_2',
               existing_type=mysql.LONGTEXT(),
               nullable=True)
    op.alter_column('job_role', 'seed_tier_1',
               existing_type=mysql.LONGTEXT(),
               nullable=True)
    op.alter_column('job_role', 'g_skill_description',
               existing_type=mysql.LONGTEXT(),
               nullable=True)
    op.alter_column('job_role', 'job_description',
               existing_type=mysql.LONGTEXT(),
               nullable=True)
    op.alter_column('job_role', 'name',
               existing_type=sa.String(length=45),
               type_=mysql.VARCHAR(length=100),
               existing_nullable=False)
    op.alter_column('ai_usage_log', 'status',
               existing_type=mysql.VARCHAR(length=20),
               comment=None,
               existing_comment='success/retry/fallback/rejected',
               existing_nullable=False,
               existing_server_default=sa.text("'success'"))
    op.alter_column('ai_usage_log', 'generator',
               existing_type=mysql.VARCHAR(length=10),
               comment=None,
               existing_comment='A/B1/B2',
               existing_nullable=False)
    op.create_table('user_course_skill_vector',
    sa.Column('id', mysql.BIGINT(), autoincrement=True, nullable=False),
    sa.Column('user_course_id', mysql.BIGINT(), autoincrement=False, nullable=False),
    sa.Column('start_vector', mysql.JSON(), nullable=False, comment='Diem goc luc bat dau course nay'),
    sa.Column('current_vector', mysql.JSON(), nullable=True, comment='Diem hien tai thuoc ve lesson moi nhat'),
    sa.Column('prev_stack', mysql.JSON(), nullable=False, comment='Mang luu cac lesson vector truoc do trong course'),
    sa.Column('updated_at', mysql.DATETIME(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['user_course_id'], ['user_course.id'], name='fk_ucsv_user_course', onupdate='CASCADE', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_0900_ai_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    op.create_index('uq_user_course_vector', 'user_course_skill_vector', ['user_course_id'], unique=True)
    op.drop_index('uq_user_radar_score', table_name='user_radar_score')
    op.drop_table('user_radar_score')
    # ### end Alembic commands ###
