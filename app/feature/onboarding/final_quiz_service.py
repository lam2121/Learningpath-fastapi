"""Final Course Quiz Service (Graduation Gate, spec §4.6 & §5.3).

Assembles a 50-question graduation assessment from completed lessons in the
user's roadmap across all 8 topics at zero AI cost. Gated by:
- Unlock Gate: All topic quizzes in roadmap must be passed.
- Pass Gate: >= 80% overall score AND >= 60% in each of the 4 skill sections
  (D_doc, C_comm, T_trouble, G_custom).
Tracks attempts, scores, and active sessions in the MySQL `user_course` table.
"""
from __future__ import annotations

from datetime import datetime
import random
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.feature.onboarding.lesson_quiz_service import normalize_index_answer
from app.feature.onboarding.roadmap_schema import (
    FinalQuizAnswerSubmission,
    FinalQuizQuestionResponse,
    FinalQuizQuestionResultResponse,
    FinalQuizSkillScoreResponse,
    FinalQuizStateResponse,
    FinalQuizSubmitResponse,
    WeakestLessonSummaryResponse,
)
from app.feature.onboarding.topic_quiz_service import (
    _build_question_data_row,
    _extract_lesson_quiz_questions,
    _is_valid_active_question,
    _shuffle_options_for_type,
)
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user import User
from app.models.user_course import UserCourse
from app.models.user_lesson import UserLesson
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz
from app.feature.onboarding.radar_service import update_user_radar_score

FINAL_QUIZ_SIZE = 50
FINAL_QUIZ_PASS_THRESHOLD_PERCENT = 80.0
FINAL_QUIZ_SKILL_SECTION_THRESHOLD_PERCENT = 60.0
FINAL_QUIZ_MIN_PER_SKILL = 8

SKILLS = ("D_doc", "C_comm", "T_trouble", "G_custom")
SKILL_LABELS: dict[str, str] = {
    "D_doc": "Documentation",
    "C_comm": "Communication",
    "T_trouble": "Troubleshooting",
    "G_custom": "Business",
}


def check_final_quiz_unlocked(db: Session, user_id: int) -> tuple[bool, int, int]:
    """Check if user has completed and passed all topic quizzes in their roadmap.

    Returns:
        (is_unlocked, completed_topics, total_topics)
    """
    roadmap_entries = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .order_by(UserRoadmap.sort_order)
        .all()
    )
    if not roadmap_entries:
        return False, 0, 0

    total_topics = len(roadmap_entries)
    topic_ids = [entry.topic_id for entry in roadmap_entries]

    passed_topic_quizzes = (
        db.query(UserTopicQuiz)
        .filter(
            UserTopicQuiz.user_id == user_id,
            UserTopicQuiz.topic_id.in_(topic_ids),
            UserTopicQuiz.status == "passed",
        )
        .all()
    )
    completed_topics = len(passed_topic_quizzes)
    is_unlocked = completed_topics == total_topics and total_topics > 0
    return is_unlocked, completed_topics, total_topics


def get_or_create_user_course(
    db: Session,
    user_id: int,
    create_if_missing: bool = True,
) -> UserCourse | None:
    """Retrieve or initialize the UserCourse record for the user's role course."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    course = None
    if user.job_role_id:
        course = db.query(Course).filter(Course.job_role_id == user.job_role_id).first()
    if not course:
        course = db.query(Course).first()
    if not course:
        return None

    user_course = (
        db.query(UserCourse)
        .filter(UserCourse.user_id == user_id, UserCourse.course_id == course.id)
        .first()
    )
    if user_course is None and create_if_missing:
        user_course = UserCourse(
            user_id=user_id,
            course_id=course.id,
            status="locked",
            attempt_count=0,
            failed_attempts=0,
            best_score_percent=0.0,
            last_score_percent=0.0,
            progress=0.0,
            unlocked_at=None,
            user_answers={},
        )
        db.add(user_course)
        db.flush()

    return user_course


def get_final_quiz_state(db: Session, user_id: int) -> FinalQuizStateResponse:
    """Get the current unlock, attempt, and score state of the Final Course Quiz."""
    is_unlocked, completed_topics, total_topics = check_final_quiz_unlocked(db, user_id)
    user_course = get_or_create_user_course(db, user_id, create_if_missing=True)

    if not is_unlocked:
        effective_status: str = "locked"
    elif user_course and user_course.status == "passed":
        effective_status = "passed"
    elif user_course and user_course.status == "failed":
        effective_status = "failed"
    else:
        effective_status = "ready"

    attempt_count = user_course.attempt_count if user_course else 0
    failed_attempts = user_course.failed_attempts if user_course else 0
    best_score = user_course.best_score_percent if user_course else None
    last_score = user_course.last_score_percent if user_course else None
    passed = effective_status == "passed"
    skill_scores = user_course.skill_scores if user_course else None

    # Reconstruct skill breakdown from recorded skill scores if available
    skill_breakdown: list[FinalQuizSkillScoreResponse] = []
    if isinstance(skill_scores, dict):
        for sk in SKILLS:
            score_val = float(skill_scores.get(sk, 0.0))
            skill_breakdown.append(
                FinalQuizSkillScoreResponse(
                    skill=sk,
                    label=SKILL_LABELS.get(sk, sk),
                    correct_count=0,
                    total_count=0,
                    accuracy_percent=score_val,
                    passed=score_val >= FINAL_QUIZ_SKILL_SECTION_THRESHOLD_PERCENT,
                )
            )

    # Reconstruct weakest lessons summaries if available
    weakest_summaries: list[WeakestLessonSummaryResponse] = []
    if user_course and isinstance(user_course.weakest_lesson_ids, list) and user_course.weakest_lesson_ids:
        weakest_lessons = (
            db.query(Lesson)
            .filter(Lesson.id.in_(user_course.weakest_lesson_ids))
            .all()
        )
        for l in weakest_lessons:
            weakest_summaries.append(
                WeakestLessonSummaryResponse(
                    lesson_id=l.id,
                    title=l.title,
                    correct_count=0,
                    total_count=0,
                    accuracy_percent=0.0,
                )
            )

    latest_attempt = None
    if user_course and isinstance(user_course.user_answers, dict):
        raw_attempt = user_course.user_answers.get("latest_attempt")
        if isinstance(raw_attempt, dict) and "question_results" in raw_attempt:
            latest_attempt = raw_attempt

    # Fallback for passed/failed final quiz where detailed latest_attempt was not yet recorded:
    if (
        latest_attempt is None
        and user_course
        and user_course.attempt_count > 0
        and user_course.status in ("passed", "failed")
    ):
        total_q = FINAL_QUIZ_SIZE
        score_pct = (
            user_course.last_score_percent
            if user_course.last_score_percent is not None
            else (100.0 if user_course.status == "passed" else 0.0)
        )
        corr_q = int(round(total_q * (score_pct / 100.0)))
        latest_attempt = {
            "passed": user_course.status == "passed",
            "score_percent": score_pct,
            "correct_count": corr_q,
            "total_questions": total_q,
            "status": user_course.status,
            "attempt_count": user_course.attempt_count,
            "failed_attempts": user_course.failed_attempts,
            "skill_scores": skill_scores,
            "skill_breakdown": skill_breakdown,
            "weakest_lessons": weakest_summaries if user_course.status == "failed" else [],
            "question_results": [],
        }

    best_attempt = None
    first_pass = None
    if user_course and isinstance(user_course.user_answers, dict):
        raw_best = user_course.user_answers.get("best_attempt")
        if isinstance(raw_best, dict) and "question_results" in raw_best:
            best_attempt = raw_best

        raw_first = user_course.user_answers.get("first_pass")
        if isinstance(raw_first, dict) and "question_results" in raw_first:
            first_pass = raw_first

    if best_attempt is None:
        best_attempt = latest_attempt
    if first_pass is None and user_course and user_course.status == "passed":
        first_pass = best_attempt

    return FinalQuizStateResponse(
        is_unlocked=is_unlocked,
        status=effective_status,  # type: ignore[arg-type]
        attempt_count=attempt_count,
        failed_attempts=failed_attempts,
        best_score_percent=best_score,
        last_score_percent=last_score,
        passed=passed,
        total_topics=total_topics,
        completed_topics=completed_topics,
        skill_scores=skill_scores,
        skill_breakdown=skill_breakdown,
        weakest_lessons=weakest_summaries,
        latest_attempt=latest_attempt,
        best_attempt=best_attempt,
        first_pass=first_pass,
    )


def _load_user_roadmap_lessons(db: Session, user_id: int) -> list[Lesson]:
    """Retrieve all Lessons with quiz content across all topics in the user's roadmap."""
    roadmap_entries = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .order_by(UserRoadmap.sort_order)
        .all()
    )
    if not roadmap_entries:
        return []

    topic_ids = [entry.topic_id for entry in roadmap_entries]
    lessons = (
        db.query(Lesson)
        .filter(Lesson.topic_id.in_(topic_ids), Lesson.quiz_content.isnot(None))
        .all()
    )
    return lessons


def get_or_create_final_quiz_questions(
    db: Session,
    user_id: int,
    force_new: bool = False,
) -> list[FinalQuizQuestionResponse]:
    """Assemble a 50-question graduation test from completed lessons in the roadmap.

    Guarantees balanced coverage: >= 8 questions per skill across the 4 skills,
    with remaining questions sampled from the pool (§5.3).
    Caches active question session in `user_course.user_answers`.
    """
    is_unlocked, _, _ = check_final_quiz_unlocked(db, user_id)
    if not is_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Final Course Quiz is locked. Complete and pass all Topic Quizzes in your roadmap first.",
        )

    user_course = get_or_create_user_course(db, user_id, create_if_missing=True)
    if not user_course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No course found for user.",
        )

    # Check if existing active question session exists
    active_questions: list[dict[str, Any]] | None = None
    if force_new and isinstance(user_course.user_answers, dict):
        existing_answers = dict(user_course.user_answers)
        existing_answers.pop("active_questions", None)
        existing_answers.pop("latest_attempt", None)
        user_course.user_answers = existing_answers
        flag_modified(user_course, "user_answers")
        db.commit()
    elif isinstance(user_course.user_answers, dict):
        active = user_course.user_answers.get("active_questions")
        if (
            isinstance(active, list)
            and len(active) > 0
            and all(_is_valid_active_question(q) for q in active)
        ):
            active_questions = active

    if active_questions is None:
        lessons = _load_user_roadmap_lessons(db, user_id)
        if not lessons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No assigned lessons found in roadmap to build Final Course Quiz.",
            )

        # Build topic map for topic names
        topic_ids = {l.topic_id for l in lessons if l.topic_id}
        topics = db.query(Topic).filter(Topic.id.in_(topic_ids)).all() if topic_ids else []
        topic_name_map = {t.id: t.name for t in topics}

        # Extract all questions across completed lessons
        raw_pool: list[dict[str, Any]] = []
        for lesson in lessons:
            extracted = _extract_lesson_quiz_questions(lesson)
            for q in extracted:
                q["topic_id"] = lesson.topic_id
                q["topic_name"] = topic_name_map.get(lesson.topic_id, "")
            raw_pool.extend(extracted)

        if not raw_pool:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No quiz questions available across assigned lessons.",
            )

        # Group pool by skill
        pool_by_skill: dict[str, list[dict[str, Any]]] = {sk: [] for sk in SKILLS}
        other_pool: list[dict[str, Any]] = []
        for q in raw_pool:
            sk = q.get("skill")
            if sk in pool_by_skill:
                pool_by_skill[sk].append(q)
            else:
                other_pool.append(q)

        # Ensure >= MIN_PER_SKILL per skill
        selected_questions: list[dict[str, Any]] = []
        used_qids: set[str] = set()

        for sk in SKILLS:
            skill_qs = list(pool_by_skill[sk])
            random.shuffle(skill_qs)
            sample_size = min(FINAL_QUIZ_MIN_PER_SKILL, len(skill_qs))
            picked = skill_qs[:sample_size]
            selected_questions.extend(picked)
            used_qids.update(q["question_id"] for q in picked)

        # Fill remaining slots from unused pool
        remaining_pool = [q for q in raw_pool if q["question_id"] not in used_qids]
        random.shuffle(remaining_pool)
        needed = max(0, FINAL_QUIZ_SIZE - len(selected_questions))
        selected_questions.extend(remaining_pool[:needed])

        # If still short of 50 (e.g. small seed dataset), take what is available
        random.shuffle(selected_questions)

        # Format questions and shuffle option display order
        active_questions = []
        for idx, q in enumerate(selected_questions):
            q_type = q.get("question_type", "fill_blank")
            raw_options = list(q.get("raw_options", []))
            correct_ans = str(q.get("correct_answer", ""))

            shuffled_options, remapped_correct_ans = _shuffle_options_for_type(
                q_type,
                raw_options,
                correct_ans,
            )

            active_questions.append(
                {
                    "question_id": q["question_id"],
                    "question_number": idx + 1,
                    "skill": q.get("skill", "D_doc"),
                    "question_type": q_type,
                    "statement": q["statement"],
                    "options": shuffled_options,
                    "correct_answer": remapped_correct_ans,
                    "explanation": q.get("explanation", ""),
                    "lesson_id": q.get("lesson_id", 0),
                    "lesson_title": q.get("lesson_title", ""),
                    "topic_id": q.get("topic_id"),
                    "topic_name": q.get("topic_name", ""),
                }
            )

        # Save session snapshot in user_course
        existing_answers = user_course.user_answers if isinstance(user_course.user_answers, dict) else {}
        user_course.user_answers = {
            **existing_answers,
            "active_questions": active_questions,
        }
        flag_modified(user_course, "user_answers")
        if user_course.status == "locked":
            user_course.status = "ready"
        if not user_course.unlocked_at:
            user_course.unlocked_at = datetime.utcnow()
        db.commit()
        db.refresh(user_course)

    # Format for client response
    client_questions: list[FinalQuizQuestionResponse] = []
    for q in active_questions:
        client_questions.append(
            FinalQuizQuestionResponse(
                id=q["question_id"],
                question_number=q["question_number"],
                skill=q["skill"],
                question_type=q["question_type"],
                data=_build_question_data_row(q),
                lesson_id=q["lesson_id"],
                lesson_title=q["lesson_title"],
                topic_id=q.get("topic_id"),
                topic_name=q.get("topic_name"),
            )
        )

    return client_questions


def submit_final_quiz(
    db: Session,
    user_id: int,
    submitted_answers: list[FinalQuizAnswerSubmission],
) -> FinalQuizSubmitResponse:
    """Evaluate Final Course Quiz answers against graduation thresholds.

    Graduation criteria (spec §4.6):
    - Overall score >= 80%
    - Each of the 4 skill sections >= 60%
    Updates `user_course` status to 'passed' or 'failed', records attempt metrics,
    and returns detailed results for the review UI.
    """
    is_unlocked, _, _ = check_final_quiz_unlocked(db, user_id)
    if not is_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Final Course Quiz is locked. Complete and pass all Topic Quizzes in your roadmap first.",
        )

    user_course = get_or_create_user_course(db, user_id, create_if_missing=True)
    if not user_course or not isinstance(user_course.user_answers, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active Final Course Quiz session found. Please load questions first.",
        )

    active_questions: list[dict[str, Any]] = user_course.user_answers.get("active_questions", [])
    if not active_questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active Final Course Quiz questions found. Please restart the quiz.",
        )

    submitted_by_id = {
        ans.question_id: ans.answer.strip() for ans in submitted_answers
    }

    correct_count = 0
    question_results: list[FinalQuizQuestionResultResponse] = []
    lesson_stats: dict[int, dict[str, Any]] = {}
    skill_stats: dict[str, dict[str, Any]] = {
        sk: {
            "skill": sk,
            "label": SKILL_LABELS.get(sk, sk),
            "correct_count": 0,
            "total_count": 0,
        }
        for sk in SKILLS
    }

    for q in active_questions:
        lid = q.get("lesson_id", 0)
        if lid and lid not in lesson_stats:
            lesson_stats[lid] = {
                "lesson_id": lid,
                "title": q.get("lesson_title", f"Lesson {lid}"),
                "correct_count": 0,
                "total_count": 0,
                "accuracy_percent": 0.0,
            }

        qid = q["question_id"]
        user_ans = submitted_by_id.get(qid, "").strip()
        correct_ans = str(q.get("correct_answer", "")).strip()
        q_type = q.get("question_type", "fill_blank")
        sk = q.get("skill", "D_doc")

        is_correct = False
        if user_ans:
            if q_type == "multi_select":
                is_correct = normalize_index_answer(user_ans) == normalize_index_answer(correct_ans)
            else:
                is_correct = user_ans.lower() == correct_ans.lower()

        if is_correct:
            correct_count += 1
            if lid in lesson_stats:
                lesson_stats[lid]["correct_count"] += 1
            if sk in skill_stats:
                skill_stats[sk]["correct_count"] += 1

        if lid in lesson_stats:
            lesson_stats[lid]["total_count"] += 1
        if sk in skill_stats:
            skill_stats[sk]["total_count"] += 1

        question_results.append(
            FinalQuizQuestionResultResponse(
                question_id=qid,
                question_type=q_type,
                question_text=q["statement"],
                options=list(q.get("options", [])),
                user_answer=user_ans,
                correct_answer=correct_ans,
                explanation=q.get("explanation", ""),
                is_correct=is_correct,
                lesson_id=lid,
                lesson_title=q.get("lesson_title", ""),
                skill=sk,
            )
        )

    total_questions = len(active_questions)
    score_percent = round((correct_count / total_questions) * 100, 2) if total_questions > 0 else 0.0

    # Calculate skill breakdown
    skill_breakdown: list[FinalQuizSkillScoreResponse] = []
    skill_scores_dict: dict[str, float] = {}
    skills_passed = True

    for sk in SKILLS:
        st = skill_stats[sk]
        acc = (
            round((st["correct_count"] / st["total_count"]) * 100, 2)
            if st["total_count"] > 0
            else 100.0
        )
        sk_passed = acc >= FINAL_QUIZ_SKILL_SECTION_THRESHOLD_PERCENT
        if st["total_count"] > 0 and not sk_passed:
            skills_passed = False

        skill_breakdown.append(
            FinalQuizSkillScoreResponse(
                skill=sk,
                label=st["label"],
                correct_count=st["correct_count"],
                total_count=st["total_count"],
                accuracy_percent=acc,
                passed=sk_passed,
            )
        )
        skill_scores_dict[sk] = acc

    # Overall graduation check
    overall_passed = score_percent >= FINAL_QUIZ_PASS_THRESHOLD_PERCENT
    passed = overall_passed and skills_passed

    # Weakest lessons calculation (< 75% accuracy)
    weakest_lessons: list[WeakestLessonSummaryResponse] = []
    for stat in lesson_stats.values():
        total = stat["total_count"]
        acc = round((stat["correct_count"] / total) * 100, 2) if total > 0 else 0.0
        stat["accuracy_percent"] = acc
        if acc < 75.0:
            weakest_lessons.append(
                WeakestLessonSummaryResponse(
                    lesson_id=stat["lesson_id"],
                    title=stat["title"],
                    correct_count=stat["correct_count"],
                    total_count=total,
                    accuracy_percent=acc,
                )
            )

    weakest_lessons.sort(key=lambda item: item.accuracy_percent)
    weakest_lesson_ids = [l.lesson_id for l in weakest_lessons]

    # Update UserCourse
    user_course.attempt_count += 1
    if not passed:
        user_course.failed_attempts += 1
    user_course.last_score_percent = score_percent
    user_course.best_score_percent = max(user_course.best_score_percent or 0.0, score_percent)
    user_course.progress = user_course.best_score_percent
    user_course.status = "passed" if passed else "failed"
    if passed:
        user_course.completed_at = datetime.utcnow()
    user_course.skill_scores = skill_scores_dict
    user_course.weakest_lesson_ids = weakest_lesson_ids

    response_obj = FinalQuizSubmitResponse(
        passed=passed,
        score_percent=score_percent,
        correct_count=correct_count,
        total_questions=total_questions,
        status="passed" if passed else "failed",
        attempt_count=user_course.attempt_count,
        failed_attempts=user_course.failed_attempts,
        skill_scores=skill_scores_dict,
        skill_breakdown=skill_breakdown,
        weakest_lessons=weakest_lessons,
        question_results=question_results,
    )

    # Determine whether current attempt is a new best attempt
    existing_answers = (
        user_course.user_answers
        if isinstance(user_course.user_answers, dict)
        else {}
    )
    existing_best = existing_answers.get("best_attempt")

    is_new_best = False
    if not existing_best or not isinstance(existing_best, dict):
        is_new_best = True
    else:
        prev_passed = bool(existing_best.get("passed", False))
        prev_score = float(existing_best.get("score_percent", 0.0))
        if passed and not prev_passed:
            is_new_best = True
        elif passed == prev_passed and score_percent >= prev_score:
            is_new_best = True

    new_answers = {
        **existing_answers,
        "latest_attempt": response_obj.model_dump(),
        "active_questions": None,
    }
    if is_new_best:
        new_answers["best_attempt"] = response_obj.model_dump()
    if passed and "first_pass" not in existing_answers:
        new_answers["first_pass"] = response_obj.model_dump()

    user_course.user_answers = new_answers
    flag_modified(user_course, "user_answers")
    db.commit()
    db.refresh(user_course)

    # Recalculate learner radar scores across skills D, C, T, G
    update_user_radar_score(db, user_id)

    return response_obj
