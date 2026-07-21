from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class QuizType(Base):
    __tablename__ = 'quiz_type'
    __table_args__ = {'comment': 'Danh muc phan loai cau hoi'} #[cite: 2]

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    name = Column(String(100), nullable=False, comment='Loai cau hoi quiz') #[cite: 2]
    description = Column(Text, nullable=True) #[cite: 2]