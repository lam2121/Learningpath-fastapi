import sys
import os
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import create_engine, pool, text
from alembic import context

sys.path.append(str(Path(__file__).parent.parent))

from app.core.infra.config import app_config
from app.models import Base 

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

connect_args = {}
ca_cert_path = getattr(app_config, "MYSQL_CA_CERT", None)
if ca_cert_path and os.path.exists(ca_cert_path):
    connect_args["ssl"] = {"ca": ca_cert_path}


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        app_config.DATABASE_URL,
        poolclass=pool.NullPool,
        connect_args=connect_args
    )
    
    with connectable.connect() as connection:
        # Ensure alembic_version.version_num is VARCHAR(100) before any upgrade or stamp runs
        try:
            connection.execute(
                text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(100) NOT NULL PRIMARY KEY);")
            )
            connection.execute(
                text("ALTER TABLE alembic_version MODIFY COLUMN version_num VARCHAR(100) NOT NULL;")
            )
            connection.commit()
        except Exception:
            pass

        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
