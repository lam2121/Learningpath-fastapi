from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import app_config

# Khởi tạo Engine với các thông số Pool lấy từ AppConfig
engine = create_engine(
    app_config.DATABASE_URL,
    pool_size=app_config.DB_POOL_MAX_SIZE,
    pool_recycle=app_config.DB_POOL_RECYCLE,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()