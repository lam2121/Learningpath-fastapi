import json
from datetime import date, datetime, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.ai.gemini import GeminiClientPool
from app.core.ai.prompts import PROMPT_E1_TEMPLATE
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.roadmap import lesson_is_assigned
from app.core.ai.gemini import GeminiClientPool
from app.core.ai.prompts import PROMPT_E1_TEMPLATE
from app.feature.onboarding.lesson_quiz_scoring import LESSON_PASS_THRESHOLD_PERCENT
from app.feature.user.quiz_review_service import (
    get_user_quiz_review_items,
    submit_user_quiz_review,
)
from app.feature.user.user_schema import (
    AICoachMessageRequest,
    AICoachMessageResponse,
    FinalQuizHistoryEntryResponse,
    LessonQuizHistoryEntryResponse,
    QuizReviewListResponse,
    QuizReviewSubmitRequest,
    QuizReviewSubmitResponse,
    StudySettingsUpdateRequest,
    TopicQuizHistoryEntryResponse,
    UserProfileResponse,
)
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.queue import Queue
from app.models.topic import Topic
from app.models.user import LEARNING_NONE, User
from app.models.user_course import UserCourse
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

router = APIRouter()
DEFAULT_DAILY_STUDY_MINUTES = 120
SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


def _coerce_skill_percent(value: object) -> float:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.0

    if numeric_value <= 1:
        numeric_value *= 100

    return max(0.0, min(100.0, round(numeric_value, 1)))


def _normalize_skill_vector(value: object | None) -> dict[str, float] | None:
    if value is None:
        return None

    if isinstance(value, dict):
        if not any(skill in value for skill in SKILL_KEYS):
            return None
        return {
            skill: _coerce_skill_percent(value.get(skill, 0))
            for skill in SKILL_KEYS
        }

    if isinstance(value, (list, tuple)):
        return {
            skill: _coerce_skill_percent(value[index]) if index < len(value) else 0
            for index, skill in enumerate(SKILL_KEYS)
        }

    return None


def _coerce_json_object(value: object | None) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_iso_datetime(value: object | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_attempt_score(value: object | None) -> float:
    if not isinstance(value, dict):
        return 0.0
    score = value.get("weighted_score_percent")
    if isinstance(score, (int, float)):
        return float(score)
    return 0.0


def _is_attempt_snapshot(value: object | None) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        key in value
        for key in ("question_results", "answers", "weighted_score_percent", "passed")
    )


def _is_passing_attempt_snapshot(value: object | None) -> bool:
    if not isinstance(value, dict):
        return False

    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed

    return _extract_attempt_score(value) >= LESSON_PASS_THRESHOLD_PERCENT


def _extract_latest_attempt(saved_state: dict) -> dict:
    latest_attempt = _coerce_json_object(saved_state.get("latest_attempt"))
    if _is_attempt_snapshot(latest_attempt):
        return latest_attempt

    if _is_attempt_snapshot(saved_state):
        return saved_state

    for key in ("best_attempt", "best_pass_attempt"):
        attempt = _coerce_json_object(saved_state.get(key))
        if _is_attempt_snapshot(attempt):
            return attempt

    return {}


def _extract_best_passing_attempt(saved_state: dict) -> dict:
    if _is_passing_attempt_snapshot(saved_state):
        return saved_state

    for key in ("best_attempt", "best_pass_attempt"):
        attempt = _coerce_json_object(saved_state.get(key))
        if _is_passing_attempt_snapshot(attempt):
            return attempt
    return {}


def _extract_best_passing_score(
    saved_state: dict,
    fallback_progress: object | None,
) -> float | None:
    best_score = _extract_attempt_score(_extract_best_passing_attempt(saved_state))
    fallback_score = 0.0
    if (
        isinstance(fallback_progress, (int, float))
        and float(fallback_progress) >= LESSON_PASS_THRESHOLD_PERCENT
    ):
        fallback_score = float(fallback_progress)
    highest = max(best_score, fallback_score)
    return round(highest, 2) if highest > 0 else None


def _extract_question_results(attempt: dict) -> list[dict]:
    raw = attempt.get("question_results", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _compute_hint_breakdown(attempt: dict) -> tuple[int, int, int, int, int]:
    question_results = _extract_question_results(attempt)
    total_questions = len(question_results)

    correct_no_hint_count = sum(
        1
        for result in question_results
        if bool(result.get("is_correct")) and not bool(result.get("used_hint"))
    )
    total_no_hint_questions = sum(
        1 for result in question_results if not bool(result.get("used_hint"))
    )
    correct_with_hint_count = sum(
        1
        for result in question_results
        if bool(result.get("is_correct")) and bool(result.get("used_hint"))
    )
    total_with_hint_questions = sum(
        1 for result in question_results if bool(result.get("used_hint"))
    )

    if total_questions == 0:
        total_questions = int(attempt.get("total_questions") or 0)

    return (
        correct_no_hint_count,
        total_no_hint_questions,
        correct_with_hint_count,
        total_with_hint_questions,
        total_questions,
    )


def _derive_lesson_quiz_status(
    user_lesson: UserLesson,
    *,
    best_attempt: dict,
    latest_attempt: dict,
) -> str:
    if user_lesson.status == "completed" or _is_passing_attempt_snapshot(best_attempt):
        return "passed"
    if _is_attempt_snapshot(latest_attempt):
        return "failed"
    return user_lesson.status or "not_started"


def _build_skill_score_snapshots(
    db: Session,
    user_id: int,
) -> tuple[dict[str, float] | None, dict[str, float] | None]:
    vector_row = (
        db.query(UserRadarScore)
        .filter(UserRadarScore.user_id == user_id)
        .order_by(UserRadarScore.updated_at.desc(), UserRadarScore.id.desc())
        .first()
    )

    if vector_row is None:
        return None, None

    initial_scores = _normalize_skill_vector(vector_row.start_vector)
    current_scores = (
        _normalize_skill_vector(vector_row.current_vector) or initial_scores
    )

    return initial_scores, current_scores


def _build_study_history(db: Session, user_id: int) -> tuple[int, list[dict[str, object]]]:
    completed_lessons = (
        db.query(UserLesson.completed_at, Lesson.estimated_minutes)
        .join(Lesson, Lesson.id == UserLesson.lesson_id)
        .filter(
            UserLesson.user_id == user_id,
            UserLesson.status == "completed",
            UserLesson.completed_at.isnot(None),
        )
        .all()
    )

    total_studied_minutes = 0
    monthly_minutes: dict[date, int] = {}
    today = date.today()

    for completed_at, estimated_minutes in completed_lessons:
        minutes = max(0, estimated_minutes or 0)
        if minutes <= 0 or completed_at is None:
            continue

        total_studied_minutes += minutes
        completed_on = completed_at.date()

        if completed_on.year == today.year and completed_on.month == today.month:
            monthly_minutes[completed_on] = monthly_minutes.get(completed_on, 0) + minutes

    study_history = [
        {"studied_on": studied_on, "minutes": minutes}
        for studied_on, minutes in sorted(monthly_minutes.items())
    ]

    return total_studied_minutes, study_history


def _build_lesson_quiz_history(
    db: Session, user_id: int
) -> list[LessonQuizHistoryEntryResponse]:
    rows = (
        db.query(UserLesson, Lesson, Topic, UserRoadmap)
        .join(Lesson, Lesson.id == UserLesson.lesson_id)
        .join(Topic, Topic.id == Lesson.topic_id)
        .outerjoin(
            UserRoadmap,
            (UserRoadmap.user_id == UserLesson.user_id)
            & (UserRoadmap.topic_id == Lesson.topic_id),
        )
        .filter(UserLesson.user_id == user_id)
        .order_by(UserLesson.completed_at.desc(), UserLesson.id.desc())
        .all()
    )

    history: list[LessonQuizHistoryEntryResponse] = []

    for user_lesson, lesson, topic, user_roadmap in rows:
        saved_state = _coerce_json_object(user_lesson.user_answers)
        best_attempt = _extract_best_passing_attempt(saved_state)
        best_score_percent = _extract_best_passing_score(saved_state, user_lesson.progress)
        latest_attempt = _extract_latest_attempt(saved_state)
        (
            correct_no_hint_count,
            total_no_hint_questions,
            correct_with_hint_count,
            total_with_hint_questions,
            total_questions,
        ) = _compute_hint_breakdown(best_attempt)
        attempt_count = user_lesson.attempt_count
        failed_attempts = user_lesson.failed_attempts
        recorded_at = (
            user_lesson.completed_at
            or _parse_iso_datetime(best_attempt.get("submitted_at"))
            or _parse_iso_datetime(latest_attempt.get("submitted_at"))
        )

        history.append(
            LessonQuizHistoryEntryResponse(
                lesson_id=lesson.id,
                lesson_title=lesson.title,
                topic_name=topic.name if topic else None,
                topic_sort_order=(
                    (user_roadmap.sort_order + 1) if user_roadmap is not None else None
                ),
                skill=lesson.primary_skill,
                difficulty_tier=lesson.difficulty_tier,
                status=_derive_lesson_quiz_status(
                    user_lesson,
                    best_attempt=best_attempt,
                    latest_attempt=latest_attempt,
                ),
                best_score_percent=best_score_percent,
                passed=bool(user_lesson.completed_at is not None),
                attempt_count=int(attempt_count or 0),
                failed_attempts=int(failed_attempts or 0),
                correct_no_hint_count=int(correct_no_hint_count or 0),
                total_no_hint_questions=int(total_no_hint_questions or 0),
                correct_with_hint_count=int(correct_with_hint_count or 0),
                total_with_hint_questions=int(total_with_hint_questions or 0),
                total_questions=int(total_questions or 0),
                recorded_at=recorded_at,
                completed_at=user_lesson.completed_at,
                last_submitted_at=_parse_iso_datetime(
                    (latest_attempt or best_attempt).get("submitted_at")
                ),
            )
        )

    history.sort(
        key=lambda entry: (
            entry.completed_at or entry.last_submitted_at or datetime.min,
            entry.best_score_percent or 0.0,
        ),
        reverse=True,
    )
    return history


def _build_topic_quiz_history(
    db: Session, user_id: int
) -> list[TopicQuizHistoryEntryResponse]:
    rows = (
        db.query(Topic, UserRoadmap, UserTopicQuiz)
        .join(
            UserRoadmap,
            (UserRoadmap.topic_id == Topic.id) & (UserRoadmap.user_id == user_id),
        )
        .outerjoin(
            UserTopicQuiz,
            (UserTopicQuiz.topic_id == Topic.id) & (UserTopicQuiz.user_id == user_id),
        )
        .order_by(UserRoadmap.sort_order.asc())
        .all()
    )

    history: list[TopicQuizHistoryEntryResponse] = []
    for topic, user_roadmap, user_topic_quiz in rows:
        topic_sort_order = (
            (user_roadmap.sort_order + 1) if user_roadmap is not None else None
        )

        attempt_count = user_topic_quiz.attempt_count if user_topic_quiz else 0
        failed_attempts = user_topic_quiz.failed_attempts if user_topic_quiz else 0
        status = user_topic_quiz.status if user_topic_quiz else "locked"
        best_score_percent = (
            user_topic_quiz.best_score_percent
            if (user_topic_quiz and attempt_count > 0)
            else None
        )
        passed = status == "passed"

        user_answers = (
            _coerce_json_object(user_topic_quiz.user_answers)
            if user_topic_quiz
            else {}
        )
        best_attempt = (
            user_answers.get("best_attempt")
            or user_answers.get("latest_attempt")
            or {}
        )

        correct_count = (
            int(best_attempt.get("correct_count", 0))
            if isinstance(best_attempt, dict)
            else 0
        )
        total_questions = (
            int(best_attempt.get("total_questions", 30))
            if isinstance(best_attempt, dict)
            else 30
        )
        if (
            correct_count == 0
            and best_score_percent is not None
            and total_questions > 0
        ):
            correct_count = int(round(total_questions * (best_score_percent / 100.0)))

        completed_at = user_topic_quiz.completed_at if user_topic_quiz else None
        recorded_at = completed_at or (
            getattr(user_topic_quiz, "updated_at", None) if user_topic_quiz else None
        )

        history.append(
            TopicQuizHistoryEntryResponse(
                topic_id=topic.id,
                topic_name=topic.name,
                topic_sort_order=topic_sort_order,
                status=status,
                best_score_percent=best_score_percent,
                passed=passed,
                attempt_count=attempt_count,
                failed_attempts=failed_attempts,
                correct_count=correct_count,
                total_questions=total_questions,
                recorded_at=recorded_at,
                completed_at=completed_at,
            )
        )
    return history


def _build_final_quiz_history(
    db: Session, user_id: int, user: User
) -> list[FinalQuizHistoryEntryResponse]:
    user_courses = (
        db.query(UserCourse, Course)
        .join(Course, Course.id == UserCourse.course_id)
        .filter(UserCourse.user_id == user_id)
        .all()
    )

    if not user_courses:
        course = None
        if user.job_role_id:
            course = (
                db.query(Course)
                .filter(Course.job_role_id == user.job_role_id)
                .first()
            )
        if not course:
            course = db.query(Course).first()
        if course:
            return [
                FinalQuizHistoryEntryResponse(
                    course_id=course.id,
                    course_name=course.name,
                    status="locked",
                    best_score_percent=None,
                    passed=False,
                    progress=0.0,
                    attempt_count=0,
                    failed_attempts=0,
                    correct_count=0,
                    total_questions=50,
                    skill_scores=None,
                    unlocked_at=None,
                    completed_at=None,
                    recorded_at=None,
                )
            ]
        return []

    history: list[FinalQuizHistoryEntryResponse] = []
    for user_course, course in user_courses:
        status = user_course.status or "locked"
        attempt_count = user_course.attempt_count or 0
        failed_attempts = user_course.failed_attempts or 0
        best_score_percent = (
            user_course.best_score_percent if attempt_count > 0 else None
        )
        passed = status == "passed"

        user_answers = _coerce_json_object(user_course.user_answers)
        best_attempt = (
            user_answers.get("best_attempt")
            or user_answers.get("latest_attempt")
            or {}
        )

        correct_count = (
            int(best_attempt.get("correct_count", 0))
            if isinstance(best_attempt, dict)
            else 0
        )
        total_questions = (
            int(best_attempt.get("total_questions", 50))
            if isinstance(best_attempt, dict)
            else 50
        )
        if (
            correct_count == 0
            and best_score_percent is not None
            and total_questions > 0
        ):
            correct_count = int(round(total_questions * (best_score_percent / 100.0)))

        raw_skill_scores = user_course.skill_scores or (
            best_attempt.get("skill_scores")
            if isinstance(best_attempt, dict)
            else None
        )
        skill_scores: dict[str, float] | None = None
        if isinstance(raw_skill_scores, dict):
            skill_scores = {}
            for k, v in raw_skill_scores.items():
                if isinstance(v, (int, float)):
                    skill_scores[str(k)] = float(v)
                elif isinstance(v, dict) and "percent" in v and isinstance(v["percent"], (int, float)):
                    skill_scores[str(k)] = float(v["percent"])
                elif isinstance(v, dict) and "score_percent" in v and isinstance(v["score_percent"], (int, float)):
                    skill_scores[str(k)] = float(v["score_percent"])

        recorded_at = user_course.completed_at or getattr(user_course, "updated_at", None)
        history.append(
            FinalQuizHistoryEntryResponse(
                course_id=course.id,
                course_name=course.name,
                status=status,
                best_score_percent=best_score_percent,
                passed=passed,
                progress=user_course.progress or 0.0,
                attempt_count=attempt_count,
                failed_attempts=failed_attempts,
                correct_count=correct_count,
                total_questions=total_questions,
                skill_scores=skill_scores,
                unlocked_at=user_course.unlocked_at,
                completed_at=user_course.completed_at,
                recorded_at=user_course.completed_at or user_course.updated_at,
            )
        )
    return history


def _build_user_profile_response(db: Session, user: User) -> UserProfileResponse:
    roadmap_rows = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user.id)
        .order_by(UserRoadmap.created_at.asc(), UserRoadmap.sort_order.asc())
        .all()
    )

    started_at = user.created_at
    total_estimated_minutes = 0

    if roadmap_rows:
        started_at = roadmap_rows[0].created_at or user.created_at
        track = roadmap_rows[0].track
        topic_ids = [row.topic_id for row in roadmap_rows]
        assigned_lessons = (
            db.query(Lesson)
            .filter(Lesson.topic_id.in_(topic_ids))
            .order_by(Lesson.id.asc())
            .all()
        )
        total_estimated_minutes = sum(
            lesson.estimated_minutes or 0
            for lesson in assigned_lessons
            if lesson_is_assigned(track, lesson.difficulty_tier)
        )

    daily_study_minutes = user.daily_study_minutes or DEFAULT_DAILY_STUDY_MINUTES
    total_studied_minutes, study_history = _build_study_history(db, user.id)
    lesson_quiz_history = _build_lesson_quiz_history(db, user.id)
    topic_quiz_history = _build_topic_quiz_history(db, user.id)
    final_quiz_history = _build_final_quiz_history(db, user.id, user)
    initial_skill_scores, current_skill_scores = _build_skill_score_snapshots(
        db,
        user.id,
    )
    estimated_finish = None
    if total_estimated_minutes > 0:
        days_needed = max(1, ceil(total_estimated_minutes / daily_study_minutes))
        estimated_finish = date.today() + timedelta(days=days_needed - 1)

    quiz_review_count = (
        db.query(Queue)
        .filter(
            Queue.user_id == user.id,
            Queue.lesson_id.isnot(None),
            Queue.status == "pending",
        )
        .count()
    )

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role_id=user.role_id,
        created_at=user.created_at,
        started_at=started_at,
        estimated_finish=estimated_finish,
        total_estimated_minutes=total_estimated_minutes,
        daily_study_minutes=daily_study_minutes,
        total_studied_minutes=total_studied_minutes,
        study_history=study_history,
        lesson_quiz_history=lesson_quiz_history,
        topic_quiz_history=topic_quiz_history,
        final_quiz_history=final_quiz_history,
        initial_skill_scores=initial_skill_scores,
        current_skill_scores=current_skill_scores,
        quiz_review_count=quiz_review_count,
    )


def _reset_user_career_track(db: Session, user: User) -> None:
    try:
        db.query(UserCourse).filter(UserCourse.user_id == user.id).delete(
            synchronize_session=False
        )
        db.query(UserLesson).filter(UserLesson.user_id == user.id).delete(
            synchronize_session=False
        )
        db.query(UserRoadmap).filter(UserRoadmap.user_id == user.id).delete(
            synchronize_session=False
        )
        db.query(UserRadarScore).filter(UserRadarScore.user_id == user.id).delete(
            synchronize_session=False
        )
        db.query(UserPlacementTest).filter(
            UserPlacementTest.user_id == user.id
        ).delete(synchronize_session=False)
        db.query(Queue).filter(Queue.user_id == user.id).delete(
            synchronize_session=False
        )

        user.job_role_id = None
        user.learning_status = LEARNING_NONE
        db.add(user)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not reset career track. Please try again.",
        ) from exc


@router.get("/me", response_model=UserProfileResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _build_user_profile_response(db, current_user)


@router.patch("/me/study-settings", response_model=UserProfileResponse)
def update_study_settings(
    payload: StudySettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.daily_study_minutes = payload.daily_study_minutes
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _build_user_profile_response(db, current_user)


@router.delete("/me/career-track", status_code=status.HTTP_204_NO_CONTENT)
def delete_career_track(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _reset_user_career_track(db, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/ai-coach-message", response_model=AICoachMessageResponse)
async def generate_ai_coach_message(
    payload: AICoachMessageRequest,
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    prompt = PROMPT_E1_TEMPLATE.format(
        day_streak=payload.day_streak,
        lesson_learner=payload.lesson_learner,
        total_lesson_in_track=payload.total_lesson_in_track,
        accuracy=payload.accuracy,
        daily_study_per_day=payload.daily_study_per_day,
    )

    client = GeminiClientPool()
    try:
        response = await client.generate_json(prompt)
        result = json.loads(response.text)
        return AICoachMessageResponse(
            feedback_summary=result.get("feedback_summary", "Keep up the great work!")
        )
    except Exception:
        return AICoachMessageResponse(
            feedback_summary=(
                "Keep up the good work! Consistent practice is the key to "
                "mastering IT English."
            )
        )
    finally:
        await client.close()


@router.get("/me/quiz-review", response_model=QuizReviewListResponse)
def get_my_quiz_review(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve up to 5 wrong questions from previous lesson quizzes for morning review."""
    return get_user_quiz_review_items(db, current_user.id, limit=limit)


@router.post("/me/quiz-review/submit", response_model=QuizReviewSubmitResponse)
def submit_my_quiz_review(
    payload: QuizReviewSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit answers for review questions. Correct answers are removed from Queue;

    incorrect answers remain for future review.
    """
    return submit_user_quiz_review(
        db,
        current_user.id,
        [answer.model_dump() for answer in payload.answers],
    )


