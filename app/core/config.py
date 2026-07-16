from pydantic_settings import BaseSettings

class AppConfig(BaseSettings):
    MYSQL_HOST: str = "localhost"
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "toeic_learningpath"
    MYSQL_PORT: str = "3306"
    
    # Connection pool settings
    DB_POOL_MIN_SIZE: int = 5
    DB_POOL_MAX_SIZE: int = 20
    DB_CONNECT_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"

    # TỰ ĐỘNG SINH CHUỖI KẾT NỐI CHO SQLALCHEMY
    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        
app_config = AppConfig()