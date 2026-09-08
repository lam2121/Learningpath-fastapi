from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.roadmap import lesson_is_assigned
from app.feature.onboarding.lesson_quiz_scoring import normalize_index_answer
from app.feature.onboarding.lesson_quiz_service import (
    _find_quiz_object,
    _parse_maybe_json,
)
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user_lesson import UserLesson
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz
from app.feature.onboarding.radar_service import update_user_radar_score

TOPIC_QUIZ_PASS_THRESHOLD_PERCENT = 75.0
TOPIC_QUIZ_TOTAL_QUESTIONS = 30

# Number of trailing zero-padding slots appended to each question's `data`
# row, matching the FillBlankQuestionData / MultiSelectQuestionData /
# OrderingQuestionData tuple shape used by the frontend quiz-engine
# components ([stem, options, correct_answer, explanation, 0, 0, 0, 0, 0, 0, 0, 0]).
_DATA_ROW_PADDING = [0, 0, 0, 0, 0, 0, 0, 0]


def check_topic_quiz_unlocked(
    db: Session,
    user_id: int,
    topic_id: int,
) -> tuple[bool, list[Lesson], set[int]]:
    """Verify whether all assigned lessons in the topic are completed for this user."""
    roadmap_entry = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id, UserRoadmap.topic_id == topic_id)
        .first()
    )
    if roadmap_entry is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Topic does not belong to your roadmap",
        )

    track = roadmap_entry.track
    all_topic_lessons = (
        db.query(Lesson)
        .filter(Lesson.topic_id == topic_id)
        .order_by(Lesson.id.asc())
        .all()
    )
    assigned_lessons = [
        l for l in all_topic_lessons if lesson_is_assigned(track, l.difficulty_tier)
    ]

    if not assigned_lessons:
        return False, [], set()

    assigned_lesson_ids = [l.id for l in assigned_lessons]
    completed_rows = (
        db.query(UserLesson.lesson_id)
        .filter(
            UserLesson.user_id == user_id,
            UserLesson.lesson_id.in_(assigned_lesson_ids),
            UserLesson.completed_at.isnot(None),
        )
        .all()
    )
    completed_ids = {int(row[0]) for row in completed_rows}

    is_unlocked = len(completed_ids) == len(assigned_lessons)
    return is_unlocked, assigned_lessons, completed_ids


def _extract_lesson_quiz_questions(lesson: Lesson) -> list[dict[str, Any]]:
    """Extract individual questions from a lesson's quiz_content JSON."""
    parsed = _parse_maybe_json(lesson.quiz_content)
    raw = _find_quiz_object(parsed)
    if not isinstance(raw, dict):
        return []

    extracted: list[dict[str, Any]] = []
    prefix_map = {
        "fill_blank": "fill",
        "multi_select": "multi",
        "ordering": "order",
    }

    for q_type, rows in raw.items():
        if not isinstance(rows, list) or q_type not in prefix_map:
            continue
        prefix = prefix_map[q_type]
        for idx, row in enumerate(rows):
            if not isinstance(row, list) or len(row) < 4:
                continue
            stem = str(row[0])
            options_raw = str(row[1])
            correct_ans = str(row[2])
            explanation = str(row[3])

            raw_options = [opt.strip() for opt in options_raw.split("|") if opt.strip()]
            if len(raw_options) < 2:
                continue

            extracted.append(
                {
                    "question_id": f"topic-q-{lesson.id}-{prefix}-{idx}",
                    "lesson_id": lesson.id,
                    "lesson_title": lesson.title,
                    "question_type": q_type,
                    "skill": lesson.primary_skill,
                    "statement": stem,
                    "raw_options": raw_options,
                    "correct_answer": correct_ans,
                    "explanation": explanation,
                }
            )

    return extracted


def _build_topic_quiz_pool(assigned_lessons: list[Lesson]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for lesson in assigned_lessons:
        pool.extend(_extract_lesson_quiz_questions(lesson))
    return pool


def _shuffle_options_for_type(
    question_type: str,
    options: list[str],
    correct_answer: str,
) -> tuple[list[str], str]:
    """Shuffle option display order, remapping the correct answer where needed.

    - fill_blank: `correct_answer` is the literal answer text, so it is
      unaffected by option order — only the display order is shuffled.
    - multi_select: `correct_answer` is pipe-separated indices into
      `options`, so shuffling requires remapping those indices to their new
      positions.
    - ordering: the option order itself IS the content being assessed, so it
      is intentionally left untouched here — same as the lesson quiz engine,
      which never shuffles ordering rows server-side and instead lets the
      OrderingQuestion component randomize the user-facing arrangement.
    """
    if question_type == "ordering":
        return options, correct_answer

    if question_type == "multi_select":
        correct_indices = {
            int(part) for part in correct_answer.split("|") if part.strip().isdigit()
        }
        order = list(range(len(options)))
        random.shuffle(order)
        shuffled_options = [options[i] for i in order]
        remapped = sorted(
            new_idx for new_idx, original_idx in enumerate(order) if original_idx in correct_indices
        )
        return shuffled_options, "|".join(str(idx) for idx in remapped)

    # fill_blank (default): options are display-only
    shuffled_options = list(options)
    random.shuffle(shuffled_options)
    return shuffled_options, correct_answer


def _build_question_data_row(q: dict[str, Any]) -> list[Any]:
    """Pack a cached active_question dict into the [stem, options, answer,
    explanation, 0×8] row shape the frontend quiz-engine components expect.
    """
    options_str = "|".join(q["options"])
    return [q["statement"], options_str, q["correct_answer"], q["explanation"], *_DATA_ROW_PADDING]


def _is_valid_active_question(q: Any) -> bool:
    """True if a cached active_question dict matches the CURRENT schema.

    Guards against stale `UserTopicQuiz.user_answers["active_questions"]`
    rows written before the fill_blank/multi_select/ordering migration,
    where `options` was a list of {"id", "text"} dicts and `difficulty`
    existed instead of `question_type`. Old-shaped cache entries are
    discarded so a fresh pool is drawn instead of crashing.
    """
    if not isinstance(q, dict):
        return False

    required_keys = {
        "question_id",
        "question_number",
        "skill",
        "question_type",
        "statement",
        "options",
        "correct_answer",
        "explanation",
        "lesson_id",
        "lesson_title",
    }
    if not required_keys.issubset(q.keys()):
        return False

    if q.get("question_type") not in ("fill_blank", "multi_select", "ordering"):
        return False

    options = q.get("options")
    if not isinstance(options, list) or not all(isinstance(opt, str) for opt in options):
        return False

    return True


def get_or_create_topic_quiz_questions(
    db: Session,
    user_id: int,
    topic_id: int,
    force_new: bool = False,
) -> list[dict[str, Any]]:
    """
    Randomly pull 30 questions from completed lesson quizzes in the topic (spec §4.2).
    Zero AI cost. Retains session state so refresh returns consistent questions.
    """
    is_unlocked, assigned_lessons, _ = check_topic_quiz_unlocked(db, user_id, topic_id)
    if not is_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Topic Quiz is locked. Complete all assigned lessons in this topic first.",
        )

    topic_quiz_record = (
        db.query(UserTopicQuiz)
        .filter(UserTopicQuiz.user_id == user_id, UserTopicQuiz.topic_id == topic_id)
        .first()
    )
    if topic_quiz_record is None:
        topic_quiz_record = UserTopicQuiz(
            user_id=user_id,
            topic_id=topic_id,
            status="unlocked",
            attempt_count=0,
            failed_attempts=0,
            best_score_percent=0.0,
            last_score_percent=0.0,
        )
        db.add(topic_quiz_record)
        db.flush()

    active_questions: list[dict[str, Any]] | None = None
    if force_new and isinstance(topic_quiz_record.user_answers, dict):
        current_answers = dict(topic_quiz_record.user_answers)
        current_answers.pop("active_questions", None)
        current_answers.pop("latest_attempt", None)
        topic_quiz_record.user_answers = current_answers
        flag_modified(topic_quiz_record, "user_answers")
        db.commit()
    elif isinstance(topic_quiz_record.user_answers, dict):
        active = topic_quiz_record.user_answers.get("active_questions")
        if (
            isinstance(active, list)
            and len(active) > 0
            and all(_is_valid_active_question(q) for q in active)
        ):
            active_questions = active
        elif isinstance(active, list) and len(active) > 0:
            # Stale pre-migration cache (old statement/options/difficulty
            # shape) — discard it so we fall through and draw a fresh pool.
            current_answers = dict(topic_quiz_record.user_answers)
            current_answers.pop("active_questions", None)
            topic_quiz_record.user_answers = current_answers
            flag_modified(topic_quiz_record, "user_answers")
            db.commit()

    if active_questions is None:
        pool = _build_topic_quiz_pool(assigned_lessons)
        if not pool:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No quiz questions available from completed lessons in this topic.",
            )

        sample_size = min(TOPIC_QUIZ_TOTAL_QUESTIONS, len(pool))
        selected_raw = random.sample(pool, sample_size)

        active_questions = []
        for i, q in enumerate(selected_raw):
            shuffled_options, remapped_answer = _shuffle_options_for_type(
                q["question_type"], q["raw_options"], q["correct_answer"]
            )

            active_questions.append(
                {
                    "question_id": q["question_id"],
                    "question_number": i + 1,
                    "skill": q["skill"],
                    "question_type": q["question_type"],
                    "statement": q["statement"],
                    "options": shuffled_options,
                    "correct_answer": remapped_answer,
                    "explanation": q["explanation"],
                    "lesson_id": q["lesson_id"],
                    "lesson_title": q["lesson_title"],
                }
            )

        current_answers = dict(topic_quiz_record.user_answers or {})
        current_answers["active_questions"] = active_questions
        topic_quiz_record.user_answers = current_answers
        flag_modified(topic_quiz_record, "user_answers")
        db.commit()

    # Client-facing payload — same fill_blank/multi_select/ordering `data`
    # row shape the lesson quiz engine sends. Note: like lesson quiz_content,
    # this embeds the correct answer in data[2] rather than stripping it.
    client_questions = []
    for q in active_questions:
        client_questions.append(
            {
                "id": q["question_id"],
                "question_number": q["question_number"],
                "skill": q["skill"],
                "question_type": q["question_type"],
                "data": _build_question_data_row(q),
                "lesson_id": q["lesson_id"],
                "lesson_title": q["lesson_title"],
            }
        )

    return client_questions


def submit_topic_quiz(
    db: Session,
    user_id: int,
    topic_id: int,
    submitted_answers: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate Topic Quiz raw score (>= 75% passes) (spec §4.2).
    Flags every lesson that fell below the 75% pass mark for review (not
    capped to a fixed count).
    Anti-farming: Does NOT update UserRadarScore (Flow 1 gatekeeping only).
    """
    is_unlocked, assigned_lessons, _ = check_topic_quiz_unlocked(db, user_id, topic_id)
    if not is_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Topic Quiz is locked. Complete all assigned lessons in this topic first.",
        )

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    topic_name = topic.name if topic else f"Topic {topic_id}"

    topic_quiz_record = (
        db.query(UserTopicQuiz)
        .filter(UserTopicQuiz.user_id == user_id, UserTopicQuiz.topic_id == topic_id)
        .first()
    )
    if topic_quiz_record is None:
        topic_quiz_record = UserTopicQuiz(
            user_id=user_id,
            topic_id=topic_id,
            status="unlocked",
        )
        db.add(topic_quiz_record)
        db.flush()

    active_questions: list[dict[str, Any]] = []
    if isinstance(topic_quiz_record.user_answers, dict):
        active = topic_quiz_record.user_answers.get("active_questions")
        if isinstance(active, list) and len(active) > 0:
            active_questions = active

    if not active_questions:
        # Fallback if no cached questions exist: generate pool and match
        get_or_create_topic_quiz_questions(db, user_id, topic_id)
        db.refresh(topic_quiz_record)
        active_questions = topic_quiz_record.user_answers.get("active_questions", [])

    submitted_by_id = {
        str(ans.get("question_id", "")): str(ans.get("answer", "") or "")
        for ans in submitted_answers
    }

    correct_count = 0
    question_results: list[dict[str, Any]] = []
    lesson_stats: dict[int, dict[str, Any]] = {}

    for lesson in assigned_lessons:
        lesson_stats[lesson.id] = {
            "lesson_id": lesson.id,
            "title": lesson.title,
            "correct_count": 0,
            "total_count": 0,
            "accuracy_percent": 0.0,
        }

    for q in active_questions:
        qid = q["question_id"]
        user_ans = submitted_by_id.get(qid, "").strip()
        correct_ans = str(q.get("correct_answer", "")).strip()
        q_type = q.get("question_type", "fill_blank")

        is_correct = False
        if user_ans:
            if q_type == "multi_select":
                is_correct = normalize_index_answer(user_ans) == normalize_index_answer(correct_ans)
            else:
                # fill_blank: exact text match. ordering: exact sequence
                # match — order matters, so it must NOT be normalized/sorted
                # the way multi_select indices are.
                is_correct = user_ans.lower() == correct_ans.lower()

        if is_correct:
            correct_count += 1

        lid = q.get("lesson_id")
        if lid in lesson_stats:
            lesson_stats[lid]["total_count"] += 1
            if is_correct:
                lesson_stats[lid]["correct_count"] += 1

        question_results.append(
            {
                "question_id": qid,
                "question_type": q_type,
                "question_text": q["statement"],
                "options": q["options"],
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "explanation": q.get("explanation", ""),
                "is_correct": is_correct,
                "lesson_id": lid,
                "lesson_title": q.get("lesson_title", ""),
                "skill": q.get("skill"),
            }
        )

    total_questions = len(active_questions)
    raw_score_percent = round((correct_count / total_questions * 100) if total_questions > 0 else 0.0, 2)
    passed = raw_score_percent >= TOPIC_QUIZ_PASS_THRESHOLD_PERCENT

    # Compute per-skill accuracy breakdown
    skill_counts: dict[str, dict[str, int]] = {
        sk: {"correct": 0, "total": 0}
        for sk in ("D_doc", "C_comm", "T_trouble", "G_custom")
    }
    for qr in question_results:
        q_sk = qr.get("skill")
        if q_sk in skill_counts:
            skill_counts[q_sk]["total"] += 1
            if qr.get("is_correct"):
                skill_counts[q_sk]["correct"] += 1

    skill_scores: dict[str, float] = {}
    for sk, cnt in skill_counts.items():
        if cnt["total"] > 0:
            skill_scores[sk] = round((cnt["correct"] / cnt["total"]) * 100.0, 2)

    # Compute per-lesson accuracy
    for stat in lesson_stats.values():
        if stat["total_count"] > 0:
            stat["accuracy_percent"] = round(
                (stat["correct_count"] / stat["total_count"]) * 100.0, 2
            )
        else:
            stat["accuracy_percent"] = 100.0

    # Flag every lesson that fell below the topic pass mark (75%) for
    # review — not just the top 2 weakest. A lesson with zero questions
    # drawn into this attempt defaults to 100% above and is never flagged.
    sorted_lessons = sorted(
        lesson_stats.values(),
        key=lambda s: (s["accuracy_percent"], s["total_count"]),
    )
    weakest_lessons = [
        s
        for s in sorted_lessons
        if s["total_count"] > 0 and s["accuracy_percent"] < TOPIC_QUIZ_PASS_THRESHOLD_PERCENT
    ]
    weakest_lesson_ids = [l["lesson_id"] for l in weakest_lessons] if not passed else []

    # Update UserTopicQuiz
    topic_quiz_record.attempt_count += 1
    topic_quiz_record.last_score_percent = raw_score_percent
    topic_quiz_record.best_score_percent = max(
        topic_quiz_record.best_score_percent, raw_score_percent
    )

    if passed:
        topic_quiz_record.status = "passed"
        topic_quiz_record.completed_at = datetime.now(UTC).replace(tzinfo=None)
        topic_quiz_record.weakest_lesson_ids = []
    else:
        topic_quiz_record.failed_attempts += 1
        topic_quiz_record.status = "failed"
        topic_quiz_record.weakest_lesson_ids = weakest_lesson_ids

    result_dict = {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "passed": passed,
        "score_percent": raw_score_percent,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "status": topic_quiz_record.status,
        "attempt_count": topic_quiz_record.attempt_count,
        "failed_attempts": topic_quiz_record.failed_attempts,
        "weakest_lessons": weakest_lessons if not passed else [],
        "question_results": question_results,
        "skill_scores": skill_scores,
    }

    # Determine whether current attempt is a new best attempt
    existing_answers = (
        topic_quiz_record.user_answers
        if isinstance(topic_quiz_record.user_answers, dict)
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
        elif passed == prev_passed and raw_score_percent >= prev_score:
            is_new_best = True

    new_answers = {
        **existing_answers,
        "latest_attempt": result_dict,
        "active_questions": None,
    }
    if is_new_best:
        new_answers["best_attempt"] = result_dict
    if passed and "first_pass" not in existing_answers:
        new_answers["first_pass"] = result_dict

    topic_quiz_record.user_answers = new_answers
    flag_modified(topic_quiz_record, "user_answers")

    db.commit()
    db.refresh(topic_quiz_record)

    # Recalculate learner radar scores across skills D, C, T, G
    update_user_radar_score(db, user_id)

    return result_dict


def get_topic_quiz_state(
    db: Session,
    user_id: int,
    topic_id: int,
) -> dict[str, Any]:
    """Return the current topic quiz state for roadmap rendering."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    topic_name = topic.name if topic else f"Topic {topic_id}"

    is_unlocked, assigned_lessons, completed_ids = check_topic_quiz_unlocked(
        db, user_id, topic_id
    )

    topic_quiz_record = (
        db.query(UserTopicQuiz)
        .filter(UserTopicQuiz.user_id == user_id, UserTopicQuiz.topic_id == topic_id)
        .first()
    )

    current_status = "locked"
    attempt_count = 0
    failed_attempts = 0
    best_score: float | None = None
    last_score: float | None = None
    weakest_lessons: list[dict[str, Any]] = []

    if topic_quiz_record is not None:
        attempt_count = topic_quiz_record.attempt_count
        failed_attempts = topic_quiz_record.failed_attempts
        best_score = topic_quiz_record.best_score_percent if attempt_count > 0 else None
        last_score = topic_quiz_record.last_score_percent if attempt_count > 0 else None

        if topic_quiz_record.status == "passed":
            current_status = "passed"
        elif is_unlocked:
            current_status = topic_quiz_record.status if topic_quiz_record.status in ("ready", "failed") else "ready"
        else:
            current_status = "locked"

        # Populate weakest lessons details if failed
        if current_status == "failed" and topic_quiz_record.weakest_lesson_ids:
            weakest_lessons_map = {l.id: l for l in assigned_lessons}
            for lid in topic_quiz_record.weakest_lesson_ids:
                if lid in weakest_lessons_map:
                    l = weakest_lessons_map[lid]
                    weakest_lessons.append(
                        {
                            "lesson_id": l.id,
                            "title": l.title,
                            "correct_count": 0,
                            "total_count": 0,
                            "accuracy_percent": 0.0,
                        }
                    )
    else:
        current_status = "ready" if is_unlocked else "locked"

    latest_attempt = None
    best_attempt = None
    first_pass = None
    if topic_quiz_record and isinstance(topic_quiz_record.user_answers, dict):
        raw_attempt = topic_quiz_record.user_answers.get("latest_attempt")
        if isinstance(raw_attempt, dict) and "question_results" in raw_attempt:
            latest_attempt = raw_attempt

        raw_best = topic_quiz_record.user_answers.get("best_attempt")
        if isinstance(raw_best, dict) and "question_results" in raw_best:
            best_attempt = raw_best

        raw_first = topic_quiz_record.user_answers.get("first_pass")
        if isinstance(raw_first, dict) and "question_results" in raw_first:
            first_pass = raw_first

    # Fallback for passed/failed topics where latest_attempt was not stored previously:
    # Allows the user to refresh the result page without losing their result view
    if (
        latest_attempt is None
        and topic_quiz_record
        and topic_quiz_record.attempt_count > 0
        and topic_quiz_record.status in ("passed", "failed")
    ):
        total_q = TOPIC_QUIZ_TOTAL_QUESTIONS
        score_pct = (
            topic_quiz_record.last_score_percent
            if topic_quiz_record.last_score_percent is not None
            else (100.0 if topic_quiz_record.status == "passed" else 0.0)
        )
        corr_q = int(round(total_q * (score_pct / 100.0)))
        latest_attempt = {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "passed": topic_quiz_record.status == "passed",
            "score_percent": score_pct,
            "correct_count": corr_q,
            "total_questions": total_q,
            "status": topic_quiz_record.status,
            "attempt_count": topic_quiz_record.attempt_count,
            "failed_attempts": topic_quiz_record.failed_attempts,
            "weakest_lessons": weakest_lessons if topic_quiz_record.status == "failed" else [],
            "question_results": [],
        }

    if best_attempt is None:
        best_attempt = latest_attempt
    if first_pass is None and topic_quiz_record and topic_quiz_record.status == "passed":
        first_pass = best_attempt

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "is_unlocked": is_unlocked,
        "status": current_status,
        "attempt_count": attempt_count,
        "failed_attempts": failed_attempts,
        "best_score_percent": best_score,
        "last_score_percent": last_score,
        "weakest_lessons": weakest_lessons,
        "total_assigned_lessons": len(assigned_lessons),
        "completed_assigned_lessons": len(completed_ids),
        "latest_attempt": latest_attempt,
        "best_attempt": best_attempt,
        "first_pass": first_pass,
    }