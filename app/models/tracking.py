from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, Date, JSON, Float, text
from sqlalchemy.orm import relationship
from app.core.database import Base

class Queue(Base):
    __tablename__ = 'queue'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    quiz_id = Column(BigInteger, ForeignKey('quiz.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    status = Column(String(20), nullable=False)
    next_review_date = Column(Date, nullable=False)
    created_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'), nullable=False)
    last_reviewed_at = Column(DateTime, nullable=False)
    count = Column(Integer, nullable=False)

class UserCourse(Base):
    __tablename__ = 'user_course'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    course_id = Column(BigInteger, ForeignKey('course.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    syllabus = Column(JSON, nullable=False)
    status = Column(String(20), server_default='locked', nullable=False)
    completed_at = Column(DateTime)
    progress = Column(Float, default=0, nullable=False)
    unlocked_at = Column(DateTime, nullable=False)
    user_answers = Column(JSON, nullable=False)

class UserCourseSkillVector(Base):
    __tablename__ = 'user_course_skill_vector'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_course_id = Column(BigInteger, ForeignKey('user_course.id', ondelete='CASCADE', onupdate='CASCADE'), unique=True, nullable=False)
    start_vector = Column(JSON, nullable=False)
    current_vector = Column(JSON)
    prev_stack = Column(JSON, nullable=False)
    updated_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False)

class UserLesson(Base):
    __tablename__ = 'user_lesson'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    lesson_id = Column(BigInteger, ForeignKey('lesson.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    user_answers = Column(JSON, nullable=False)
    status = Column(String(20), server_default='locked', nullable=False)
    completed_at = Column(DateTime)
    progress = Column(Float, default=0, nullable=False)
    unlocked_at = Column(DateTime)
