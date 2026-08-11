from urllib.parse import quote_plus

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    MYSQL_HOST: str = "localhost"
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "123456"
    MYSQL_DB: str = "toeic_learningpath"
    MYSQL_PORT: str = "3306"

    # Connection pool settings
    DB_POOL_MIN_SIZE: int = 5
    DB_POOL_MAX_SIZE: int = 20
    DB_CONNECT_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    GEMINI_API_KEY: str = ""
    GEMINI_FLASH_MODEL: str = "gemini-2.5-flash"
    # Pro model for Generators C-1/C-2 (deep theory + quiz content). Default is
    # gemini-2.5-pro (GA, retirement Oct 2026); newer previews such as
    # gemini-3.1-pro-preview can be swapped in via .env without code changes.
    GEMINI_PRO_MODEL: str = "gemini-2.5-pro"

    # Runtime environment: "development" (default) enables dev-only behavior
    # (skill-score override on POST /onboarding/roadmap/select, the dev-mode
    # lesson-generate endpoint). Set to "production" to disable them (404).
    APP_ENV: str = "development"

    # TLS trust store for outbound provider calls. Point these at the CA bundle
    # / CA directory that terminates TLS on this machine when Python's bundled
    # roots (certifi) cannot verify it (e.g. a corporate/self-signed MITM proxy).
    SSL_CERT_FILE: str = ""  # single PEM bundle
    SSL_CERT_DIR: str = ""  # directory of CA certs (auto-concatenated at startup)
    SSL_VERIFY: bool = (
        True  # False = skip TLS verification for provider calls (insecure)
    )

    # Generator C-1 quality gates — count-based only (word-count gates removed;
    # the C-1 prompt still requests generous word counts). Counts are relaxed
    # from spec §9 so free-tier fallback models (llama-3.3-70b / flash) can pass
    # until a paid key is set. Restore spec values to re-tighten:
    # vocab 8, patterns 5, dialogue key phrases 3.
    C1_MIN_VOCAB: int = 6
    C1_MIN_PATTERNS: int = 2
    C1_MIN_DIALOGUE_KEY_PHRASES: int = 1

    # Optional alternate LLM providers (OpenAI-compatible, used for rotation)
    OpenRouter: str = ""
    Groq: str = ""
    Mistral: str = ""
    Nvidia: str = ""
    HuggingFace: str = ""
    # Reserved but not wired into the rotation registry:
    Zen: str = ""
    Google: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"

    # TỰ ĐỘNG SINH CHUỖI KẾT NỐI CHO SQLALCHEMY
    @property
    def DATABASE_URL(self) -> str:
        # Dùng quote_plus để mã hóa mật khẩu nếu có ký tự đặc biệt như @, #, $, v.v.
        safe_password = quote_plus(self.MYSQL_PASSWORD)
        return f"mysql+pymysql://{self.MYSQL_USER}:{safe_password}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"


app_config = AppConfig()
