from urllib.parse import quote_plus

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    MYSQL_HOST: str = "localhost"
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "12345678x@X"
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

    # Optional alternate LLM providers (OpenAI-compatible, used for rotation)
    OpenRouter: str = ""
    Groq: str = ""
    Mistral: str = ""
    Nvidia: str = ""
    HuggingFace: str = ""
    # Reserved but not wired into the rotation registry:
    Zen: str = ""
    Google: str = ""

    # Set to True in environments with corporate SSL interception / self-signed certs
    # that cause CERTIFICATE_VERIFY_FAILED errors when calling external APIs.
    DISABLE_SSL_VERIFY: bool = False

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
