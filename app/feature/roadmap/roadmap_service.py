"""Course Roadmap engine for CareerPath.

Computes 8-topic zero-AI roadmaps (spec §2.C), calculates topic unlock progression,
evaluates sequential lesson unlocking, and handles roadmap recomputations.
Extracted from placement_test_service.py for single responsibility.
"""

import json
from typing import TYPE_CHECKING, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.core.infra.notification_stream import notification_stream_broker
from app.core.domain.roadmap import (
    SKILLS,
    assigned_lessons,
    lesson_is_assigned,
    select_roadmap,
)
from app.feature.onboarding.placement_evaluator import classify_user
from app.feature.roadmap.roadmap_schema import (
    DevPlacementOverrideRequest,
    RoadmapLessonResponse,
    RoadmapResponse,
    RoadmapTopicResponse,
)
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user import LEARNING_ENROLLED, User
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_lesson import UserLesson
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz


def _roadmap_shells(db: Session, role_id: int) -> list[Lesson]:
    """All lesson shells of a role (used to count assigned lessons per skill)."""
    return (
        db.query(Lesson)
        .join(Topic, Lesson.topic_id == Topic.id)
        .filter(Topic.role_id == role_id)
        .all()
    )


def _build_and_save_roadmap(
    db: Session,
    user_id: int,
    *,
    weak_skills: list[str] | None = None,
    track: str | None = None,
    role_id: int | None = None,
    raise_on_missing: bool = False,
    commit: bool = True,
) -> None:
    """Select the user's 8-topic roadmap (spec §2.C) and persist it
    (idempotent delete+insert). When `raise_on_missing` is False the function
    returns silently if the prerequisites are missing (placement answers not
    saved yet, or the role has no course outline) — the placement-test trigger
    uses that mode; a later recompute fills the roadmap.
    """
    from app.feature.onboarding.placement_test_service import compute_skill_scores

    # Lock user row to serialize concurrent roadmap modifications for the same user
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return

    role_id = role_id or user.job_role_id
    if not role_id:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No career track selected yet",
            )
        return

    if weak_skills is None or track is None:
        scores = compute_skill_scores(db, user_id)
        if not scores:
            if raise_on_missing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No placement test answers to build a roadmap from",
                )
            return
        track, weak_skills = classify_user(scores)

    topics = (
        db.query(Topic)
        .filter(Topic.role_id == role_id)
        .order_by(Topic.sort_order.asc())
        .all()
    )
    if not topics:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No course outline for this track yet (B1/B2 not run). "
                    "Generate it in the Admin portal first."
                ),
            )
        return

    shells = _roadmap_shells(db, role_id)
    selected = select_roadmap(
        user_id=user.id,
        role_id=role_id,
        weak_skills=weak_skills,
        role_topics=topics,
        lesson_shells=shells,
        track=track,
    )

    db.query(UserRoadmap).filter(UserRoadmap.user_id == user_id).delete()
    for i, topic in enumerate(selected):
        db.add(
            UserRoadmap(user_id=user_id, topic_id=topic.id, sort_order=i, track=track)
        )
    if commit:
        db.commit()
    else:
        db.flush()
    notification_stream_broker.publish_nowait(
        user_id,
        {
            "type": "roadmap_updated",
            "reason": "roadmap_changed",
        },
    )


def build_and_save_roadmap(db: Session, user_id: int, commit: bool = True) -> None:
    """Silent roadmap build used by the placement-test completion trigger."""
    _build_and_save_roadmap(db, user_id, commit=commit)


def _compute_topic_unlock_map(
    topic_lessons: list[Lesson],
    completed_lesson_ids: set[int],
) -> dict[int, bool]:
    unlock_map: dict[int, bool] = {}
    previous_lesson_id: int | None = None

    for lesson in topic_lessons:
        unlock_map[lesson.id] = (
            previous_lesson_id is None
            or previous_lesson_id in completed_lesson_ids
        )
        previous_lesson_id = lesson.id

    return unlock_map


def get_assigned_topic_lessons(
    db: Session,
    topic_id: int,
    track: str,
) -> list[Lesson]:
    lessons = (
        db.query(Lesson)
        .filter(Lesson.topic_id == topic_id)
        .order_by(Lesson.id.asc())
        .all()
    )
    return [
        lesson
        for lesson in lessons
        if lesson_is_assigned(track, lesson.difficulty_tier)
    ]


def get_completed_lesson_ids_for_topic(
    db: Session,
    user_id: int,
    topic_id: int,
) -> set[int]:
    rows = (
        db.query(UserLesson.lesson_id)
        .join(Lesson, Lesson.id == UserLesson.lesson_id)
        .filter(
            UserLesson.user_id == user_id,
            UserLesson.completed_at.isnot(None),
            Lesson.topic_id == topic_id,
        )
        .all()
    )
    return {int(lesson_id) for (lesson_id,) in rows}


def lesson_is_unlocked_for_user(
    db: Session,
    user_id: int,
    lesson: Lesson,
    track: str,
) -> bool:
    topic_lessons = get_assigned_topic_lessons(db, lesson.topic_id, track)
    completed_lesson_ids = get_completed_lesson_ids_for_topic(
        db,
        user_id,
        lesson.topic_id,
    )
    unlock_map = _compute_topic_unlock_map(topic_lessons, completed_lesson_ids)
    return unlock_map.get(lesson.id, False)


def is_lesson_generated_and_valid(lesson: Lesson) -> bool:
    """Check if a lesson is marked generated and has valid modern C-1/C-2 structure."""
    return bool(
        lesson.is_generated
        and isinstance(lesson.theory_content, dict)
        and isinstance(lesson.theory_content.get("reading", {}).get("document"), dict)
    )


def get_first_assigned_lesson_ids(db: Session, user_id: int) -> list[int]:
    """Return the first assigned lesson id for each topic in the user's roadmap."""
    rows = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .order_by(UserRoadmap.sort_order.asc())
        .all()
    )
    if not rows:
        return []

    track = rows[0].track
    topic_ids = [row.topic_id for row in rows]
    lessons = (
        db.query(Lesson)
        .filter(Lesson.topic_id.in_(topic_ids))
        .order_by(Lesson.topic_id.asc(), Lesson.id.asc())
        .all()
    )

    first_lesson_ids: list[int] = []
    seen_topic_ids: set[int] = set()
    for lesson in lessons:
        if lesson.topic_id in seen_topic_ids:
            continue
        if not lesson_is_assigned(track, lesson.difficulty_tier):
            continue
        if is_lesson_generated_and_valid(lesson):
            seen_topic_ids.add(lesson.topic_id)
            continue
        first_lesson_ids.append(lesson.id)
        seen_topic_ids.add(lesson.topic_id)

    return first_lesson_ids


def sanitize_quiz_content_for_client(quiz_content: Any) -> Any | None:
    """
    Strips out correct_answer (index 2) and explanation (index 3) from each
    question row in lesson quiz_content, replacing them with empty strings.
    This prevents cheating via browser network inspection and LocalStorage drafts,
    while maintaining the 4-element row structure expected by client parsers.
    """
    if not quiz_content:
        return None

    parsed = quiz_content
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return None

    if not isinstance(parsed, dict):
        return None

    sanitized: dict[str, list[Any]] = {}
    for qtype in ("fill_blank", "multi_select", "ordering"):
        items = parsed.get(qtype)
        if isinstance(items, list):
            sanitized[qtype] = [
                [row[0], row[1], "", ""] + list(row[4:])
                if isinstance(row, list) and len(row) >= 4
                else row
                for row in items
            ]
        else:
            sanitized[qtype] = []
    return sanitized


def get_user_roadmap(db: Session, user_id: int) -> RoadmapResponse:
    """Fetch the user's roadmap with lessons inline. Auto-computes when empty."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    rows = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .order_by(UserRoadmap.sort_order.asc())
        .all()
    )
    if not rows:
        _build_and_save_roadmap(db, user_id)
        rows = (
            db.query(UserRoadmap)
            .filter(UserRoadmap.user_id == user_id)
            .order_by(UserRoadmap.sort_order.asc())
            .all()
        )
    if not rows:
        return RoadmapResponse(track="", topics=[], assigned_lessons={})

    track = rows[0].track
    topic_ids = [r.topic_id for r in rows]
    order = {r.topic_id: r.sort_order for r in rows}
    topics = db.query(Topic).filter(Topic.id.in_(topic_ids)).all()
    topics.sort(key=lambda t: order[t.id])

    lessons = (
        db.query(Lesson)
        .filter(Lesson.topic_id.in_(topic_ids))
        .order_by(Lesson.id.asc())
        .all()
    )
    lessons_by_topic: dict[int, list[Lesson]] = {}
    for lesson in lessons:
        if lesson_is_assigned(track, lesson.difficulty_tier):
            lessons_by_topic.setdefault(lesson.topic_id, []).append(lesson)

    completed_lesson_ids_by_topic: dict[int, set[int]] = {}
    if topic_ids:
        completed_rows = (
            db.query(UserLesson.lesson_id, Lesson.topic_id)
            .join(Lesson, Lesson.id == UserLesson.lesson_id)
            .filter(
                UserLesson.user_id == user_id,
                UserLesson.completed_at.isnot(None),
                Lesson.topic_id.in_(topic_ids),
            )
            .all()
        )
        for lesson_id, topic_id in completed_rows:
            completed_lesson_ids_by_topic.setdefault(int(topic_id), set()).add(
                int(lesson_id)
            )

    topic_quiz_records: dict[int, UserTopicQuiz] = {}
    if topic_ids:
        for record in (
            db.query(UserTopicQuiz)
            .filter(
                UserTopicQuiz.user_id == user_id,
                UserTopicQuiz.topic_id.in_(topic_ids),
            )
            .all()
        ):
            topic_quiz_records[int(record.topic_id)] = record

    roadmap_topics: list[RoadmapTopicResponse] = []
    total_estimated_minutes = 0
    for topic in topics:
        topic_lessons = lessons_by_topic.get(topic.id, [])
        completed_set = completed_lesson_ids_by_topic.get(topic.id, set())
        unlock_map = _compute_topic_unlock_map(
            topic_lessons,
            completed_set,
        )
        topic_minutes = sum((lesson.estimated_minutes or 0) for lesson in topic_lessons)
        total_estimated_minutes += topic_minutes

        all_lessons_completed = (
            len(topic_lessons) > 0
            and all(l.id in completed_set for l in topic_lessons)
        )
        tq_rec = topic_quiz_records.get(topic.id)
        if tq_rec is not None and tq_rec.status == "passed":
            tq_status = "passed"
        elif all_lessons_completed:
            tq_status = tq_rec.status if (tq_rec and tq_rec.status in ("ready", "failed")) else "ready"
        else:
            tq_status = "locked"

        tq_score = tq_rec.best_score_percent if (tq_rec and tq_rec.attempt_count > 0) else None
        tq_attempts = tq_rec.attempt_count if tq_rec else 0
        weakest_ids = [int(x) for x in (tq_rec.weakest_lesson_ids or [])] if (tq_rec and tq_status == "failed") else []

        roadmap_topics.append(
            RoadmapTopicResponse(
                id=topic.id,
                name=topic.name,
                primary_skill=topic.primary_skill,
                seed_tier=topic.seed_tier,
                sort_order=order[topic.id] + 1,
                total_estimated_minutes=topic_minutes,
                topic_quiz_status=tq_status,
                topic_quiz_score=tq_score,
                topic_quiz_attempt_count=tq_attempts,
                weakest_lesson_ids=weakest_ids,
                lessons=[
                    RoadmapLessonResponse(
                        id=lesson.id,
                        title=lesson.title,
                        primary_skill=lesson.primary_skill,
                        difficulty_tier=lesson.difficulty_tier,
                        estimated_minutes=lesson.estimated_minutes,
                        is_generated=is_lesson_generated_and_valid(lesson),
                        is_unlocked=unlock_map.get(lesson.id, False),
                        is_completed=lesson.id in completed_set,
                        theory_content=(
                            lesson.theory_content
                            if unlock_map.get(lesson.id, False) and isinstance(lesson.theory_content, dict)
                            else None
                        ),
                        quiz_content=(
                            sanitize_quiz_content_for_client(lesson.quiz_content)
                            if unlock_map.get(lesson.id, False)
                            else None
                        ),
                    )
                    for lesson in topic_lessons
                ],
            )
        )

    all_topic_quizzes_passed = (
        len(roadmap_topics) > 0
        and all(t.topic_quiz_status == "passed" for t in roadmap_topics)
    )

    user_course = (
        db.query(UserFinalQuiz)
        .filter(UserFinalQuiz.user_id == user_id)
        .first()
    )
    if not all_topic_quizzes_passed:
        final_quiz_status = "locked"
    elif user_course and user_course.status == "passed":
        final_quiz_status = "passed"
    elif user_course and user_course.status == "failed":
        final_quiz_status = "failed"
    else:
        final_quiz_status = "ready"

    final_quiz_score = (
        user_course.best_score_percent
        if (user_course and user_course.attempt_count > 0)
        else None
    )
    final_quiz_attempts = user_course.attempt_count if user_course else 0

    return RoadmapResponse(
        track=track,
        topics=roadmap_topics,
        assigned_lessons=assigned_lessons(topics, lessons, track),
        total_estimated_minutes=total_estimated_minutes,
        final_quiz_status=final_quiz_status,
        final_quiz_score=final_quiz_score,
        final_quiz_attempt_count=final_quiz_attempts,
        all_topic_quizzes_passed=all_topic_quizzes_passed,
    )


def recompute_roadmap(
    db: Session,
    user_id: int,
    *,
    skills: DevPlacementOverrideRequest | None = None,
    role_id: int | None = None,
) -> RoadmapResponse:
    """Force-recompute the roadmap (idempotent delete+insert).

    - Without `skills`: rebuilds from the user's stored placement answers
      (existing E2E use).
    - With `skills` (dev-mode): skips placement answers entirely —
      weighted accuracy from difficulty breakdown -> classify -> select ->
      initialize radar. Returns 404 in production.
    """
    if skills is not None:
        if app_config.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill-score override is disabled in production",
            )
        fractions = skills.as_fractions()
        track, weak_skills = classify_user(fractions)
        user = db.query(User).filter(User.id == user_id).first()
        role_id = role_id or (user.job_role_id if user else None)
        if not role_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No career track selected yet",
            )
        _build_and_save_roadmap(
            db,
            user_id,
            weak_skills=weak_skills,
            track=track,
            role_id=role_id,
            raise_on_missing=True,
            commit=False,
        )
        if user is not None:
            user.job_role_id = role_id
            user.learning_status = LEARNING_ENROLLED

        INITIAL_RADAR_SCALE = 0.85
        db.query(UserRadarScore).filter(
            UserRadarScore.user_id == user_id
        ).delete()
        start_vector = {
            skill: fractions[skill] * 100 * INITIAL_RADAR_SCALE
            for skill in SKILLS
        }
        prev_stack = {s: [] for s in SKILLS}
        radar = UserRadarScore(
            user_id=user_id,
            start_vector=start_vector,
            current_vector=start_vector.copy(),
            prev_stack=prev_stack,
        )
        db.add(radar)
        db.commit()
    else:
        _build_and_save_roadmap(db, user_id, raise_on_missing=True)

    return get_user_roadmap(db, user_id)
