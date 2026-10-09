import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.infra.config import app_config

connect_args = {
    "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
}

# Attach SSL certificate for cloud MySQL (e.g. Aiven) if ca.pem exists
ca_cert_path = getattr(app_config, "MYSQL_CA_CERT", None)
if ca_cert_path and os.path.exists(ca_cert_path):
    connect_args["ssl"] = {"ca": ca_cert_path}

# Initialize Engine with pool configuration from AppConfig
engine = create_engine(
    app_config.DATABASE_URL,
    pool_size=app_config.DB_POOL_MAX_SIZE,
    max_overflow=app_config.DB_MAX_OVERFLOW,
    pool_timeout=app_config.DB_POOL_TIMEOUT,
    pool_recycle=app_config.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and ensures cleanup.

    - On success (no exception): the caller is responsible for commit.
    - On unhandled exception: rolls back the transaction so partial writes
      never leak and the connection is returned in a clean state.
    - Always closes the session so the connection goes back to the pool.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
