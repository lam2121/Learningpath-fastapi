from sqlalchemy import Column, String, DateTime, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Role(Base):
    __tablename__ = 'role'
    __table_args__ = {'comment': 'Danh muc vai tro cong viec'} #[cite: 2]

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    type = Column(String(150), nullable=False, comment='PM, BA, Tech Lead, SA, QA, DevOps...') #[cite: 2]
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')) #[cite: 2]