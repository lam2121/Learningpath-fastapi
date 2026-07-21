from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, JSON, text, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class JobRole(Base):
    __tablename__ = 'job_role'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(45), nullable=False)
    JD = Column(Text, nullable=False)
    seed_tier = Column(JSON, nullable=False)
    init_weights = Column(JSON, nullable=False)
    example_question = Column(JSON, nullable=False)

class Course(Base):
    __tablename__ = 'course'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'), nullable=False)
    job_role_id = Column(BigInteger, ForeignKey('job_role.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)

class Topic(Base):
    __tablename__ = 'topic'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    english_level = Column(Integer, nullable=False)
    skill_weight = Column(JSON, nullable=False)
    business_level = Column(Integer, nullable=False)
    course_id = Column(BigInteger, ForeignKey('course.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)

class Lesson(Base):
    __tablename__ = 'lesson'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    theory = Column(JSON)
    topic_id = Column(BigInteger, ForeignKey('topic.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    name = Column(String(45), nullable=False)
    skill_weight = Column(JSON, nullable=False)
    english_level = Column(Integer, nullable=False)
    business_level = Column(Integer, nullable=False)
