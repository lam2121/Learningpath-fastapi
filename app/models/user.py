from sqlalchemy import Column, String, DateTime, ForeignKey, Index, Boolean, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class User(Base):
    __tablename__ = 'user'
    __table_args__ = (
        Index('fk_user_role', 'role_id'),
        Index('email', 'email', unique=True),
        {'comment': 'Nguoi dung he thong'}
    )

<<<<<<< HEAD

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    role_id = Column(BIGINT(unsigned=True), ForeignKey('role.id', ondelete='SET NULL'), nullable=True)
    job_role_id = Column(BIGINT, ForeignKey('job_role.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(150), nullable=False)
    email = Column(String(254), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_finished_placement_test = Column(Boolean, nullable=False, default=False, server_default=text('0'))
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
=======
    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    role_id = Column(BIGINT(unsigned=True), ForeignKey('role.id', ondelete='SET NULL'), nullable=True) #[cite: 2]
    name = Column(String(150), nullable=False) #[cite: 2]
    email = Column(String(254), nullable=False) #[cite: 2]
    hashed_password = Column(String(255), nullable=False) # Cột mới chuẩn bị update
    is_finished_placement_test = Column(Boolean, nullable=False, default=False, server_default=text('0'))
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')) #[cite: 2]
>>>>>>> b45da58 (merge)
