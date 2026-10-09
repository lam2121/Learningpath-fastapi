"""Shared quiz normalization, attempt parsing, and scoring helpers.

Used across Lesson Quiz, Topic Quiz, Final Quiz, and User Serializers.
Extracted for single-responsibility and deduplication.
"""

from datetime import datetime
import json
from typing import Any

from app.feature.quiz.lesson_quiz_scoring import (
    HINT_CREDIT,
    LESSON_PASS_THRESHOLD_PERCENT,
    PLACEMENT_EVIDENCE_WEIGHT,
    compute_lesson_score_percent,
    compute_radar_score_for_skill,
    normalize_index_answer,
)

SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


def parse_iso_datetime(value: object | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_maybe_json(value: Any) -> Any:
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


def coerce_json_object(value: Any) -> dict[str, Any]:
    parsed = parse_maybe_json(value)
    return parsed if isinstance(parsed, dict) else {}


def find_quiz_object(value: Any, depth: int = 0) -> dict[str, Any] | None:
    if (
        isinstance(value, dict)
        and {"fill_blank", "multi_select", "ordering"}.issubset(value.keys())
    ):
        return value

    if isinstance(value, dict) and depth < 3:
        for nested in value.values():
            found = find_quiz_object(nested, depth + 1)
            if found is not None:
                return found
    return None


def is_attempt_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        key in value
        for key in ("question_results", "answers", "weighted_score_percent", "passed")
    )


def extract_saved_attempt(saved_state: dict[str, Any]) -> dict[str, Any]:
    if is_attempt_snapshot(saved_state):
        return saved_state

    for key in ("best_attempt", "latest_attempt", "best_pass_attempt"):
        attempt = saved_state.get(key)
        if is_attempt_snapshot(attempt):
            return attempt
    return {}


def is_passing_attempt_snapshot(value: Any, threshold: float = LESSON_PASS_THRESHOLD_PERCENT) -> bool:
    if not isinstance(value, dict):
        return False

    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed

    return extract_attempt_score(value) >= threshold


def extract_best_passing_attempt(
    saved_state: dict[str, Any], threshold: float = LESSON_PASS_THRESHOLD_PERCENT
) -> dict[str, Any]:
    if "weighted_score_percent" in saved_state and is_passing_attempt_snapshot(saved_state, threshold):
        return saved_state

    for key in ("best_attempt", "best_pass_attempt"):
        attempt = saved_state.get(key)
        if is_passing_attempt_snapshot(attempt, threshold):
            return attempt
    return {}


def extract_attempt_score(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    score = value.get("weighted_score_percent")
    if isinstance(score, (int, float)):
        return float(score)
    score_p = value.get("score_percent")
    if isinstance(score_p, (int, float)):
        return float(score_p)
    return 0.0


def extract_question_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw = value.get("question_results", [])
    if not isinstance(raw, list):
        return []
    return [result for result in raw if isinstance(result, dict)]


def compute_hint_breakdown(attempt: dict[str, Any]) -> tuple[int, int, int, int, int]:
    question_results = extract_question_results(attempt)
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


def normalize_radar_vector(value: Any) -> dict[str, float]:
    vector = coerce_json_object(value)
    return {
        skill: float(vector.get(skill, 0.0) or 0.0)
        for skill in SKILL_KEYS
    }


def normalize_prev_stack(value: Any) -> dict[str, list[float]]:
    stack = coerce_json_object(value)
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
