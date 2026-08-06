from sqlalchemy import Column, DateTime, String, text
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_setting"
    __table_args__ = {
        "comment": "Key/value settings (single-row per key). ai_generation_enabled = false blocks generation"
    }

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(LONGTEXT, nullable=False)
    updated_by = Column(BIGINT, nullable=True)
    reason = Column(String(500), nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
