from sqlalchemy import Column, String, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class User(Base):
    __tablename__ = 'user'
    __table_args__ = (
        Index('fk_user_role', 'role_id'), #[cite: 2]
        Index('email', 'email', unique=True), #[cite: 2]
        {'comment': 'Nguoi dung he thong'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    role_id = Column(BIGINT(unsigned=True), ForeignKey('role.id', ondelete='SET NULL'), nullable=True) #[cite: 2]
    name = Column(String(150), nullable=False) #[cite: 2]
    email = Column(String(254), nullable=False) #[cite: 2]
    hashed_password = Column(String(255), nullable=False) # Cột mới chuẩn bị update
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')) #[cite: 2]
    age = Column(String(150), nullable=True)