"""Initial consolidated schema for CareerPath

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-09-21 11:15:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. role (independent) ────────────────────────────────────────────────
    op.create_table(
        'role',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('type', sa.String(length=150), nullable=False, comment='PM, BA, Tech Lead, SA, QA, DevOps...'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Danh muc vai tro cong viec',
    )

    # ── 2. system_setting (independent) ──────────────────────────────────────
    op.create_table(
        'system_setting',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', mysql.LONGTEXT(), nullable=False),
        sa.Column('updated_by', sa.BIGINT(), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
        comment='Key/value settings (single-row per key). ai_generation_enabled = false blocks generation',
    )

    # ── 3. job_role (created first without user FK to break circular dependency)
    op.create_table(
        'job_role',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=45), nullable=False),
        sa.Column('job_description', mysql.LONGTEXT(), nullable=False),
        sa.Column('baseline', sa.JSON(), nullable=False),
        sa.Column('skill_definitions', sa.JSON(), nullable=False),
        sa.Column('seed_tier_1', mysql.LONGTEXT(), nullable=False),
        sa.Column('seed_tier_2', mysql.LONGTEXT(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_by', sa.BIGINT(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── 4. user (depends on role and job_role) ────────────────────────────────
    op.create_table(
        'user',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('role_id', mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column('job_role_id', sa.BIGINT(), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('learning_status', sa.String(length=20), server_default=sa.text("'none'"), nullable=False),
        sa.Column('daily_study_minutes', sa.Integer(), server_default=sa.text('120'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], name='fk_user_role', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['job_role_id'], ['job_role.id'], name='fk_user_job_role', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='Nguoi dung he thong',
    )
    op.create_index('fk_user_role', 'user', ['role_id'], unique=False)
    op.create_index('email', 'user', ['email'], unique=True)

    # Add circular foreign key from job_role.created_by -> user.id
    op.create_foreign_key(
        'fk_job_role_created_by',
        'job_role',
        'user',
        ['created_by'],
        ['id'],
        ondelete='SET NULL',
    )

    # ── 5. topic (depends on job_role) ───────────────────────────────────────
    op.create_table(
        'topic',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.BIGINT(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('primary_skill', sa.String(length=45), nullable=False, comment='D_doc | C_comm | T_trouble | G_custom'),
        sa.Column('seed_tier', sa.String(length=10), nullable=False, comment='tier_1 | tier_2'),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['job_role.id'], name='fk_topic_job_role', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Pool 20 Topics / Role, sinh boi Generator B',
    )
    op.create_index('fk_topic_job_role_idx', 'topic', ['role_id'], unique=False)

    # ── 6. lesson (depends on topic) ─────────────────────────────────────────
    op.create_table(
        'lesson',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('topic_id', sa.BIGINT(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('primary_skill', sa.String(length=45), nullable=False, comment='D_doc | C_comm | T_trouble | G_custom'),
        sa.Column('difficulty_tier', sa.String(length=20), nullable=False, comment='basic | intermediate | advanced'),
        sa.Column('estimated_minutes', sa.Integer(), nullable=True),
        sa.Column('theory_content', sa.JSON(), nullable=True),
        sa.Column('quiz_content', sa.JSON(), nullable=True),
        sa.Column('is_generated', sa.Boolean(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name='fk_lesson_topic', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Lesson shells / Role, sinh boi Generator B2',
    )
    op.create_index('fk_lesson_topic_idx', 'lesson', ['topic_id'], unique=False)

    # ── 7. placement_test_question (depends on job_role) ────────────────────
    op.create_table(
        'placement_test_question',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('question', mysql.LONGTEXT(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('skill', sa.String(length=45), nullable=False, comment='v2.1 tag: D_doc | C_comm | T_trouble | G_custom'),
        sa.Column('level', sa.String(length=45), nullable=False, comment='Easy|Medium|Hard|Expert'),
        sa.Column('expanded_skill', sa.String(length=45), nullable=True, comment='Context_layer|Language_layer'),
        sa.Column('job_role_id', sa.BIGINT(), nullable=False),
        sa.ForeignKeyConstraint(['job_role_id'], ['job_role.id'], name='fk_placement_test_question_job_role', ondelete='NO ACTION', onupdate='NO ACTION'),
        sa.PrimaryKeyConstraint('id'),
        comment='Cau hoi test dau vao, sinh boi Generator A',
    )
    op.create_index('fk_placement_test_question_job_role_idx', 'placement_test_question', ['job_role_id'], unique=False)

    # ── 8. ai_usage_log (depends on job_role) ───────────────────────────────
    op.create_table(
        'ai_usage_log',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('generator', sa.String(length=10), nullable=False, comment='A/B1/B2'),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('completion_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_usd', sa.Float(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='success', nullable=False, comment='success/retry/fallback/rejected'),
        sa.Column('role_id', sa.BIGINT(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['job_role.id'], name='fk_ai_usage_log_job_role', ondelete='SET NULL', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Log chi phi va token cua tung AI call (powers AI Costs page)',
    )
    op.create_index('fk_ai_usage_log_job_role_idx', 'ai_usage_log', ['role_id'], unique=False)

    # ── 9. role_generation (depends on job_role) ────────────────────────────
    op.create_table(
        'role_generation',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.BIGINT(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False, comment='pending/in_progress/completed/failed'),
        sa.Column('step', sa.String(length=10), server_default='a', nullable=False, comment='a/b1/b2'),
        sa.Column('step_a_count', sa.Integer(), server_default='0', nullable=False, comment='so cau hoi placement da tao'),
        sa.Column('step_a_errors', sa.Integer(), server_default='0', nullable=False, comment='so lan loi khi tao placement'),
        sa.Column('step_b1_count', sa.Integer(), server_default='0', nullable=False, comment='so topics da tao'),
        sa.Column('step_b1_errors', sa.Integer(), server_default='0', nullable=False),
        sa.Column('step_b2_count', sa.Integer(), server_default='0', nullable=False, comment='so lesson shells da tao'),
        sa.Column('step_b2_errors', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['job_role.id'], name='fk_role_generation_job_role', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Trang thai sinh noi dung theo role (Generator A/B1/B2)',
    )
    op.create_index('fk_role_generation_job_role_idx', 'role_generation', ['role_id'], unique=False)

    # ── 10. rejected_content (depends on job_role) ───────────────────────────
    op.create_table(
        'rejected_content',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('generator', sa.String(length=10), nullable=False, comment='A/B1/B2'),
        sa.Column('role_id', sa.BIGINT(), nullable=True),
        sa.Column('input_preview', sa.String(length=500), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=False),
        sa.Column('raw_response', mysql.LONGTEXT(), nullable=True),
        sa.Column('validator_checks', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False, comment='pending/fixed/ignored'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['job_role.id'], name='fk_rejected_content_job_role', ondelete='SET NULL', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Noi dung AI tra ve nhung khong qua duoc quality gates',
    )
    op.create_index('fk_rejected_content_job_role_idx', 'rejected_content', ['role_id'], unique=False)

    # ── 11. queue (depends on user and lesson) ───────────────────────────────
    op.create_table(
        'queue',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('quiz_id', sa.BIGINT(), nullable=True),
        sa.Column('lesson_id', sa.BIGINT(), nullable=True),
        sa.Column('question_id', sa.String(length=50), nullable=True),
        sa.Column('question_type', sa.String(length=50), nullable=True),
        sa.Column('stem', sa.Text(), nullable=True),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('correct_answer', sa.Text(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('last_wrong_answer', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('next_review_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('last_reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('count', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_queue_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['lesson_id'], ['lesson.id'], name='fk_queue_lesson', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'lesson_id', 'question_id', name='uq_queue_user_lesson_question'),
        comment='Spaced repetition review queue for wrong quiz answers (toeicapp_spaced_rep_queue)',
    )
    op.create_index('fk_queue_user_idx', 'queue', ['user_id'], unique=False)
    op.create_index('fk_queue_lesson_idx', 'queue', ['lesson_id'], unique=False)

    # ── 12. user_lesson (depends on user and lesson) ─────────────────────────
    op.create_table(
        'user_lesson',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('lesson_id', sa.BIGINT(), nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('user_answers', sa.JSON(), nullable=False, comment='Luu ket qua 30 cau quiz cua lesson'),
        sa.Column('status', sa.String(length=20), server_default='locked', nullable=False, comment='locked / in_progress / completed'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('progress', sa.Float(), server_default='0', nullable=False),
        sa.Column('unlocked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_ul_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['lesson_id'], ['lesson.id'], name='fk_ul_lesson', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Quan ly trang thai va bai lam cua tung lesson le (Lazy Load)',
    )
    op.create_index('fk_ul_user_idx', 'user_lesson', ['user_id'], unique=False)
    op.create_index('fk_ul_lesson_idx', 'user_lesson', ['lesson_id'], unique=False)

    # ── 13. user_placement_test (depends on placement_test_question and user)
    op.create_table(
        'user_placement_test',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('placement_test_question_id', sa.BIGINT(), nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('user_answer', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['placement_test_question_id'], ['placement_test_question.id'], name='fk_user_placement_test_question'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_user_placement_test_user'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('fk_user_placement_test_1_idx', 'user_placement_test', ['user_id'], unique=False)
    op.create_index('fk_user_placement_test_2', 'user_placement_test', ['placement_test_question_id'], unique=False)

    # ── 14. user_radar_score (depends on user) ───────────────────────────────
    op.create_table(
        'user_radar_score',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('start_vector', sa.JSON(), nullable=False, comment='Diem goc luc bat dau course nay'),
        sa.Column('current_vector', sa.JSON(), nullable=True, comment='Diem hien tai thuoc ve lesson moi nhat'),
        sa.Column('prev_stack', sa.JSON(), nullable=False, comment='Mang luu cac lesson vector truoc do trong course'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_user_radar_score_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_user_radar_score', 'user_radar_score', ['user_id'], unique=True)

    # ── 15. user_roadmap (depends on user and topic) ─────────────────────────
    op.create_table(
        'user_roadmap',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('topic_id', sa.BIGINT(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('track', sa.String(length=20), nullable=False, comment='basic | intermediate | advanced'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_user_roadmap_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name='fk_user_roadmap_topic', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'topic_id', name='uq_user_roadmap_user_topic'),
        comment='8-topic learning roadmap per user (Phase A, zero AI)',
    )
    op.create_index('fk_user_roadmap_user_idx', 'user_roadmap', ['user_id'], unique=False)
    op.create_index('fk_user_roadmap_topic_idx', 'user_roadmap', ['topic_id'], unique=False)

    # ── 16. user_topic_quiz (depends on user and topic) ──────────────────────
    op.create_table(
        'user_topic_quiz',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('topic_id', sa.BIGINT(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='unlocked', nullable=False, comment='unlocked | passed | failed'),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('best_score_percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('last_score_percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('weakest_lesson_ids', sa.JSON(), nullable=True, comment='[lesson_id_1, lesson_id_2] for review flag'),
        sa.Column('user_answers', sa.JSON(), nullable=True, comment='Latest attempt snapshot and active question bank'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_user_topic_quiz_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], name='fk_user_topic_quiz_topic', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'topic_id', name='uq_user_topic_quiz_user_topic'),
        comment='User topic quiz attempts and pass state (§4.2, zero AI)',
    )
    op.create_index('fk_user_topic_quiz_user_idx', 'user_topic_quiz', ['user_id'], unique=False)
    op.create_index('fk_user_topic_quiz_topic_idx', 'user_topic_quiz', ['topic_id'], unique=False)

    # ── 17. user_final_quiz (depends on user and job_role) ───────────────────
    op.create_table(
        'user_final_quiz',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('job_role_id', sa.BIGINT(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='locked', nullable=False, comment='locked | ready | passed | failed'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('progress', sa.Float(), server_default='0', nullable=False),
        sa.Column('unlocked_at', sa.DateTime(), nullable=True),
        sa.Column('user_answers', sa.JSON(), nullable=True, comment='Latest attempt snapshot and active question bank'),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('best_score_percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('last_score_percent', sa.Float(), server_default='0', nullable=False),
        sa.Column('skill_scores', sa.JSON(), nullable=True, comment="Latest per-skill accuracy percentages e.g. {'D_doc': 85.0, ...}"),
        sa.Column('weakest_lesson_ids', sa.JSON(), nullable=True, comment='[lesson_id_1, lesson_id_2] for review flag'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_ufq_user', ondelete='CASCADE', onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['job_role_id'], ['job_role.id'], name='fk_ufq_job_role', ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'job_role_id', name='uq_user_final_quiz_user_role'),
        comment='Per-user final graduation quiz state and attempts',
    )
    op.create_index('fk_ufq_user_idx', 'user_final_quiz', ['user_id'], unique=False)
    op.create_index('fk_ufq_job_role_idx', 'user_final_quiz', ['job_role_id'], unique=False)

    # ── 18. user_flashcard (depends on user) ─────────────────────────────────
    op.create_table(
        'user_flashcard',
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BIGINT(), nullable=False),
        sa.Column('word_eng', sa.String(length=45), nullable=False),
        sa.Column('word_vi', sa.String(length=50), nullable=True),
        sa.Column('word_ja', sa.String(length=150), nullable=True),
        sa.Column('transcription', sa.String(length=45), nullable=True),
        sa.Column('context', sa.String(length=500), nullable=True),
        sa.Column('workspace_example', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_user_flashcard_user'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('fk_user_flashcard_1_idx', 'user_flashcard', ['user_id'], unique=False)
    op.create_index('uq_user_flashcard_user_word', 'user_flashcard', ['user_id', 'word_eng'], unique=True)


def downgrade() -> None:
    # Drop tables in reverse topological order
    op.drop_table('user_flashcard')
    op.drop_table('user_final_quiz')
    op.drop_table('user_topic_quiz')
    op.drop_table('user_roadmap')
    op.drop_table('user_radar_score')
    op.drop_table('user_placement_test')
    op.drop_table('user_lesson')
    op.drop_table('queue')
    op.drop_table('rejected_content')
    op.drop_table('role_generation')
    op.drop_table('ai_usage_log')
    op.drop_table('placement_test_question')
    op.drop_table('lesson')
    op.drop_table('topic')

    # Drop circular foreign key before dropping user / job_role
    op.drop_constraint('fk_job_role_created_by', 'job_role', type_='foreignkey')

    op.drop_table('user')
    op.drop_table('job_role')
    op.drop_table('system_setting')
    op.drop_table('role')
