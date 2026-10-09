from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base

# Learner enrollment states (user.learning_status, docs/07 deviation #23).
LEARNING_NONE = "none"
LEARNING_ENROLLED = "enrolled"

# CareerPath authorization (user.role_id -> role.id).
# Admin rights are derived and synchronized bidirectionally from the central
# Auth Service token claims (Single Source of Truth).
LEARNER_ROLE_ID = 1
ADMIN_ROLE_ID = 2


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
    daily_study_minutes = Column(
        Integer, nullable=False, default=120, server_default=text("120")
    )
    # Relative path to the avatar image on disk (e.g. "avatars/42_abc123.jpg").
    # Served via /api/static/uploads/avatars/... — NULL means no custom avatar.
    avatar_path = Column(String(500), nullable=True, default=None)
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
