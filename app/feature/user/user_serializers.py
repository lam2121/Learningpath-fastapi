"""Serialization and normalization helpers for user domain data.

Extracted from user_router.py for single responsibility.
"""

from datetime import datetime
import json

from app.feature.quiz.lesson_quiz_scoring import LESSON_PASS_THRESHOLD_PERCENT
from app.models.user_lesson import UserLesson

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
