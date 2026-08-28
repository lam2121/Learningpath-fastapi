import json

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import app_config
from app.core.notification_stream import notification_stream_broker
from app.core.roadmap import (
    SKILLS,
    assigned_lessons,
    lesson_is_assigned,
    select_roadmap,
)
from app.feature.onboarding.placement_evaluator import classify_user
from app.feature.onboarding.placement_test_schema import (
    PlacementAnswerDetail,
    PlacementResultResponse,
    PlacementTestQuestionResponse,
)
from app.feature.onboarding.roadmap_schema import (
    DevPlacementOverrideRequest,
    RoadmapLessonResponse,
    RoadmapResponse,
    RoadmapTopicResponse,
)
from app.models.job_role import DEFAULT_BASELINE, JobRole
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.queue import Queue
from app.models.topic import Topic
from app.models.user import LEARNING_ENROLLED, LEARNING_NONE
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap

# Map v2.1 full tag -> short letter used by the existing frontend response
SKILL_TAG_TO_SHORT = {
    "D_doc": "D",
    "C_comm": "C",
    "T_trouble": "T",
    "G_custom": "G",
}

# level column stores plain strings: 'Easy' | 'Medium' | 'Hard'

# Difficulty-weighted scoring (v3: learning-path-scoring-design-v3.md §3)
# Each skill: 4×Easy (weight 1) + 4×Medium (weight 2) + 4×Hard (weight 3)
# = 4 + 8 + 12 = 24
DIFFICULTY_WEIGHT: dict[str, int] = {
    "Easy": 1,
    "Medium": 2,
    "Hard": 3,
}
MAX_SKILL_WEIGHT = 24


def _cleanup_user_progress(db: Session, user_id: int) -> None:
    """Remove all learning progress for a user.

    Deletes: lesson progress, radar scores, SM-2 spaced-repetition queue.
    Placement answers and roadmap are handled separately by the caller.
    """
    db.query(UserLesson).filter(UserLesson.user_id == user_id).delete()
    db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).delete()
    db.query(Queue).filter(Queue.user_id == user_id).delete()


def fetch_questions_by_role(
    db: Session, role_id: int
) -> list[PlacementTestQuestionResponse]:
    """
    Fetch all placement_test_question rows for a given job_role_id.
    Parses the JSON `question` column and returns structured response objects.
    """
    records = (
        db.query(PlacementTestQuestion)
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .order_by(PlacementTestQuestion.id.asc())
        .all()
    )

    results: list[PlacementTestQuestionResponse] = []

    for record in records:
        # Parse the JSON `question` column (stored as TEXT or JSON in MySQL)
        raw = record.question
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(raw, dict):
            data = raw
        else:
            continue

        statement = data.get("statement", "")
        options = data.get("options", [])
        correct_answer = data.get("correct_answer", "")

        # Validate that options is a non-empty list and correct_answer exists
        if (
            not statement
            or not isinstance(options, list)
            or not options
            or not correct_answer
        ):
            continue

        # Ensure all options are strings
        options = [str(o) for o in options]

        results.append(
            PlacementTestQuestionResponse(
                id=record.id,
                skill=SKILL_TAG_TO_SHORT.get(
                    record.skill, record.skill
                ),  # 'D' | 'C' | 'T' | 'G'
                level=record.level,  # 'Easy' | 'Medium' | 'Hard' | 'Expert'
                statement=statement,
                options=options,
                correct_answer=correct_answer,
                expanded_skill=record.expanded_skill,
            )
        )

    return results


def save_user_placement_test_answers(db: Session, user_id: int, answers: list) -> int:
    """Persist a user's placement-test answers (one row per question) into
    user_placement_test. Re-runs replace the user's previous attempt."""
    db.execute(
        text("DELETE FROM user_placement_test WHERE user_id = :user_id"),
        {"user_id": user_id},
    )

    count = 0
    for item in answers:
        question_id = getattr(
            item,
            "question_id",
            item.get("question_id") if isinstance(item, dict) else None,
        )
        selected_id = getattr(
            item,
            "selected_id",
            item.get("selected_id") if isinstance(item, dict) else None,
        )
        selected_text = getattr(
            item,
            "selected_text",
            item.get("selected_text") if isinstance(item, dict) else None,
        )
        is_correct = getattr(
            item,
            "is_correct",
            item.get("is_correct") if isinstance(item, dict) else None,
        )
        axis = getattr(
            item, "axis", item.get("axis") if isinstance(item, dict) else None
        )
        difficulty = getattr(
            item,
            "difficulty",
            item.get("difficulty") if isinstance(item, dict) else None,
        )

        if question_id is None:
            continue

        db.execute(
            text(
                """
                INSERT INTO user_placement_test (
                    placement_test_question_id,
                    user_id,
                    user_answer
                ) VALUES (
                    :placement_test_question_id,
                    :user_id,
                    :user_answer
                )
                """
            ),
            {
                "placement_test_question_id": int(question_id),
                "user_id": user_id,
                "user_answer": json.dumps(
                    {
                        "selected_id": selected_id,
                        "selected_text": selected_text,
                        "is_correct": is_correct,
                        "axis": axis,
                        "difficulty": difficulty,
                    }
                ),
            },
        )
        count += 1

    db.flush()
    return count


def complete_placement_test(
    db: Session,
    user_id: int,
    role_id: int | None = None,
    placement_test_answers: list | None = None,
) -> bool:
    """Finalize onboarding: record placement answers, assign the selected role,
    and mark the user's placement test as finished."""
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    existing_answer = (
        db.query(UserPlacementTest.id)
        .filter(UserPlacementTest.user_id == user_id)
        .first()
    )
    if existing_answer is not None:
        # Re-enrollment (e.g. "Change Career Track"): clean up previous
        # progress so the user starts fresh with the new track.
        _cleanup_user_progress(db, user_id)
        db.query(UserPlacementTest).filter(
            UserPlacementTest.user_id == user_id
        ).delete()

    if role_id:
        role = db.query(JobRole).filter(JobRole.id == role_id).first()
        if role is not None and not role.is_active and user.job_role_id != role_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Career track '{role.name}' is deactivated and is not accepting "
                    "new learners. Please select an active track or contact your "
                    "administrator."
                ),
            )
        user.job_role_id = role_id  # Store selected job role (FK to job_role table)

    if placement_test_answers:
        save_user_placement_test_answers(
            db, user_id=user_id, answers=placement_test_answers
        )

    user.learning_status = LEARNING_ENROLLED
    db.commit()

    # Phase A: build the zero-AI learning roadmap (spec §2.C) from the saved
    # answers. Silently skips when the role has no topics yet (B1/B2 not run);
    # a later recompute (POST /onboarding/roadmap/select) fills it.
    build_and_save_roadmap(db, user_id)
    
    # Initialize Radar Score from placement test
    _initialize_radar_score(db, user_id)
    
    return True


def _initialize_radar_score(db: Session, user_id: int):
    """
    Computes and persists the initial radar score based on the placement test
    weighted accuracy (spec §3), and saves it into UserRadarScore.
    start_vector = weighted_accuracy × INITIAL_RADAR_SCALE per skill.
    """
    # Delete any existing record for this user
    db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).delete()

    rows = _load_placement_answer_rows(db, user_id)
    if not rows:
        return

    # _parse_answer_rows returns a 4-tuple; we only need answers + earned weights
    answers, _skill_correct, _skill_total, skill_earned_weight = _parse_answer_rows(rows)
    if not answers:
        return

    INITIAL_RADAR_SCALE = 0.85

    start_vector = {
        skill: (skill_earned_weight[skill] / MAX_SKILL_WEIGHT) * 100 * INITIAL_RADAR_SCALE
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


def _load_placement_answer_rows(db: Session, user_id: int):
    """Load a user's saved placement answers joined with their questions."""
    return (
        db.query(UserPlacementTest, PlacementTestQuestion)
        .join(
            PlacementTestQuestion,
            UserPlacementTest.placement_test_question_id == PlacementTestQuestion.id,
        )
        .filter(UserPlacementTest.user_id == user_id)
        .all()
    )


def _parse_answer_rows(rows) -> tuple[list[PlacementAnswerDetail], dict, dict]:
    """Build per-question detail + per-skill correct/total counts.

    Shared by `get_placement_test_result` and `compute_skill_scores` so the
    answer-parsing logic lives in exactly one place.
    """
    answers: list[PlacementAnswerDetail] = []
    skill_correct: dict[str, int] = {s: 0 for s in SKILLS}
    skill_total: dict[str, int] = {s: 0 for s in SKILLS}
    skill_earned_weight: dict[str, int] = {s: 0 for s in SKILLS}

    for user_test, question in rows:
        # Parse user_answer JSON
        user_answer = {}
        if isinstance(user_test.user_answer, str):
            try:
                user_answer = json.loads(user_test.user_answer)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(user_test.user_answer, dict):
            user_answer = user_test.user_answer
        else:
            continue

        # Parse question.question JSON
        question_data = {}
        if isinstance(question.question, str):
            try:
                question_data = json.loads(question.question)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(question.question, dict):
            question_data = question.question
        else:
            continue

        statement = question_data.get("statement", "")
        options = question_data.get("options", [])
        correct_answer = question_data.get("correct_answer", "")

        # Validate question data
        if (
            not statement
            or not isinstance(options, list)
            or not options
            or not correct_answer
        ):
            continue

        # Ensure options are strings
        options = [str(o) for o in options]

        # Build answer detail
        answer = PlacementAnswerDetail(
            question_id=question.id,
            axis=question.skill,  # authoritative skill tag (D_doc, ...)
            level=user_answer.get("difficulty", question.level),
            statement=statement,
            options=options,
            correct_answer=correct_answer,
            selected_id=user_answer.get("selected_id", ""),
            selected_text=user_answer.get("selected_text"),
            is_correct=user_answer.get("is_correct", False),
            expanded_skill=getattr(question, "expanded_skill", None),
        )
        answers.append(answer)

        # Group by authoritative skill tag (ignore stored axis)
        skill = question.skill
        if skill not in skill_correct:
            continue
        skill_total[skill] += 1
        if answer.is_correct:
            skill_correct[skill] += 1
            weight = DIFFICULTY_WEIGHT.get(answer.level, 1)
            skill_earned_weight[skill] += weight

    return answers, skill_correct, skill_total, skill_earned_weight


def compute_skill_scores(db: Session, user_id: int) -> dict[str, float] | None:
    """Compute per-skill fraction-correct scores from saved placement answers.

    Returns None when the user has no saved answers (e.g. placement not taken).
    """
    rows = _load_placement_answer_rows(db, user_id)
    if not rows:
        return None
    _, _skill_correct, _skill_total, skill_earned_weight = _parse_answer_rows(rows)
    return {
        skill: skill_earned_weight[skill] / MAX_SKILL_WEIGHT for skill in SKILLS
    }


def get_placement_test_result(db: Session, user_id: int) -> PlacementResultResponse:
    """
    Fetch a user's placement test result from user_placement_test + placement_test_question.
    Returns computed scores, starting level, and per-question detail.
    """
    from app.models.job_role import JobRole
    from app.models.user import User

    # Load user and check if placement is finished
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return PlacementResultResponse(
            learning_status=LEARNING_NONE,
            total_questions=0,
            total_correct=0,
            overall_percent=0,
            skill_scores={},
            starting_level="basic",
            weak_skills=[],
            answers=[],
        )

    rows = _load_placement_answer_rows(db, user_id)
    if not rows:
        return PlacementResultResponse(
            learning_status=user.learning_status,
            total_questions=0,
            total_correct=0,
            overall_percent=0,
            skill_scores={},
            starting_level="basic",
            weak_skills=[],
            answers=[],
        )

    # Parse answers + accumulate per-skill counts (shared with compute_skill_scores)
    answers, skill_correct, skill_total, skill_earned_weight = _parse_answer_rows(rows)

    # Difficulty-weighted accuracy per skill (spec §3)
    # Score = earned_weight / MAX_SKILL_WEIGHT (24) × 100
    skill_scores_fraction: dict[str, float] = {
        skill: skill_earned_weight[skill] / MAX_SKILL_WEIGHT for skill in SKILLS
    }

    # Raw counts (used for display: "X / Y correct")
    total_questions = sum(skill_total.values())
    total_correct = sum(skill_correct.values())
    # Overall percent = average weighted accuracy across all 4 skills
    overall_percent = round(sum(skill_scores_fraction.values()) / max(1, len(SKILLS)) * 100)

    # Classify starting level and weak skills
    starting_level, weak_skills = classify_user(skill_scores_fraction)

    # Load role and baseline for target bars
    role_id: int | None = None
    role_name: str | None = None
    baseline: dict[str, int] | None = None
    if user.job_role_id:
        role = db.query(JobRole).filter(JobRole.id == user.job_role_id).first()
        if role:
            role_id = role.id
            role_name = role.name
            baseline = role.baseline or DEFAULT_BASELINE

    # Convert skill_scores to percent integers
    skill_scores_percent = {
        skill: round(score * 100) for skill, score in skill_scores_fraction.items()
    }

    # Load UserRadarScore if it exists
    from app.models.user_radar_score import UserRadarScore
    radar_score_record = db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).first()
    radar_score = None
    if radar_score_record:
        radar_score = {
            "start_vector": radar_score_record.start_vector,
            "current_vector": radar_score_record.current_vector,
            "prev_stack": radar_score_record.prev_stack,
        }

    return PlacementResultResponse(
        learning_status=user.learning_status,
        total_questions=total_questions,
        total_correct=total_correct,
        overall_percent=overall_percent,
        skill_scores=skill_scores_percent,
        starting_level=starting_level,
        weak_skills=weak_skills,
        role_id=role_id,
        role_name=role_name,
        baseline=baseline,
        answers=answers,
        radar_score=radar_score,
    )


# ─── Phase A: zero-AI roadmap (spec §2.C) ────────────────────────────────────


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
) -> None:
    """Select the user's 8-topic roadmap (spec §2.C) and persist it
    (idempotent delete+insert). When `raise_on_missing` is False the function
    returns silently if the prerequisites are missing (placement answers not
    saved yet, or the role has no course outline) — the placement-test trigger
    uses that mode; a later recompute fills the roadmap.
    """
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
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
    db.commit()
    notification_stream_broker.publish_nowait(
        user_id,
        {
            "type": "roadmap_updated",
            "reason": "roadmap_changed",
        },
    )


def build_and_save_roadmap(db: Session, user_id: int) -> None:
    """Silent roadmap build used by the placement-test completion trigger."""
    _build_and_save_roadmap(db, user_id)


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
        if lesson.is_generated:
            seen_topic_ids.add(lesson.topic_id)
            continue
        first_lesson_ids.append(lesson.id)
        seen_topic_ids.add(lesson.topic_id)

    return first_lesson_ids


def get_user_roadmap(db: Session, user_id: int) -> RoadmapResponse:
    """Fetch the user's roadmap with lessons inline. Auto-computes when empty."""
    from app.models.user import User

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

    roadmap_topics: list[RoadmapTopicResponse] = []
    total_estimated_minutes = 0
    for topic in topics:
        topic_lessons = lessons_by_topic.get(topic.id, [])
        unlock_map = _compute_topic_unlock_map(
            topic_lessons,
            completed_lesson_ids_by_topic.get(topic.id, set()),
        )
        topic_minutes = sum((lesson.estimated_minutes or 0) for lesson in topic_lessons)
        total_estimated_minutes += topic_minutes
        roadmap_topics.append(
            RoadmapTopicResponse(
                id=topic.id,
                name=topic.name,
                primary_skill=topic.primary_skill,
                seed_tier=topic.seed_tier,
                sort_order=order[topic.id] + 1,
                total_estimated_minutes=topic_minutes,
                lessons=[
                    RoadmapLessonResponse(
                        id=lesson.id,
                        title=lesson.title,
                        primary_skill=lesson.primary_skill,
                        difficulty_tier=lesson.difficulty_tier,
                        estimated_minutes=lesson.estimated_minutes,
                        is_generated=bool(lesson.is_generated),
                        is_unlocked=unlock_map.get(lesson.id, False),
                        theory_content=(
                            lesson.theory_content
                            if unlock_map.get(lesson.id, False)
                            else None
                        ),
                        quiz_content=(
                            lesson.quiz_content
                            if unlock_map.get(lesson.id, False)
                            else None
                        ),
                    )
                    for lesson in topic_lessons
                ],
            )
        )

    return RoadmapResponse(
        track=track,
        topics=roadmap_topics,
        assigned_lessons=assigned_lessons(topics, lessons, track),
        total_estimated_minutes=total_estimated_minutes,
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
    from app.models.user import User
    from app.models.user_radar_score import UserRadarScore

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
        )
        # Dev-mode enrollment (docs/07 deviation #23): a skills-override roadmap
        # is a real live roadmap in a real role, so persist the enrollment so the
        # user counts as an active learner and is not treated as a "new" learner
        # on a deactivated track.
        if user is not None:
            user.job_role_id = role_id
            user.learning_status = LEARNING_ENROLLED
            db.commit()

        # Initialize radar from dev-mode difficulty breakdown (v3 scoring).
        # start_vector = weighted_accuracy% × 0.85 per skill.
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
