from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.database import Base


class RejectedContent(Base):
    __tablename__ = "rejected_content"
    __table_args__ = (
        Index("fk_rejected_content_job_role_idx", "role_id"),
        {"comment": "Noi dung AI tra ve nhung khong qua duoc quality gates"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    generator = Column(String(10), nullable=False, comment="A/B1/B2")
    role_id = Column(
        BIGINT,
        ForeignKey("job_role.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    input_preview = Column(String(500), nullable=True)
    error = Column(String(500), nullable=False)
    raw_response = Column(LONGTEXT, nullable=True)
    validator_checks = Column(JSON, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="pending/fixed/ignored",
    )
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
