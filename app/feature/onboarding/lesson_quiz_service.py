from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.feature.onboarding.lesson_quiz_scoring import (
    LESSON_PASS_THRESHOLD_PERCENT,
    compute_lesson_score_percent,
    compute_radar_score_for_skill,
    normalize_index_answer,
)
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user_lesson import UserLesson
from app.models.user_radar_score import UserRadarScore
from app.core.ai.gemini import GeminiClientPool
from app.core.ai.prompts import (
    PROMPT_D1_TEMPLATE,
    PROMPT_D2_TEMPLATE,
    PROMPT_D3_TEMPLATE,
)

QUESTION_TYPE_KEYS = {
    "fill_blank": "fill",
    "multi_select": "multi",
    "ordering": "order",
}
SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


def get_lesson_quiz_state(db: Session, user_id: int, lesson: Lesson) -> dict[str, Any]:
    user_lesson = _get_user_lesson(db, user_id, lesson.id)
    saved_state = _coerce_json_object(user_lesson.user_answers if user_lesson else {})
    radar = db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).first()
    best_score_percent = _extract_best_score(saved_state, user_lesson.progress if user_lesson else 0.0)

    return {
        "lesson_id": lesson.id,
        "skill": lesson.primary_skill,
        "status": user_lesson.status if user_lesson else "not_started",
        "lesson_passed": bool(user_lesson and user_lesson.completed_at is not None),
        "best_score_percent": best_score_percent,
        "attempt_count": user_lesson.attempt_count if user_lesson else 0,
        "failed_attempts": user_lesson.failed_attempts if user_lesson else 0,
        "completed_at": user_lesson.completed_at if user_lesson else None,
        "current_skill_score": _extract_current_skill_score(radar, lesson.primary_skill),
        "first_pass_score_percent": _extract_first_pass_score(saved_state),
    }


def get_lesson_quiz_result_detail(
    db: Session,
    user_id: int,
    lesson: Lesson,
) -> dict[str, Any]:
    user_lesson = _get_user_lesson(db, user_id, lesson.id)
    saved_state = _coerce_json_object(user_lesson.user_answers if user_lesson else {})
    topic = db.query(Topic).filter(Topic.id == lesson.topic_id).first()
    saved_attempt = _extract_saved_attempt(saved_state)
    (
        correct_no_hint_count,
        total_no_hint_questions,
        correct_with_hint_count,
        total_with_hint_questions,
        total_questions,
    ) = _compute_hint_breakdown(saved_attempt)
    best_score_percent = _extract_best_score(saved_state, user_lesson.progress if user_lesson else 0.0)
    recorded_at = (
        user_lesson.completed_at if user_lesson else None
    ) or _parse_iso_datetime(saved_attempt.get("submitted_at"))
    question_lookup = _build_question_lookup_for_result_detail(lesson.quiz_content)

    return {
        "lesson_id": lesson.id,
        "lesson_title": lesson.title,
        "topic_name": topic.name if topic else None,
        "skill": lesson.primary_skill,
        "difficulty_tier": lesson.difficulty_tier,
        "status": _derive_result_status(user_lesson, saved_attempt),
        "best_score_percent": best_score_percent if best_score_percent > 0 else None,
        "attempt_count": user_lesson.attempt_count if user_lesson else 0,
        "failed_attempts": user_lesson.failed_attempts if user_lesson else 0,
        "correct_no_hint_count": correct_no_hint_count,
        "total_no_hint_questions": total_no_hint_questions,
        "correct_with_hint_count": correct_with_hint_count,
        "total_with_hint_questions": total_with_hint_questions,
        "total_questions": total_questions,
        "recorded_at": recorded_at,
        "question_order": _extract_question_order(saved_attempt),
        "answers": _extract_answers(saved_attempt),
        "question_results": _enrich_question_results(
            _extract_question_results(saved_attempt),
            question_lookup,
        ),
    }


def submit_lesson_quiz(
    db: Session,
    user_id: int,
    lesson: Lesson,
    *,
    question_order: list[str],
    submitted_answers: list[dict[str, Any]],
) -> dict[str, Any]:
    quiz_content = _normalize_quiz_content(lesson.quiz_content)
    questions = _build_question_bank(quiz_content)
    submitted_by_id = _index_submitted_answers(submitted_answers)

    correct_no_hint_count = 0
    correct_with_hint_count = 0
    question_results: list[dict[str, Any]] = []
    normalized_answers: list[dict[str, Any]] = []

    for question in questions:
        submitted = submitted_by_id.get(question["question_id"], {})
        answer = str(submitted.get("answer", "") or "")
        used_hint = bool(submitted.get("used_hint", False))
        is_correct = _is_answer_correct(question, answer)

        if is_correct:
            if used_hint:
                correct_with_hint_count += 1
            else:
                correct_no_hint_count += 1

        question_results.append(
            {
                "question_id": question["question_id"],
                "question_type": question["question_type"],
                "user_answer": answer,
                "correct_answer": question["correct_answer"],
                "explanation": question["explanation"],
                "is_correct": is_correct,
                "used_hint": used_hint,
            }
        )
        normalized_answers.append(
            {
                "question_id": question["question_id"],
                "question_type": question["question_type"],
                "answer": answer,
                "used_hint": used_hint,
            }
        )

    total_questions = len(questions)
    weighted_score_percent = round(
        compute_lesson_score_percent(
            correct_no_hint_count=correct_no_hint_count,
            correct_with_hint_count=correct_with_hint_count,
            total_questions=total_questions,
        ),
        2,
    )
    current_attempt_passed = weighted_score_percent >= LESSON_PASS_THRESHOLD_PERCENT

    user_lesson = _get_user_lesson(db, user_id, lesson.id)
    if user_lesson is None:
        user_lesson = UserLesson(
            user_id=user_id,
            lesson_id=lesson.id,
            attempt_count=0,
            failed_attempts=0,
            user_answers={},
            status="in_progress",
        )
        db.add(user_lesson)

    saved_state = _coerce_json_object(user_lesson.user_answers)
    attempt_count = user_lesson.attempt_count + 1
    failed_attempts = user_lesson.failed_attempts
    if not current_attempt_passed:
        failed_attempts += 1

    best_score_percent = _extract_best_score(saved_state, user_lesson.progress)
    current_attempt_is_new_best = (
        current_attempt_passed and (not saved_state or weighted_score_percent >= best_score_percent)
    )

    current_attempt_snapshot = {
        "question_order": question_order,
        "answers": normalized_answers,
        "question_results": question_results,
        "submitted_at": datetime.utcnow().isoformat(),
        "weighted_score_percent": weighted_score_percent,
        "correct_no_hint_count": correct_no_hint_count,
        "correct_with_hint_count": correct_with_hint_count,
        "total_questions": total_questions,
        "passed": current_attempt_passed,
    }

    if current_attempt_is_new_best:
        saved_state = current_attempt_snapshot

    user_lesson.attempt_count = attempt_count
    user_lesson.failed_attempts = failed_attempts
    user_lesson.progress = _extract_best_score(saved_state, user_lesson.progress)

    first_pass_radar_applied = False
    if current_attempt_passed and user_lesson.completed_at is None:
        user_lesson.completed_at = datetime.utcnow()
        user_lesson.status = "completed"
        first_pass_radar_applied = _apply_first_pass_radar_update(
            db,
            user_id=user_id,
            skill=lesson.primary_skill,
            lesson_performance=weighted_score_percent,
        )
    elif user_lesson.completed_at is None:
        user_lesson.status = "in_progress"

    if user_lesson.unlocked_at is None:
        user_lesson.unlocked_at = datetime.utcnow()

    user_lesson.user_answers = saved_state
    db.commit()
    db.refresh(user_lesson)

    radar = db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).first()
    return {
        "lesson_id": lesson.id,
        "skill": lesson.primary_skill,
        "status": user_lesson.status,
        "lesson_passed": user_lesson.completed_at is not None,
        "best_score_percent": _extract_best_score(saved_state, user_lesson.progress),
        "attempt_count": attempt_count,
        "failed_attempts": failed_attempts,
        "completed_at": user_lesson.completed_at,
        "current_skill_score": _extract_current_skill_score(radar, lesson.primary_skill),
        "first_pass_score_percent": _extract_first_pass_score(saved_state),
        "current_attempt_passed": current_attempt_passed,
        "weighted_score_percent": weighted_score_percent,
        "correct_no_hint_count": correct_no_hint_count,
        "correct_with_hint_count": correct_with_hint_count,
        "total_questions": total_questions,
        "first_pass_radar_applied": first_pass_radar_applied,
        "current_attempt_is_new_best": current_attempt_is_new_best,
        "question_results": question_results,
    }


def _normalize_quiz_content(value: Any) -> dict[str, list[list[str]]]:
    parsed = _parse_maybe_json(value)
    raw = _find_quiz_object(parsed)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson quiz content is missing or malformed",
        )

    quiz: dict[str, list[list[str]]] = {}
    for key in ("fill_blank", "multi_select", "ordering"):
        rows = raw.get(key)
        if not isinstance(rows, list):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lesson quiz content is missing '{key}' rows",
            )
        quiz[key] = []
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) < 4
                or not all(isinstance(item, str) for item in row[:4])
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Lesson quiz content contains an invalid '{key}' row",
                )
            quiz[key].append([row[0], row[1], row[2], row[3]])
    return quiz


def _build_question_bank(quiz: dict[str, list[list[str]]]) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    for question_type in ("fill_blank", "multi_select", "ordering"):
        prefix = QUESTION_TYPE_KEYS[question_type]
        for index, row in enumerate(quiz[question_type]):
            questions.append(
                {
                    "question_id": f"{prefix}-{index}",
                    "question_type": question_type,
                    "stem": row[0],
                    "options": row[1],
                    "correct_answer": row[2],
                    "explanation": row[3],
                }
            )
    return questions


def _index_submitted_answers(submitted_answers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for answer in submitted_answers:
        question_id = str(answer.get("question_id", "") or "")
        question_type = str(answer.get("question_type", "") or "")
        if not question_id:
            continue
        indexed[question_id] = {
            "question_id": question_id,
            "question_type": question_type,
            "answer": str(answer.get("answer", "") or ""),
            "used_hint": bool(answer.get("used_hint", False)),
        }
    return indexed


def _is_answer_correct(question: dict[str, str], answer: str) -> bool:
    if not answer.strip():
        return False

    if question["question_type"] == "multi_select":
        return normalize_index_answer(answer) == normalize_index_answer(
            question["correct_answer"]
        )

    return answer == question["correct_answer"]


def _apply_first_pass_radar_update(
    db: Session,
    *,
    user_id: int,
    skill: str,
    lesson_performance: float,
) -> bool:
    radar = db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).first()
    if radar is None:
        return False

    start_vector = _normalize_radar_vector(radar.start_vector)
    current_vector = _normalize_radar_vector(radar.current_vector or radar.start_vector)
    prev_stack = _normalize_prev_stack(radar.prev_stack)

    performances = list(prev_stack.get(skill, []))
    performances.append(float(lesson_performance))
    prev_stack[skill] = performances
    current_vector[skill] = round(
        compute_radar_score_for_skill(start_vector.get(skill, 0.0), performances), 2
    )

    radar.current_vector = current_vector
    radar.prev_stack = prev_stack
    return True


def _extract_current_skill_score(radar: UserRadarScore | None, skill: str) -> float | None:
    if radar is None:
        return None
    current_vector = _normalize_radar_vector(radar.current_vector or radar.start_vector)
    return round(float(current_vector.get(skill, 0.0)), 2)


def _extract_first_pass_score(saved_state: dict[str, Any]) -> float | None:
    first_pass = saved_state.get("first_pass")
    if not isinstance(first_pass, dict):
        return None
    value = first_pass.get("weighted_score_percent")
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _is_attempt_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        key in value
        for key in ("question_results", "answers", "weighted_score_percent", "passed")
    )


def _extract_saved_attempt(saved_state: dict[str, Any]) -> dict[str, Any]:
    if _is_attempt_snapshot(saved_state):
        return saved_state

    for key in ("best_attempt", "latest_attempt", "best_pass_attempt"):
        attempt = saved_state.get(key)
        if _is_attempt_snapshot(attempt):
            return attempt
    return {}


def _extract_best_passing_attempt(saved_state: dict[str, Any]) -> dict[str, Any]:
    if "weighted_score_percent" in saved_state and _is_passing_attempt_snapshot(saved_state):
        return saved_state

    for key in ("best_attempt", "best_pass_attempt"):
        attempt = saved_state.get(key)
        if _is_passing_attempt_snapshot(attempt):
            return attempt
    return {}


def _extract_attempt_score(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    score = value.get("weighted_score_percent")
    if isinstance(score, (int, float)):
        return float(score)
    return 0.0


def _extract_question_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("question_results", [])
    if not isinstance(raw, list):
        return []
    return [result for result in raw if isinstance(result, dict)]


def _split_question_options(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [part.strip() for part in raw.split("|")]


def _build_question_lookup_for_result_detail(
    quiz_content: Any,
) -> dict[str, dict[str, Any]]:
    try:
        questions = _build_question_bank(_normalize_quiz_content(quiz_content))
    except HTTPException:
        return {}

    return {
        question["question_id"]: {
            "question_text": question["stem"],
            "options": _split_question_options(question["options"]),
        }
        for question in questions
    }


def _enrich_question_results(
    question_results: list[dict[str, Any]],
    question_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for result in question_results:
        lookup = question_lookup.get(str(result.get("question_id", "")), {})
        enriched.append(
            {
                **result,
                "question_text": str(lookup.get("question_text", "") or ""),
                "options": lookup.get("options", []),
            }
        )
    return enriched


def _extract_answers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("answers", [])
    if not isinstance(raw, list):
        return []
    return [answer for answer in raw if isinstance(answer, dict)]


def _extract_question_order(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    raw = value.get("question_order", [])
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _drop_redundant_best_attempt_keys(saved_state: dict[str, Any]) -> None:
    for key in (
        "best_pass_attempt",
        "highest_attempt",
        "highest_answer",
        "highest_answers",
    ):
        saved_state.pop(key, None)


def _is_passing_attempt_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed

    return _extract_attempt_score(value) >= LESSON_PASS_THRESHOLD_PERCENT


def _compute_hint_breakdown(attempt: dict[str, Any]) -> tuple[int, int, int, int, int]:
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


def _derive_result_status(user_lesson: UserLesson | None, attempt: dict[str, Any]) -> str:
    if user_lesson and user_lesson.status == "completed":
        return "passed"
    if _is_passing_attempt_snapshot(attempt):
        return "passed"
    if _is_attempt_snapshot(attempt):
        return "failed"
    if user_lesson and user_lesson.status:
        return user_lesson.status
    return "not_started"


def _extract_best_score(saved_state: dict[str, Any], fallback_progress: Any) -> float:
    best_attempt_score = _extract_attempt_score(_extract_best_passing_attempt(saved_state))

    fallback_score = 0.0
    if (
        isinstance(fallback_progress, (int, float))
        and float(fallback_progress) >= LESSON_PASS_THRESHOLD_PERCENT
    ):
        fallback_score = float(fallback_progress)

    return round(max(best_attempt_score, fallback_score), 2)


def _normalize_radar_vector(value: Any) -> dict[str, float]:
    vector = _coerce_json_object(value)
    return {
        skill: float(vector.get(skill, 0.0) or 0.0)
        for skill in SKILL_KEYS
    }


def _normalize_prev_stack(value: Any) -> dict[str, list[float]]:
    stack = _coerce_json_object(value)
    normalized: dict[str, list[float]] = {}
    for skill in SKILL_KEYS:
        raw = stack.get(skill, [])
        if not isinstance(raw, list):
            normalized[skill] = []
            continue
        normalized[skill] = [
            float(item)
            for item in raw
            if isinstance(item, (int, float))
        ]
    return normalized


def _parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _find_quiz_object(value: Any, depth: int = 0) -> dict[str, Any] | None:
    if (
        isinstance(value, dict)
        and {"fill_blank", "multi_select", "ordering"}.issubset(value.keys())
    ):
        return value

    if isinstance(value, dict) and depth < 3:
        for nested in value.values():
            found = _find_quiz_object(nested, depth + 1)
            if found is not None:
                return found
    return None


def _coerce_json_object(value: Any) -> dict[str, Any]:
    parsed = _parse_maybe_json(value)
    return parsed if isinstance(parsed, dict) else {}


def _get_user_lesson(db: Session, user_id: int, lesson_id: int) -> UserLesson | None:
    return (
        db.query(UserLesson)
        .filter(UserLesson.user_id == user_id, UserLesson.lesson_id == lesson_id)
        .order_by(UserLesson.id.asc())
        .first()
    )


async def evaluate_user_answer(
    section_type: str,
    context: str,
    question: str,
    reference_answer: str,
    user_answer: str,
) -> str:
    if section_type == "reading":
        prompt = PROMPT_D1_TEMPLATE.format(
            reading_content=context,
            question=question,
            reference_answer=reference_answer,
            user_answer=user_answer,
        )
    elif section_type == "dialogue":
        prompt = PROMPT_D2_TEMPLATE.format(
            question=question,
            reference_answer=reference_answer,
            user_answer=user_answer,
        )
    elif section_type == "listening":
        prompt = PROMPT_D3_TEMPLATE.format(
            listening_content=context,
            question=question,
            reference_answer=reference_answer,
            user_answer=user_answer,
        )
    else:
        raise ValueError(f"Unknown section type: {section_type}")

    client = GeminiClientPool()
    try:
        response = await client.generate_json(prompt)
        text = response.text.strip()
        
        # Clean markdown code blocks if any
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        data = json.loads(text)
        return data.get("feedback_summary", "Good effort! Keep practicing.")
    except Exception as e:
        return "Great effort! (AI evaluation unavailable at the moment)"
