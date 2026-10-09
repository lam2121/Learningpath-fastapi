-- ==============================================================================
-- Deploy Bridge Script: Run on MySQL BEFORE 'alembic stamp --purge 0002_uq_user_lesson'
-- ==============================================================================
-- Purpose:
-- 1. Pre-check existing state (alembic revision & table existence).
-- 2. Check column types and signedness of foreign-key parent columns.
-- 3. Widen alembic_version.version_num so revision 0004 (35 chars) does not truncate.
-- 4. Create tables present in NEW 0001_initial_schema but missing from old migrations.
-- 5. Make placement_test_question.quiz_type_id nullable (legacy column in old schema).
-- 6. Verify table creation and column definitions.
-- 7. Update alembic_version only after verification passes.
-- ==============================================================================

-- ==============================================================================
-- PRE-CHECK SECTION: Run these queries FIRST.
-- ==============================================================================
-- 1. Check current alembic revision in DB:
SELECT * FROM `alembic_version`;

-- 2. Check if user_final_quiz or user_flashcard already exist:
SHOW TABLES LIKE 'user_final_quiz';
SHOW TABLES LIKE 'user_flashcard';
-- INSTRUCTION: If either table already exists in the target DB, do NOT run the
-- CREATE TABLE statements below until the existing table schema is compared
-- against 0001_initial_schema.py to avoid accidental schema divergence.

-- 3. Verify exact column types and signedness for FK parents (user.id and job_role.id):
SELECT 
    TABLE_NAME, 
    COLUMN_NAME, 
    COLUMN_TYPE, 
    IS_NULLABLE, 
    COLUMN_KEY
FROM information_schema.COLUMNS 
WHERE TABLE_SCHEMA = DATABASE() 
  AND TABLE_NAME IN ('user', 'job_role', 'role') 
  AND COLUMN_NAME = 'id';

-- if either shows 'unsigned', change user_id/job_role_id in the two CREATE TABLE statements to BIGINT UNSIGNED, matching 0001_initial_schema
-- ==============================================================================


-- ==============================================================================
-- BRIDGE DDL EXECUTION
-- ==============================================================================

-- (a) Widen version_num column on alembic_version table
ALTER TABLE `alembic_version` MODIFY COLUMN `version_num` VARCHAR(100) NOT NULL;

-- (b) Create user_final_quiz (exact definition from 0001_initial_schema)
CREATE TABLE IF NOT EXISTS `user_final_quiz` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `job_role_id` BIGINT NOT NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'locked' COMMENT 'locked | ready | passed | failed',
  `completed_at` DATETIME NULL,
  `progress` FLOAT NOT NULL DEFAULT 0,
  `unlocked_at` DATETIME NULL,
  `user_answers` JSON NULL COMMENT 'Latest attempt snapshot and active question bank',
  `attempt_count` INT NOT NULL DEFAULT 0,
  `failed_attempts` INT NOT NULL DEFAULT 0,
  `best_score_percent` FLOAT NOT NULL DEFAULT 0,
  `last_score_percent` FLOAT NOT NULL DEFAULT 0,
  `skill_scores` JSON NULL COMMENT 'Latest per-skill accuracy percentages e.g. {\'D_doc\': 85.0, ...}',
  `weakest_lesson_ids` JSON NULL COMMENT '[lesson_id_1, lesson_id_2] for review flag',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_final_quiz_user_role` (`user_id`, `job_role_id`),
  KEY `fk_ufq_user_idx` (`user_id`),
  KEY `fk_ufq_job_role_idx` (`job_role_id`),
  CONSTRAINT `fk_ufq_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_ufq_job_role` FOREIGN KEY (`job_role_id`) REFERENCES `job_role` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Per-user final graduation quiz state and attempts';

-- (c) Create user_flashcard (exact definition from 0001_initial_schema)
CREATE TABLE IF NOT EXISTS `user_flashcard` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL,
  `word_eng` VARCHAR(45) NOT NULL,
  `word_vi` VARCHAR(50) NULL,
  `word_ja` VARCHAR(150) NULL,
  `transcription` VARCHAR(45) NULL,
  `context` VARCHAR(500) NULL,
  `workspace_example` VARCHAR(500) NULL,
  PRIMARY KEY (`id`),
  KEY `fk_user_flashcard_1_idx` (`user_id`),
  UNIQUE KEY `uq_user_flashcard_user_word` (`user_id`, `word_eng`),
  CONSTRAINT `fk_user_flashcard_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- (d) Make legacy column quiz_type_id nullable on placement_test_question
-- Note: Matches signed BIGINT of parent quiz_type.id (sa.Column('id', mysql.BIGINT(), ...))
-- Old schema defined it as NOT NULL, but new codebase models do not insert it.
ALTER TABLE `placement_test_question` MODIFY COLUMN `quiz_type_id` BIGINT NULL;


-- ==============================================================================
-- VERIFICATION SECTION: Run these queries AFTER applying DDL above.
-- ==============================================================================
SHOW CREATE TABLE `alembic_version`;
SHOW CREATE TABLE `user_final_quiz`;
SHOW CREATE TABLE `user_flashcard`;
DESCRIBE `placement_test_question`;
-- ==============================================================================


-- ==============================================================================
-- RUN LAST, ONLY AFTER VERIFICATION PASSES
-- ==============================================================================
-- Update Alembic version row to 0002_uq_user_lesson:
-- CLI equivalent: alembic stamp --purge 0002_uq_user_lesson
-- Direct SQL execution:
UPDATE `alembic_version` SET `version_num` = '0002_uq_user_lesson';

-- Confirm the stamp:
SELECT * FROM `alembic_version`;
-- ==============================================================================
