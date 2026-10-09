from __future__ import annotations

import json
import re
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.ai.client.gemini import GeminiClientPool, get_gemini_client_pool
from app.core.ai.dispatch.prompts import (
    PROMPT_D1_TEMPLATE,
    PROMPT_D2_TEMPLATE,
    PROMPT_D3_TEMPLATE,
    PROMPT_D4_TEMPLATE,
)
from app.feature.quiz.lesson_quiz_scoring import (
    LESSON_PASS_THRESHOLD_PERCENT,
    compute_lesson_score_percent,
    compute_radar_score_for_skill,
    normalize_index_answer,
)
from app.feature.quiz.quiz_common import (
    coerce_json_object as _coerce_json_object,
    compute_hint_breakdown as _compute_hint_breakdown,
    extract_attempt_score as _extract_attempt_score,
    extract_best_passing_attempt as _extract_best_passing_attempt,
    extract_question_results as _extract_question_results,
    extract_saved_attempt as _extract_saved_attempt,
    find_quiz_object as _find_quiz_object,
    is_attempt_snapshot as _is_attempt_snapshot,
    is_passing_attempt_snapshot as _is_passing_attempt_snapshot,
    normalize_prev_stack as _normalize_prev_stack,
    normalize_radar_vector as _normalize_radar_vector,
    parse_iso_datetime as _parse_iso_datetime,
    parse_maybe_json as _parse_maybe_json,
)
from app.feature.radar.radar_service import update_user_radar_score
from app.models.lesson import Lesson
from app.models.queue import Queue
from app.models.topic import Topic
from app.models.user import User
from app.models.user_lesson import UserLesson
from app.models.user_radar_score import UserRadarScore

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
    # Serialize submission transaction for this user to prevent race conditions
    # when inserting UserLesson or computing radar scores concurrently.
    db.query(User.id).filter(User.id == user_id).with_for_update().first()

    user_lesson = _get_user_lesson(db, user_id, lesson.id, for_update=True)
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
        db.flush()

    saved_state = dict(_coerce_json_object(user_lesson.user_answers))
    server_hinted_ids = set(str(qid) for qid in saved_state.get("active_hint_question_ids", []))

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
        client_used_hint = bool(submitted.get("used_hint", False))
        # Server-enforced hint flag: client cannot evade hint penalty by sending used_hint=False
        used_hint = client_used_hint or (str(question["question_id"]) in server_hinted_ids)
        is_correct = _is_answer_correct(question, answer)

        if is_correct:
            if used_hint:
                correct_with_hint_count += 1
            else:
                correct_no_hint_count += 1
        else:
            _record_wrong_answer_in_queue(
                db,
                user_id=user_id,
                lesson=lesson,
                question=question,
                user_answer=answer,
            )

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
        "submitted_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "weighted_score_percent": weighted_score_percent,
        "correct_no_hint_count": correct_no_hint_count,
        "correct_with_hint_count": correct_with_hint_count,
        "total_questions": total_questions,
        "passed": current_attempt_passed,
    }

    if current_attempt_is_new_best:
        saved_state = dict(current_attempt_snapshot)
    else:
        saved_state["latest_attempt"] = current_attempt_snapshot

    # Reset active hint IDs so subsequent attempts start clean
    saved_state["active_hint_question_ids"] = []

    user_lesson.attempt_count = attempt_count
    user_lesson.failed_attempts = failed_attempts
    user_lesson.progress = _extract_best_score(saved_state, user_lesson.progress)

    first_pass_radar_applied = False
    if current_attempt_passed and user_lesson.completed_at is None:
        user_lesson.completed_at = datetime.now(UTC).replace(tzinfo=None)
        user_lesson.status = "completed"
        if "first_pass" not in saved_state:
            saved_state["first_pass"] = current_attempt_snapshot
        user_lesson.user_answers = saved_state
        db.flush()
        first_pass_radar_applied = _apply_first_pass_radar_update(
            db,
            user_id=user_id,
            skill=lesson.primary_skill,
            lesson_performance=weighted_score_percent,
        )
    elif user_lesson.completed_at is None:
        user_lesson.status = "in_progress"

    if user_lesson.unlocked_at is None:
        user_lesson.unlocked_at = datetime.now(UTC).replace(tzinfo=None)

    user_lesson.user_answers = saved_state
    flag_modified(user_lesson, "user_answers")
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
    radar = update_user_radar_score(db, user_id)
    return radar is not None


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


def _get_user_lesson(
    db: Session, user_id: int, lesson_id: int, for_update: bool = False
) -> UserLesson | None:
    query = (
        db.query(UserLesson)
        .filter(UserLesson.user_id == user_id, UserLesson.lesson_id == lesson_id)
        .order_by(UserLesson.id.asc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _record_wrong_answer_in_queue(
    db: Session,
    *,
    user_id: int,
    lesson: Lesson,
    question: dict[str, str],
    user_answer: str,
) -> None:
    queue_item = (
        db.query(Queue)
        .filter(
            Queue.user_id == user_id,
            Queue.lesson_id == lesson.id,
            Queue.question_id == question["question_id"],
        )
        .first()
    )
    options_list = _split_question_options(question.get("options", ""))
    if queue_item is None:
        queue_item = Queue(
            user_id=user_id,
            lesson_id=lesson.id,
            question_id=question["question_id"],
            question_type=question.get("question_type", "fill_blank"),
            stem=question.get("stem", ""),
            options=options_list,
            correct_answer=question.get("correct_answer", ""),
            explanation=question.get("explanation", ""),
            last_wrong_answer=user_answer,
            status="pending",
            count=1,
        )
        db.add(queue_item)
    else:
        queue_item.count += 1
        queue_item.last_wrong_answer = user_answer
        queue_item.status = "pending"
        queue_item.stem = question.get("stem", queue_item.stem)
        queue_item.options = options_list if options_list else queue_item.options
        queue_item.correct_answer = question.get("correct_answer", queue_item.correct_answer)
        queue_item.explanation = question.get("explanation", queue_item.explanation)



async def evaluate_user_answer(
    section_type: str,
    context: str,
    question: str,
    reference_answer: str,
    user_answer: str,
) -> dict[str, Any]:
    cleaned_answer = (user_answer or "").strip()
    if not cleaned_answer:
        return {
            "feedback_summary": "Please provide an answer before submitting for evaluation.",
            "score": 0,
        }

    # Length guard: cap at 2000 chars to prevent token-exhaustion or prompt overflow
    capped_answer = cleaned_answer[:2000]

    # Delimiter neutralization: strip any tags attempting to break out of the sandbox
    sanitized_answer = (
        capped_answer.replace("</learner_response>", "")
        .replace("<learner_response>", "")
        .strip()
    )

    if section_type == "reading":
        prompt = PROMPT_D1_TEMPLATE.format(
            reading_content=context,
            question=question,
            reference_answer=reference_answer,
            user_answer=sanitized_answer,
        )
    elif section_type == "dialogue":
        prompt = PROMPT_D2_TEMPLATE.format(
            question=question,
            reference_answer=reference_answer,
            user_answer=sanitized_answer,
        )
    elif section_type == "listening":
        prompt = PROMPT_D3_TEMPLATE.format(
            listening_content=context,
            question=question,
            reference_answer=reference_answer,
            user_answer=sanitized_answer,
        )
    elif section_type in ("wrapup", "challenge", "output_challenge"):
        prompt = PROMPT_D4_TEMPLATE.format(
            wrap_up_content=context,
            question=question,
            user_answer=sanitized_answer,
        )
    else:
        raise ValueError(f"Unknown section type: {section_type}")

    client = get_gemini_client_pool()
    try:
        response = await client.generate_json(prompt, preferred_provider="groq")
        text = response.text.strip()
        
        # Clean markdown code blocks if any
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        text = text.removesuffix("```")
        text = text.strip()
        
        data = json.loads(text)
        score_val = data.get("score")
        if isinstance(score_val, (int, float)):
            score_val = int(score_val)
        elif isinstance(score_val, str) and score_val.strip().isdigit():
            score_val = int(score_val.strip())
        else:
            match = re.search(r"Score:\s*(\d{1,3})(?:\s*/\s*100)?", str(data.get("feedback_summary", "")), re.IGNORECASE)
            score_val = int(match.group(1)) if match else None

        if score_val is not None:
            score_val = max(0, min(100, score_val))

        return {
            "feedback_summary": data.get("feedback_summary", "Good effort! Keep practicing."),
            "score": score_val,
        }
    except Exception:
        return {
            "feedback_summary": "Great effort! (AI evaluation unavailable at the moment)",
            "score": None,
        }


def get_lesson_quiz_hint(
    db: Session,
    user_id: int,
    lesson: Lesson,
    question_id: str,
) -> dict[str, str]:
    user_lesson = _get_user_lesson(db, user_id, lesson.id)
    failed_attempts = user_lesson.failed_attempts if user_lesson else 0
    if failed_attempts < 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hint mode unlocks only after 2 failed attempts.",
        )

    quiz_content = _normalize_quiz_content(lesson.quiz_content)
    questions = _build_question_bank(quiz_content)
    target_question = None
    for q in questions:
        if q["question_id"] == question_id:
            target_question = q
            break

    if target_question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found in this lesson quiz.",
        )

    # Server-side hint validation: mark question as hinted so client cannot evade 0.75 penalty
    saved_state = dict(_coerce_json_object(user_lesson.user_answers if user_lesson else {}))
    hinted_ids = set(str(qid) for qid in saved_state.get("active_hint_question_ids", []))
    hinted_ids.add(str(question_id))
    saved_state["active_hint_question_ids"] = sorted(list(hinted_ids))
    user_lesson.user_answers = saved_state
    flag_modified(user_lesson, "user_answers")
    db.commit()

    return {
        "question_id": question_id,
        "correct_answer": target_question["correct_answer"],
    }
