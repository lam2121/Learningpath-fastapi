from sqlalchemy import Column, String, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

# Learner enrollment states (user.learning_status, docs/07 deviation #23).
LEARNING_NONE = "none"
LEARNING_ENROLLED = "enrolled"


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        Index("fk_user_role", "role_id"),
        Index("email", "email", unique=True),
        {"comment": "Nguoi dung he thong"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    role_id = Column(
        BIGINT(unsigned=True), ForeignKey("role.id", ondelete="SET NULL"), nullable=True
    )
    job_role_id = Column(
        BIGINT, ForeignKey("job_role.id", ondelete="SET NULL"), nullable=True
    )
    name = Column(String(150), nullable=False)
    email = Column(String(254), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    learning_status = Column(
        String(20),
        nullable=False,
        default=LEARNING_NONE,
        server_default=text("'none'"),
    )
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
