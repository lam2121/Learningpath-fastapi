from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, Boolean, Text, text
from sqlalchemy.orm import relationship
from app.core.database import Base

class QuizType(Base):
    __tablename__ = 'quiz_type'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

class PlacementTestQuestion(Base):
    __tablename__ = 'placement_test_question'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    skill = Column(String(45), nullable=False)
    level = Column(Integer, nullable=False)
    quiz_type_id = Column(BigInteger, ForeignKey('quiz_type.id'), nullable=False)
    job_role_id = Column(BigInteger, ForeignKey('job_role.id'), nullable=False)

class Quiz(Base):
    __tablename__ = 'quiz'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    skill = Column(String(45), nullable=False)
    quiz_type_id = Column(BigInteger, ForeignKey('quiz_type.id', ondelete='RESTRICT', onupdate='CASCADE'), nullable=False)
    lesson_id = Column(BigInteger, ForeignKey('lesson.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)

class QuizDetail(Base):
    __tablename__ = 'quiz_detail'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    quiz_id = Column(BigInteger, ForeignKey('quiz.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    answer = Column(String(45), nullable=False)
    is_correct = Column(Boolean)

class Survey(Base):
    __tablename__ = 'survey'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)

class SurveyUser(Base):
    __tablename__ = 'survey_user'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    survey_id = Column(BigInteger, ForeignKey('survey.id', ondelete='CASCADE'), nullable=False)
    answer = Column(Integer, nullable=False)
    user_id = Column(BigInteger, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
