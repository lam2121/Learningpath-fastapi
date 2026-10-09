from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"
    __table_args__ = (
        Index("fk_ai_usage_log_job_role_idx", "role_id"),
        {"comment": "Log chi phi va token cua tung AI call (powers AI Costs page)"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    generator = Column(String(10), nullable=False, comment="A/B1/B2")
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, server_default="0")
    completion_tokens = Column(Integer, nullable=False, server_default="0")
    cost_usd = Column(Float, nullable=False, server_default="0")
    status = Column(
        String(20),
        nullable=False,
        server_default="success",
        comment="success/retry/fallback/rejected",
    )
    role_id = Column(
        BIGINT,
        ForeignKey("job_role.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
