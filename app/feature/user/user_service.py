"""User domain service — profile assembly, quiz histories, study tracking, and resets.

Extracted from user_router.py for single responsibility.
"""

from datetime import date, datetime, timedelta
import json
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.ai.client.gemini import GeminiClientPool, get_gemini_client_pool
from app.core.ai.dispatch.prompts import PROMPT_E1_TEMPLATE
from app.core.domain.learner_reset import reset_learner
from app.core.domain.roadmap import lesson_is_assigned
from app.core.infra.config import app_config
from app.feature.quiz.final_quiz_service import FINAL_QUIZ_SIZE
from app.feature.user.user_schema import (
    AICoachMessageRequest,
    AICoachMessageResponse,
    FinalQuizHistoryEntryResponse,
    LessonQuizHistoryEntryResponse,
    StreakRestoreRequest,
    StreakStatusResponse,
    TopicQuizHistoryEntryResponse,
    UserProfileResponse,
)
from app.feature.user.user_serializers import (
    _coerce_json_object,
    _compute_hint_breakdown,
    _derive_lesson_quiz_status,
    _extract_best_passing_attempt,
    _extract_best_passing_score,
    _extract_latest_attempt,
    _normalize_skill_vector,
    _parse_iso_datetime,
)
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.queue import Queue
from app.models.system_setting import SystemSetting
from app.models.topic import Topic
from app.models.user import User
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_lesson import UserLesson
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

DEFAULT_DAILY_STUDY_MINUTES = app_config.DEFAULT_DAILY_STUDY_MINUTES
RESTORE_MINUTES_PER_DAY = app_config.STREAK_RESTORE_MINUTES_PER_DAY


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
        db.query(UserFinalQuiz, JobRole)
        .join(JobRole, JobRole.id == UserFinalQuiz.job_role_id)
        .filter(UserFinalQuiz.user_id == user_id)
        .all()
    )

    if not user_courses:
        course = None
        if user.job_role_id:
            course = db.query(JobRole).filter(JobRole.id == user.job_role_id).first()
        if course:
            return [
                FinalQuizHistoryEntryResponse(
                    job_role_id=course.id,
                    role_name=course.name,
                    status="locked",
                    best_score_percent=None,
                    passed=False,
                    progress=0.0,
                    attempt_count=0,
                    failed_attempts=0,
                    correct_count=0,
                    total_questions=FINAL_QUIZ_SIZE,
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
            int(best_attempt.get("total_questions", FINAL_QUIZ_SIZE))
            if isinstance(best_attempt, dict)
            else FINAL_QUIZ_SIZE
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
                job_role_id=course.id,
                role_name=course.name,
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


def build_user_profile_response(db: Session, user: User) -> UserProfileResponse:
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

    # Compute avatar URL from stored file path
    avatar_url = None
    if user.avatar_path:
        avatar_url = f"{app_config.STATIC_URL_PREFIX.rstrip('/')}/uploads/{user.avatar_path}"

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role_id=user.role_id,
        avatar_url=avatar_url,
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


_build_user_profile_response = build_user_profile_response


def reset_user_career_track(db: Session, user: User) -> None:
    try:
        # Self-serve reset keeps the learner's own vocabulary list.
        reset_learner(db, user, clear_flashcards=False)
        db.add(user)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not reset career track. Please try again.",
        ) from exc


_reset_user_career_track = reset_user_career_track


async def generate_ai_coach_message_service(
    payload: AICoachMessageRequest,
) -> AICoachMessageResponse:
    prompt = PROMPT_E1_TEMPLATE.format(
        day_streak=payload.day_streak,
        lesson_learner=payload.lesson_learner,
        total_lesson_in_track=payload.total_lesson_in_track,
        accuracy=payload.accuracy,
        daily_study_per_day=payload.daily_study_per_day,
    )

    client = get_gemini_client_pool()
    try:
        response = await client.generate_json(prompt, preferred_provider="groq")
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


def _get_streak_restore_data(db: Session, user_id: int) -> dict:
    setting_key = f"streak_restore:{user_id}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except Exception:
            return {"used_credits": 0, "restored_dates": []}
    return {"used_credits": 0, "restored_dates": []}


def _save_streak_restore_data(db: Session, user_id: int, data: dict) -> None:
    setting_key = f"streak_restore:{user_id}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()
    val = json.dumps(data)
    if setting:
        setting.value = val
    else:
        setting = SystemSetting(key=setting_key, value=val)
        db.add(setting)
    db.commit()


def _calc_longest_streak(date_strs: list[str]) -> int:
    if not date_strs:
        return 0
    unique_dates = sorted(set(date_strs))
    longest = 0
    current = 0
    prev_date = None
    for d_str in unique_dates:
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if prev_date is not None and d == prev_date + timedelta(days=1):
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        prev_date = d
    return longest


def _calc_current_streak(date_strs: list[str], today: date | None = None) -> int:
    if not date_strs:
        return 0
    if today is None:
        today = date.today()
    date_set = set(date_strs)

    check_date = today
    if today.isoformat() not in date_set:
        yesterday = today - timedelta(days=1)
        if yesterday.isoformat() in date_set:
            check_date = yesterday
        else:
            return 0

    streak = 0
    while check_date.isoformat() in date_set:
        streak += 1
        check_date -= timedelta(days=1)
    return streak


def get_user_streak_status(
    db: Session,
    user: User,
    client_study_minutes: int | None = None,
) -> StreakStatusResponse:
    db_total_minutes, _ = _build_study_history(db, user.id)
    restore_data = _get_streak_restore_data(db, user.id)
    used_credits = int(restore_data.get("used_credits", 0))
    restored_dates = list(restore_data.get("restored_dates", []))

    baseline_minutes = restore_data.get("baseline_minutes")
    if baseline_minutes is None:
        if "accumulated_study_minutes" in restore_data:
            baseline_minutes = int(restore_data["accumulated_study_minutes"])
        else:
            baseline_minutes = db_total_minutes
        restore_data["baseline_minutes"] = baseline_minutes
        _save_streak_restore_data(db, user.id, restore_data)

    eligible_db_minutes = max(0, db_total_minutes - int(baseline_minutes))
    client_minutes = max(0, client_study_minutes or 0)
    total_studied_minutes = eligible_db_minutes + client_minutes

    total_earned_credits = total_studied_minutes // RESTORE_MINUTES_PER_DAY
    available_credits = max(0, total_earned_credits - used_credits)
    progress_minutes = total_studied_minutes % RESTORE_MINUTES_PER_DAY
    progress_percent = round((progress_minutes / RESTORE_MINUTES_PER_DAY) * 100, 1)

    completed_dates = {
        row[0].date().isoformat()
        for row in db.query(UserLesson.completed_at)
        .filter(
            UserLesson.user_id == user.id,
            UserLesson.status == "completed",
            UserLesson.completed_at.isnot(None),
        )
        .all()
        if row[0] is not None
    }
    all_active_dates = sorted(completed_dates.union(set(restored_dates)))

    current_streak = _calc_current_streak(all_active_dates)
    longest_streak = _calc_longest_streak(all_active_dates)

    return StreakStatusResponse(
        total_studied_minutes=total_studied_minutes,
        required_minutes_per_day=RESTORE_MINUTES_PER_DAY,
        total_earned_credits=total_earned_credits,
        used_credits=used_credits,
        available_credits=available_credits,
        progress_minutes=progress_minutes,
        progress_percent=progress_percent,
        restored_dates=sorted(set(restored_dates)),
        current_streak=current_streak,
        longest_streak=longest_streak,
    )


def restore_user_streak(
    db: Session,
    user: User,
    dates: list[str],
    client_study_minutes: int | None = None,
) -> StreakStatusResponse:
    today = date.today()
    clean_dates: list[str] = []
    for d_str in dates:
        try:
            d = date.fromisoformat(d_str.strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format: {d_str}. Expected YYYY-MM-DD.",
            )
        if d > today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot restore future date: {d_str}.",
            )
        clean_dates.append(d.isoformat())

    unique_dates_to_restore = sorted(set(clean_dates))
    restore_data = _get_streak_restore_data(db, user.id)
    current_restored = set(restore_data.get("restored_dates", []))
    new_dates = [d for d in unique_dates_to_restore if d not in current_restored]

    if not new_dates:
        return get_user_streak_status(db, user, client_study_minutes)

    db_total_minutes, _ = _build_study_history(db, user.id)
    baseline_minutes = restore_data.get("baseline_minutes")
    if baseline_minutes is None:
        baseline_minutes = restore_data.get("accumulated_study_minutes", db_total_minutes)
        restore_data["baseline_minutes"] = int(baseline_minutes)

    eligible_db_minutes = max(0, db_total_minutes - int(baseline_minutes))
    client_minutes = max(0, client_study_minutes or 0)
    total_studied_minutes = eligible_db_minutes + client_minutes
    total_earned_credits = total_studied_minutes // RESTORE_MINUTES_PER_DAY
    used_credits = int(restore_data.get("used_credits", 0))
    available_credits = max(0, total_earned_credits - used_credits)

    if len(new_dates) > available_credits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Not enough restore credits. Required: {len(new_dates)}, "
                f"available: {available_credits}. "
                f"You must accumulate {RESTORE_MINUTES_PER_DAY} minutes of study time per restored day."
            ),
        )

    updated_restored = sorted(current_restored.union(set(new_dates)))
    updated_used = used_credits + len(new_dates)
    data_to_save = {
        "used_credits": updated_used,
        "restored_dates": updated_restored,
        "baseline_minutes": int(baseline_minutes),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_streak_restore_data(db, user.id, data_to_save)

    return get_user_streak_status(db, user, client_study_minutes)

