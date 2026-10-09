# Aiven Fork Migration Rehearsal Plan

Follow this checklist on a temporary **Aiven MySQL fork** (or local copy) before touching production.

> [!CAUTION]
> **CRITICAL ENVIRONMENT ISOLATION WARNING:**  
> Run this rehearsal ONLY with a separate environment file (e.g., `.env.fork`) or temporary explicit shell environment variables pointing directly at the **Aiven fork**.  
> **NEVER** run these rehearsal commands against your live production database.  
> Verify your shell parameters before running any command!

---

## Pre-requisites & Fork Environment Setup

1. **Create a Service Fork in Aiven Console:**
   - In your Aiven project, create a fork of your MySQL service:
     - Example name: `careerpath-db-fork-rehearsal`
   - Wait until the fork status shows `RUNNING`.

2. **Obtain Fork Connection Parameters:**
   - Host: `<fork-host>.aivencloud.com`
   - Port: `<fork-port>`
   - User: `avnadmin` (or configured user)
   - Password: `<fork-password>`
   - DB Name: `toeic_learningpath`
   - CA Certificate: Download or use `./certs/ca.pem`.

3. **Configure Fork Environment Variables:**
   Create a temporary file `deploy/.env.fork` (or export in shell session):
   ```bash
   # Windows PowerShell:
   $env:DATABASE_URL="mysql+pymysql://<user>:<password>@<fork-host>:<port>/toeic_learningpath"
   $env:MYSQL_CA_CERT="./certs/ca.pem"

   # Linux / macOS / Bash:
   export DATABASE_URL="mysql+pymysql://<user>:<password>@<fork-host>:<port>/toeic_learningpath"
   export MYSQL_CA_CERT="./certs/ca.pem"
   ```

4. **Safety Pre-Check against the Fork:**
   Connect to the fork with MySQL CLI and inspect the starting state:
   ```sql
   -- Must show current old revision (e.g. c81e728d9a4b):
   SELECT * FROM `alembic_version`;

   -- Must NOT exist yet on live DB:
   SHOW TABLES LIKE 'user_final_quiz';
   SHOW TABLES LIKE 'user_flashcard';
   ```
   *If either `user_final_quiz` or `user_flashcard` already exists on the fork, stop and compare its columns against `alembic/versions/0001_initial_schema.py` before continuing.*

---

## Step 1: Execute Bridge SQL on the Fork

Run the updated bridge SQL script `deploy/bridge_before_stamp.sql` against the fork database:
```bash
mysql -h <fork-host> -P <port> -u <user> -p --ssl-ca=./certs/ca.pem toeic_learningpath < deploy/bridge_before_stamp.sql
```
Or execute the script contents via MySQL Workbench / DBeaver / Aiven Query Editor.

**Verification on the Fork:**
- Run `SELECT * FROM alembic_version;` -> Shows `0002_uq_user_lesson`.
- Run `SHOW CREATE TABLE alembic_version;` -> `version_num` is `varchar(100)`.
- Run `SHOW CREATE TABLE user_final_quiz;` -> Table exists and matches 0001 definition.
- Run `SHOW CREATE TABLE user_flashcard;` -> Table exists and matches 0001 definition.
- Run `DESCRIBE placement_test_question;` -> Column `quiz_type_id` has `Null: YES`.

---

## Step 2: Stamp Alembic Revision (CLI Verification)

If you executed the full bridge SQL script, `alembic_version` is already stamped to `0002_uq_user_lesson`.
To verify or execute via Alembic CLI against the fork:
```bash
# Note: --purge is REQUIRED because the old revision c81e728d9a4b no longer exists in alembic/versions/
alembic stamp --purge 0002_uq_user_lesson
```
**Verification:**
```sql
SELECT * FROM alembic_version;
-- Expected output: exactly 1 row with '0002_uq_user_lesson'
```

---

## Step 3: Upgrade to Head on the Fork

Apply the new revisions `0003_user_avatar_path` and `0004_lesson_is_generated_to_integer_`:
```bash
alembic upgrade head
```

**Verification:**
```sql
SELECT * FROM alembic_version;
-- Expected output: exactly 1 row with '0004_lesson_is_generated_to_integer'

DESCRIBE user;
-- Expected: column avatar_path exists (varchar(500) NULL)

DESCRIBE lesson;
-- Expected: column is_generated has type int (not tinyint(1))
```

---

## Step 4: Schema Diff Check (Alembic Autogenerate Dry Run)

Run an autogenerate dry run against the new SQLAlchemy models to verify schema equivalence:
```bash
alembic revision --autogenerate -m "rehearsal_dry_run"
```
Inspect the newly generated migration file in `alembic/versions/`:

### EXPECTED Diffs (Normal and Safe):
1. **Legacy Tables (Dropping):**
   - `op.drop_table('course')`
   - `op.drop_table('user_course')`
   - `op.drop_table('quiz')`
   - `op.drop_table('quiz_type')`
   - `op.drop_table('quiz_detail')`
2. **Legacy Column (Dropping):**
   - `op.drop_column('placement_test_question', 'quiz_type_id')`
3. **Missing Foreign Key (Adding):**
   - `op.create_foreign_key('fk_user_job_role', 'user', 'job_role', ['job_role_id'], ['id'])`

> [!CAUTION]
> **RED FLAG CHECK:**  
> If ANY other table (e.g., `user`, `lesson`, `queue`, `topic`, `job_role`, `user_lesson`, `user_final_quiz`, `user_flashcard`) shows unexpected column additions, drops, or type alterations, **STOP IMMEDIATELY**.  
> Delete the dry run file after inspection:
> ```bash
> rm alembic/versions/*rehearsal_dry_run*.py
> ```

---

## Step 5: Backend Smoke Test against the Fork

Start the FastAPI application against the fork database:
```bash
uvicorn app.main:app --port 8000
```
Smoke tests:
1. `GET http://localhost:8000/` -> returns `{"message": "Welcome to TOEIC Learning Path API!"}`
2. `GET http://localhost:8000/docs` -> Swagger UI loads properly.
3. `GET http://localhost:8000/api/onboarding/job-roles` -> Status 200 with job roles list.
4. `GET http://localhost:8000/api/user/me` with Bearer token -> Validates user profile & provisioning.
5. `GET http://localhost:8000/api/flashcard` -> Status 200 with flashcards list.
