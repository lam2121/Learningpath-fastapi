# careerpath-fastapi

# Signature - MUST NOT DELETE
- Dung - batch 52 was here
- Thai - batch 52 was here
- Lam - batch 52 was here
- An - batch 52 was here

> **CareerPath English** — AI-augmented TOEIC English learning platform backend.  
> FastAPI 0.110+ · SQLAlchemy 2.0 · MySQL 8 · Multi-Provider LLM Pool · OpenPronounce / Wav2Vec2  
> **Status**: Production-Ready · 21/21 Code Audit Findings Resolved · 88 End-to-End QA Tests Verified

---

## 🚀 Running the Service

```bash
cd careerpath-fastapi
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# System packages required by the pronunciation scorer & audio transcoding:
sudo apt install -y ffmpeg espeak-ng python3.10 python3.10-venv     # Debian/Ubuntu
# brew install ffmpeg espeak-ng                                      # macOS

pip install -r requirements.txt

cp .env.example .env              # then fill in MYSQL_PASSWORD, SECRET_KEY, and AI keys
alembic upgrade head
python -m app.seeds.seed_roles
python -m app.seeds.seed_job_roles
uvicorn app.main:app --reload --port 8000
# API Base: http://localhost:8000/api
# Swagger Docs: http://localhost:8000/api/docs
```

---

## 🗄️ Database Migrations (Alembic)

The database schema is managed via Alembic across 4 active schema revisions:
1. `0001_initial_schema.py`: Base 18-table relational schema.
2. `0002_uq_user_lesson.py`: Unique constraint `uq_user_lesson_user_lesson` on `(user_id, lesson_id)` preventing concurrent quiz submission race conditions.
3. `0003_user_avatar_path.py`: Adds `avatar_path` column to `user` table (served via `/api/static/uploads/avatars/...`).
4. `0004_lesson_is_generated_to_integer_.py`: Converts `lesson.is_generated` to tri-state integer (`-1 = failed`, `0 = pending`, `1 = completed`).

- **Fresh database setup** — apply all migrations from scratch:
  ```bash
  alembic upgrade head
  ```

- **Reset / Stamp existing database** — if your database already contains tables or encounters `Can't locate revision identified by '...'`:
  ```bash
  alembic stamp --purge head
  ```

- **Check current revision**:
  ```bash
  alembic current
  ```

- **Preview SQL without executing (offline mode)**:
  ```bash
  alembic upgrade head --sql
  ```

---

## ⚙️ Environment Configuration

Configuration lives in `.env` at the service root, next to this README. The path is relative, so **start the service from this directory** (`careerpath-fastapi/`).

Key names are case-sensitive and match the fields in `app/core/infra/config.py` exactly — provider keys are spelled `OpenRouter`, `Groq`, `Mistral`, `GEMINI_API_KEY`.

### Key Configuration Groups

| Group | Variables | Notes |
|---|---|---|
| **Database** | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` | PyMySQL driver with pooled connections |
| **Pool Sizing** | `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_CONNECT_TIMEOUT`, `DB_POOL_RECYCLE` | Hardened defaults: 10/25/15/30s/30s/1800s |
| **Redis** | `REDIS_URL` | Optional — multi-worker SSE Pub/Sub, rate limiting, caching |
| **JWT Auth** | `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AUTH_SERVICE_URL`, `AUTH_JWKS_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_SHARED_SECRET` | Validates against central TMA SSO (`https://english-practice.tma.com.vn/api/auth_test`) |
| **AI Providers** | `GEMINI_API_KEY`, `GEMINI_FLASH_MODEL`, `GEMINI_PRO_MODEL`, `GROQ_MODEL`, `Groq`, `Mistral`, `OpenRouter` | Gemini Flash 3.1, Gemini Pro 3.5, Groq gpt-oss-120b, Mistral, Gemma 4 31B |
| **Rate Limiting** | SlowAPI per IP/User | `/api/audio/voices`: 30/m, `/tts/stream`: 20/m, `/tts/generate`: 15/m, `/stt`: 10/m, `/pronunciation`: 5/m |
| **C-1 Quality Gates** | `C1_MIN_VOCAB`, `C1_MIN_PATTERNS`, `C1_MIN_DIALOGUE_KEY_PHRASES` | Relaxed defaults (6/2/1) for free-tier fallbacks |
| **TLS** | `SSL_CERT_FILE`, `SSL_CERT_DIR`, `DISABLE_SSL_VERIFY` | For corporate TLS proxy environments |
| **Pronunciation** | `PRONUNCIATION_MAX_CONCURRENCY`, `PRONUNCIATION_QUEUE_TIMEOUT_SECONDS`, `PRONUNCIATION_MAX_AUDIO_SECONDS`, `PRONUNCIATION_TORCH_THREADS`, `PRONUNCIATION_PRELOAD_MODELS` | Bounded CPU concurrency (max 1 worker, 2 torch threads) |
| **Runtime** | `APP_ENV` | `development` enables dev utilities; `production` enforces strict security |

---

## 🏗️ Project Architecture

```
careerpath-fastapi/
├── app/
│   ├── main.py                    # FastAPI lifespan, CORS, SlowAPI, periodic cleanup
│   ├── api_router.py              # Central APIRouter mounting all feature routers
│   ├── core/
│   │   ├── infra/                 # Database, config, dependencies, SSE broker
│   │   ├── domain/                # Roadmap algorithm, learner reset, lesson duration
│   │   └── ai/                    # Multi-provider LLM pool & generation pipeline
│   │       ├── client/            # GeminiClientPool, cost, JWKS
│   │       ├── dispatch/          # Top-level generators & cross-domain prompts
│   │       ├── course/            # Generator B-1 (Outline) & B-2 (Lesson Shells)
│   │       ├── lesson/            # Generator C-1 (Theory) & C-2 (Quiz)
│   │       ├── placement/         # Generator A (48-question placement pool)
│   │       └── quiz/              # Topic & Final quiz prompt templates
│   ├── feature/                   # 8 modular feature packages
│   │   ├── admin/                 # Admin dashboard, cost analytics, generation kickoff
│   │   ├── audio/                 # TTS, STT, Wav2Vec2 pronunciation scoring
│   │   ├── flashcard/             # Vocabulary retention & personal decks
│   │   ├── onboarding/            # Career tracks & diagnostic placement
│   │   ├── quiz/                  # Lesson, Topic, and Final quizzes
│   │   ├── radar/                 # Competency radar tracking
│   │   ├── roadmap/               # Interactive curriculum navigation
│   │   └── user/                  # Learner profile, history & reviews
│   ├── models/                    # 18 SQLAlchemy 2.0 ORM models
│   └── seeds/                     # Database seed scripts
├── scripts/                       # CLI tools (complete_final_quiz, skip_topic_quiz)
├── tests/                         # Automated test suite
└── alembic/                       # Database migrations (4 revisions)
```

---

## 🧪 Testing & Quality Assurance

All features are documented in [**`doc/careerpath-qa-test-matrix.xlsx`**](../doc/careerpath-qa-test-matrix.xlsx) (88 end-to-end calibrated test cases).

```bash
# Run pytest verification suite
source venv/bin/activate
pytest tests/ -v
```

---

## 🔒 Code Audit & Security Hardening Status

The service has resolved all **21 code audit findings** documented in [**`doc/careerpath_code_audit.xlsx`**](../doc/careerpath_code_audit.xlsx) and [**`doc/PROJECT_OVERVIEW.md` (Section 13)**](../doc/PROJECT_OVERVIEW.md#13-code-audit-resolution--security-hardening-log):
- **Quiz Evaluation Security**: Quiz answer keys and explanations are completely stripped from client payloads until submission.
- **Access Control**: Administrative generation flags (`force=true`, `sync=true`) require `ADMIN_ROLE_ID = 2`.
- **Connection Safety**: DB sessions are closed prior to long async streaming or Wav2Vec2 CPU operations; pool sizes tuned to 10–25.
- **Memory Protection**: Audio uploads enforce a 10MB streaming byte cap (`await audio_file.read(MAX_AUDIO_FILE_SIZE + 1)`) before memory decoding.
- **Race Condition Guard**: Unique database constraint `uq_user_lesson_user_lesson` prevents duplicate quiz submissions.

---

## 🎤 Pronunciation Scoring

`POST /api/audio/pronunciation` scores a recording at the phoneme level with
[OpenPronounce](https://github.com/Halleck45/OpenPronounce) and generates coaching feedback using prompts F1/F2 (sentences) and F4/F5 (vocabulary words).

- **System packages:** `ffmpeg` (decodes webm/opus recordings) and `espeak-ng` (phonemizer backend).
- **Model weights:** Roughly 4.8 GB of Wav2Vec2 checkpoints from HuggingFace cached under `~/.cache/huggingface`. Set `PRONUNCIATION_PRELOAD_MODELS=true` to preload at startup.
- **CPU bounding:** Scoring concurrency is capped at `PRONUNCIATION_MAX_CONCURRENCY=1` and `PRONUNCIATION_TORCH_THREADS=2` to ensure the host remains responsive.

---

## 🔗 API Route Map

| Prefix | Router | Tags | Description |
|---|---|---|---|
| `/api/user` | `user_router` | User Profile | Learner profile, avatar, history, streak restore (`/me/streak`, `/me/streak/restore`), study goals |
| `/api/onboarding` | `job_role_router` | Onboarding | Career track selection & role management |
| `/api/onboarding` | `placement_router` | Onboarding - Placement | 48-question diagnostic placement test |
| `/api/onboarding` | `roadmap_router` | Curriculum Roadmap | 8-topic roadmap & lesson progression |
| `/api/onboarding` | `quiz_router` | Quizzes & Evaluation | Lesson, Topic & Final quiz sessions |
| `/api/admin` | `admin_router` | Admin | Track management, costs, logs, kill switch |
| `/api/audio` | `audio_router` | Audio | TTS, STT, pronunciation scoring (Rate-limited) |
| `/api/flashcard` | `flashcard_router` | Flashcard | Vocabulary retention & personal decks |

---

## 🛡️ Streak Restoration & Accumulation Engine

- **Rate / Requirement**: 120 minutes of study time = 1 streak restore credit (`DEFAULT_DAILY_STUDY_MINUTES = 120`).
- **Accumulation Mechanics ("Cộng dồn")**:
  - **Study Time Banking**: Minutes accumulate continuously across study sessions and days (`floor(total_studied_minutes / 120)`). Credits never expire.
  - **Cumulative Day Restoration**: Learners who missed multiple days can restore them consecutively or in bulk ("Khôi phục cộng dồn X ngày") to stitch past streaks back into an unbroken active streak.
- **Endpoints**:
  - `GET /api/user/me/streak`: Get streak counts, studied minutes, banked credits, and progress percentage.
  - `POST /api/user/me/streak/restore`: Deduct credits and record restored dates with persistence in `SystemSetting`.

---

## 📖 GitLab Repository

```bash
cd existing_repo
git remote add origin https://gitsdc.tma.com.vn/careerpath-english/careerpath-fastapi.git
git branch -M main
git push -uf origin main
```
