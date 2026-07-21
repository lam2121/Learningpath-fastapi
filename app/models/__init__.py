# Import tất cả các model vào đây để Alembic có thể quét được toàn bộ metadata
from app.core.database import Base
from app.models.user import User, Role
from app.models.curriculum import JobRole, Course, Topic, Lesson
from app.models.assessment import QuizType, PlacementTestQuestion, Quiz, QuizDetail, Survey, SurveyUser
from app.models.tracking import Queue, UserCourse, UserCourseSkillVector, UserLesson
