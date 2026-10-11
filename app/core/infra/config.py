import os
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    # ── Database SSL Certificate ─────────────────────────────────────────────
    MYSQL_CA_CERT: str = "./certs/ca.pem"

    # ── JWT Verification Strictness ──────────────────────────────────────────
    # False by default for backward compatibility with external auth-service tokens
    JWT_STRICT_CLAIMS: bool = False

    # ─── Static files & directories ──────────────────────────────────────────
    STATIC_DIR: str = "static"
    STATIC_URL_PREFIX: str = "/api/static"

    # ─── CORS Allowed Origins (comma-separated string) ───────────────────────
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://builtbylam.com,https://www.builtbylam.com,https://auth.builtbylam.com,"
        "https://localhost:8001"
    )

    # ─── File & Upload Limits ────────────────────────────────────────────────
    MAX_AVATAR_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/webp"
    MAX_AUDIO_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

    # ─── TTS & Audio Cache Settings ──────────────────────────────────────────
    MAX_CACHE_SIZE_MB: int = 100
    MAX_FILE_AGE_SECONDS: int = 7 * 86400  # 7 days
    DEFAULT_TTS_VOICE: str = "en-US-JennyNeural"
    PRONUNCIATION_CACHE_DIR: str = "pronunciation_cache"

    # ─── SSE, Stream Timeouts & Lifecycle Cleanup ────────────────────────────
    SSE_NOTIFICATION_TIMEOUT_SECONDS: int = 25
    STALE_GENERATION_MINUTES: int = 15
    STALE_CLEANUP_INTERVAL_SECONDS: int = 300

    # ─── Study & Moderation Defaults ─────────────────────────────────────────
    DEFAULT_DAILY_STUDY_MINUTES: int = 120
    STREAK_RESTORE_MINUTES_PER_DAY: int = 120
    STREAK_RESTORE_MAX_LOOKBACK_DAYS: int = 30
    USAGE_LOG_DEFAULT_LIMIT: int = 500
    USAGE_LOG_MAX_LIMIT: int = 2000


    # ─── Quiz & Assessment Thresholds ────────────────────────────────────────
    FINAL_QUIZ_SIZE: int = 50
    FINAL_QUIZ_PASS_THRESHOLD_PERCENT: float = 80.0
    FINAL_QUIZ_SKILL_SECTION_THRESHOLD_PERCENT: float = 60.0
    FINAL_QUIZ_MIN_PER_SKILL: int = 8
    TOPIC_QUIZ_TOTAL_QUESTIONS: int = 30
    TOPIC_QUIZ_PASS_THRESHOLD_PERCENT: float = 75.0
    LESSON_PASS_THRESHOLD_PERCENT: float = 70.0
    DEFAULT_INITIAL_RADAR_SCORE: float = 50.0

    # ─── AI Provider Endpoints & Default Models ──────────────────────────────
    GOOGLE_GEMINI_API_BASE_URL: str = "https://generativelanguage.googleapis.com"
    GROQ_API_BASE_URL: str = "https://api.groq.com/openai/v1"
    MISTRAL_API_BASE_URL: str = "https://api.mistral.ai/v1"
    OPENROUTER_API_BASE_URL: str = "https://openrouter.ai/api/v1"
    GROQ_DEFAULT_MODEL: str = "openai/gpt-oss-120b"
    MISTRAL_DEFAULT_MODEL: str = "mistral-small-latest"
    OPENROUTER_DEFAULT_MODEL: str = "google/gemma-4-31b-it:free"

    MYSQL_HOST: str = "localhost"
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "toeic_learningpath"
    MYSQL_PORT: str = "3306"
    # Connection pool settings (scaled to match 40-worker threadpool capacity)
    DB_POOL_MIN_SIZE: int = 10
    DB_POOL_MAX_SIZE: int = 25
    DB_MAX_OVERFLOW: int = 15
    DB_POOL_TIMEOUT: int = 30
    DB_CONNECT_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Redis configuration for multi-worker SSE Pub/Sub, rate limiting, and caching
    REDIS_URL: str = ""

    SECRET_KEY: str
    ALGORITHM: str = "HS256"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        val = (v or "").strip()
        if not val:
            raise ValueError("SECRET_KEY must not be empty.")
        if len(val) < 16:
            raise ValueError("SECRET_KEY is too short; must be at least 16 characters.")
        return val
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    # ── Central Auth Service ──────────────────────────────────────────────
    AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL", "https://auth.builtbylam.com/api/auth")
    AUTH_JWKS_URL: str = os.getenv("AUTH_JWKS_URL", "https://auth.builtbylam.com/api/auth/.well-known/jwks.json")
    AUTH_PUBLIC_KEY_PATH: str = "../auth-service/keys/public_key.pem"
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", os.getenv("AUTH_TOKEN_ISSUER", "https://api.builtbylam.com"))
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", os.getenv("AUTH_TOKEN_AUDIENCE", "careerpath"))

    # The shared HS256 secret that the external auth-service signs JWTs with.
    # The backend must use the SAME secret to decode those tokens, otherwise
    # every authenticated request fails and users are never provisioned into
    # toeic_learningpath.user. This is a document-only reference for the guard
    # below; override via AUTH_SHARED_SECRET if it ever changes.
    AUTH_SHARED_SECRET: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_FLASH_MODEL: str = ""
    GEMINI_PRO_MODEL: str = ""
    # Pro model for Generators C-1/C-2 (deep theory + quiz content). Override
    # via GEMINI_PRO_MODEL in .env without code changes.

    
    # Runtime environment: "production" (default) disables dev-only behavior
    # (skill-score override on POST /onboarding/roadmap/select, the dev-mode
    # lesson-generate endpoint). Set to "development" to enable them.
    APP_ENV: str = "production"

    # TLS trust store for outbound provider calls. Point these at the CA bundle
    # / CA directory that terminates TLS on this machine when Python's bundled
    # roots (certifi) cannot verify it (e.g. a corporate/self-signed MITM proxy).
    SSL_CERT_FILE: str = ""  # single PEM bundle
    SSL_CERT_DIR: str = ""  # directory of CA certs (auto-concatenated at startup)

    # Generator C-1 quality gates — count-based only (word-count gates removed;
    # the C-1 prompt still requests generous word counts). Counts are relaxed
    # from spec §9 so free-tier fallback models (llama-3.3-70b / flash) can pass
    # until a paid key is set. Restore spec values to re-tighten:
    # vocab 8, patterns 5, dialogue key phrases 3.
    C1_MIN_VOCAB: int = 6
    C1_MIN_PATTERNS: int = 2
    C1_MIN_DIALOGUE_KEY_PHRASES: int = 1

    # --- AI generation counts ---
    # Single source for the counts the prompts, validators and JSON schemas are
    # built from. Read at import, so a change needs a restart and only affects
    # content generated afterwards.
    # Generator A: questions per skill, split evenly over 3 difficulty bands.
    NUM_PLACEMENT_QUESTIONS_PER_SKILL: int = 12
    # Generator B-1: topics per role. Must divide cleanly by every role's
    # baseline percentages (baseline% × topics // 100).
    NUM_TOPICS_PER_ROLE: int = 20
    # Generator B-2: lessons per topic by tier, in this order.
    NUM_BASIC_PER_TOPIC: int = 2
    NUM_INTERMEDIATE_PER_TOPIC: int = 2
    NUM_ADVANCED_PER_TOPIC: int = 2
    # Generator C-1: vocab items and phrase patterns per lesson.
    NUM_VOCAB: int = 8
    NUM_PATTERNS: int = 5
    # Generator C-2: questions per quiz type (fill_blank / multi_select / ordering).
    NUM_QUIZ_QUESTIONS_PER_TYPE: int = 10

    @field_validator(
        "NUM_PLACEMENT_QUESTIONS_PER_SKILL",
        "NUM_TOPICS_PER_ROLE",
        "NUM_BASIC_PER_TOPIC",
        "NUM_INTERMEDIATE_PER_TOPIC",
        "NUM_ADVANCED_PER_TOPIC",
        "NUM_VOCAB",
        "NUM_PATTERNS",
        "NUM_QUIZ_QUESTIONS_PER_TYPE",
    )
    @classmethod
    def validate_generation_count(cls, v: int, info: ValidationInfo) -> int:
        if v < 1:
            raise ValueError(f"{info.field_name} must be at least 1.")
        # The C-1 prompt describes five patterns (p1..p5) and the validator
        # needs 4 dialogue key phrases with distinct phrase ids.
        if info.field_name == "NUM_PATTERNS" and not 4 <= v <= 5:
            raise ValueError("NUM_PATTERNS must be 4 or 5.")
        # 3 difficulty bands, each holding Context-layer and Language-layer questions.
        if info.field_name == "NUM_PLACEMENT_QUESTIONS_PER_SKILL" and (v % 3 or v < 6):
            raise ValueError(
                "NUM_PLACEMENT_QUESTIONS_PER_SKILL must be a multiple of 3 and at least 6."
            )
        return v

    # --- LLM call tuning ---
    # Read at import, so a change needs a restart.
    # Attempts per generator call: the original request plus retries (spec §8.1).
    LLM_MAX_ATTEMPTS: int = Field(3, ge=1)
    # Output token ceilings per generator. A response cut off at the ceiling
    # fails JSON parsing, so raise these together with the content counts above.
    LLM_PLACEMENT_MAX_OUTPUT_TOKENS: int = Field(4096, ge=1)
    LLM_C1_MAX_OUTPUT_TOKENS: int = Field(24576, ge=1)
    LLM_C2_MAX_OUTPUT_TOKENS: int = Field(16384, ge=1)
    LLM_C2_TEMPERATURE: float = Field(0.15, ge=0, le=2)
    # Sampling defaults for every call that does not set its own.
    LLM_DEFAULT_TEMPERATURE: float = Field(0.3, ge=0, le=2)
    LLM_DEFAULT_TOP_P: float = Field(0.8, gt=0, le=1)
    LLM_DEFAULT_MAX_OUTPUT_TOKENS: int = Field(2048, ge=1)
    # Global request pacing across providers (spec §7.2) and per-request timeout.
    LLM_RATE_LIMIT_RPM: int = Field(250, ge=1)
    LLM_REQUEST_TIMEOUT_SECONDS: float = Field(150.0, gt=0)
    # On 429/quota: wait a random time in [min, max], and skip that provider
    # for the cooldown so its per-minute quota window can clear.
    LLM_QUOTA_BACKOFF_MIN_SECONDS: float = Field(5.0, ge=0)
    LLM_QUOTA_BACKOFF_MAX_SECONDS: float = Field(20.0, ge=0)
    LLM_PROVIDER_COOLDOWN_SECONDS: float = Field(65.0, ge=0)
    # USD per 1K tokens for cost estimates (spec §7.3). Flash rates apply to
    # GEMINI_FLASH_MODEL, Pro rates to any other model.
    LLM_FLASH_INPUT_RATE_PER_1K: float = Field(0.0003, ge=0)
    LLM_FLASH_OUTPUT_RATE_PER_1K: float = Field(0.0025, ge=0)
    LLM_PRO_INPUT_RATE_PER_1K: float = Field(0.00125, ge=0)
    LLM_PRO_OUTPUT_RATE_PER_1K: float = Field(0.01, ge=0)
    # Speech-to-text request (Gemini audio) and JWKS fetch.
    STT_REQUEST_TIMEOUT_SECONDS: float = Field(30.0, gt=0)
    STT_MAX_OUTPUT_TOKENS: int = Field(500, ge=1)
    AUTH_JWKS_TIMEOUT_SECONDS: float = Field(5.0, gt=0)

    # Optional alternate LLM providers (OpenAI-compatible, used for rotation)
    OpenRouter: str = ""
    Groq: str = ""
    GROQ_MODEL: str = ""
    Mistral: str = ""
    Nvidia: str = ""
    HuggingFace: str = ""
    # Reserved but not wired into the rotation registry:
    Zen: str = ""
    Google: str = ""

    # Set to True in environments with corporate SSL interception / self-signed certs
    # that cause CERTIFICATE_VERIFY_FAILED errors when calling external APIs.
    DISABLE_SSL_VERIFY: bool = False

    @field_validator("DISABLE_SSL_VERIFY")
    @classmethod
    def validate_ssl_verify(cls, v: bool, info: ValidationInfo) -> bool:
        app_env = str(info.data.get("APP_ENV", "")).lower()
        if v and app_env == "production":
            raise ValueError("DISABLE_SSL_VERIFY must never be enabled in production environment.")
        return v

    # --- Pronunciation scoring (POST /api/audio/pronunciation) ---
    # Wav2Vec2 inference is CPU-bound and uninterruptible once started, so the
    # feature is bounded by admission control + input limits rather than timeouts.
    # Concurrency is 1 by default: the models are process-wide singletons, so the
    # scarce resource is CPU, not RAM, and two parallel forward passes each try to
    # grab every core and thrash.
    PRONUNCIATION_MAX_CONCURRENCY: int = 1
    PRONUNCIATION_QUEUE_TIMEOUT_SECONDS: float = 20.0
    PRONUNCIATION_MAX_AUDIO_SECONDS: float = 30.0
    PRONUNCIATION_TORCH_THREADS: int = 2
    # Output token ceiling for the AI pronunciation feedback call.
    PRONUNCIATION_FEEDBACK_MAX_OUTPUT_TOKENS: int = Field(2048, ge=1)
    # Load the ~4.8GB of Wav2Vec2 checkpoints at startup instead of on first
    # request. Leave False for local dev (uvicorn --reload would re-run it on
    # every code save); enable in deployed environments.
    PRONUNCIATION_PRELOAD_MODELS: bool = False

    class Config:
        env_file = (
            str(Path(__file__).resolve().parents[3] / ".env"),
            ".env",
        )
        case_sensitive = True
        extra = "allow"

    # TỰ ĐỘNG SINH CHUỖI KẾT NỐI CHO SQLALCHEMY
    @property
    def DATABASE_URL(self) -> str:
        # Dùng quote_plus để mã hóa mật khẩu nếu có ký tự đặc biệt như @, #, $, v.v.
        safe_password = quote_plus(self.MYSQL_PASSWORD)
        return f"mysql+pymysql://{self.MYSQL_USER}:{safe_password}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"

    @property
    def NUM_LESSONS_PER_TOPIC(self) -> int:
        return (
            self.NUM_BASIC_PER_TOPIC
            + self.NUM_INTERMEDIATE_PER_TOPIC
            + self.NUM_ADVANCED_PER_TOPIC
        )

    @property
    def LESSON_TIER_ORDER(self) -> list[str]:
        return (
            ["basic"] * self.NUM_BASIC_PER_TOPIC
            + ["intermediate"] * self.NUM_INTERMEDIATE_PER_TOPIC
            + ["advanced"] * self.NUM_ADVANCED_PER_TOPIC
        )

    @property
    def PLACEMENT_QUESTIONS_PER_BAND(self) -> int:
        return self.NUM_PLACEMENT_QUESTIONS_PER_SKILL // 3

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def ALLOWED_IMAGE_TYPES_SET(self) -> set[str]:
        return {t.strip() for t in self.ALLOWED_IMAGE_TYPES.split(",") if t.strip()}

    @property
    def PROJECT_ROOT(self) -> Path:
        # Resolves to careerpath-fastapi root directory
        return Path(__file__).resolve().parents[3]

    @property
    def RESOLVED_STATIC_DIR(self) -> Path:
        p = Path(self.STATIC_DIR)
        if not p.is_absolute():
            p = (self.PROJECT_ROOT / p).resolve()
        return p


app_config = AppConfig()

