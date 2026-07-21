from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from app.core.database import Base

class Role(Base):
    __tablename__ = 'role'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    type = Column(String(150), nullable=False)
    created_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'), nullable=False)
    users = relationship('User', back_populates='role')

class User(Base):
    __tablename__ = 'user'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role_id = Column(BigInteger, ForeignKey('role.id', ondelete='SET NULL'))
    name = Column(String(150), nullable=False)
    email = Column(String(254), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False) # Cột mới thêm
    created_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'), nullable=False)
    role = relationship('Role', back_populates='users')
