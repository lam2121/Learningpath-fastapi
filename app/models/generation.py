from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base


class RoleGeneration(Base):
    __tablename__ = "role_generation"
    __table_args__ = (
        Index("fk_role_generation_job_role_idx", "role_id"),
        {"comment": "Trang thai sinh noi dung theo role (Generator A/B1/B2)"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    role_id = Column(
        BIGINT,
        ForeignKey("job_role.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    status = Column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="pending/in_progress/completed/failed",
    )
    step = Column(String(10), nullable=False, server_default="a", comment="a/b1/b2")
    step_a_count = Column(
        Integer,
        nullable=False,
        server_default="0",
        comment="so cau hoi placement da tao",
    )
    step_a_errors = Column(
        Integer,
        nullable=False,
        server_default="0",
        comment="so lan loi khi tao placement",
    )
    step_b1_count = Column(
        Integer, nullable=False, server_default="0", comment="so topics da tao"
    )
    step_b1_errors = Column(Integer, nullable=False, server_default="0")
    step_b2_count = Column(
        Integer, nullable=False, server_default="0", comment="so lesson shells da tao"
    )
    step_b2_errors = Column(Integer, nullable=False, server_default="0")
    error_message = Column(String(500), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
