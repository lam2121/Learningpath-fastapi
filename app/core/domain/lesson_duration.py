"""Lesson duration estimation based on generated theory and quiz payloads."""

from collections.abc import Mapping, Sequence
from typing import Any

READING_WPM = 122
VOCAB_RECALL_SECONDS_PER_TERM = 8
QUIZ_TIME_SECONDS = {
    "ordering": 42,
    "fill_blank": 20,
    "multi_select": 30,
}
DEFAULT_QUESTION_SECONDS = 25
MIN_MINUTES = 5
MAX_MINUTES = 60


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def count_words(text: str) -> int:
    if not text:
        return 0
    cleaned = (
        text.replace("||", " ").replace("|", " ").replace("#", " ").strip()
    )
    if not cleaned:
        return 0
    return len([part for part in cleaned.split() if part])


def count_vocab_terms(vocab_field: str) -> int:
    if not vocab_field:
        return 0
    return sum(
        1
        for entry in (part.strip() for part in vocab_field.split("#"))
        if entry and len([segment for segment in entry.split("|") if segment.strip()]) >= 4
    )


def calculate_theory_minutes(theory: Any) -> float:
    if isinstance(theory, Mapping):
        total_words = 0
        vocab_terms = len(theory.get("vocab", {}).get("items", []))

        def _extract_words(val: Any) -> int:
            if isinstance(val, str):
                return count_words(val)
            elif isinstance(val, Mapping):
                return sum(_extract_words(v) for v in val.values())
            elif isinstance(val, Sequence) and not isinstance(val, (str, bytes, bytearray)):
                return sum(_extract_words(item) for item in val)
            return 0

        total_words = _extract_words(theory)
        reading_minutes = total_words / READING_WPM
        recall_minutes = (vocab_terms * VOCAB_RECALL_SECONDS_PER_TERM) / 60
        return reading_minutes + recall_minutes

    if not isinstance(theory, Sequence) or isinstance(theory, (str, bytes, bytearray)):
        return 0.0

    total_words = 0
    vocab_terms = 0

    for section in theory:
        if not isinstance(section, Sequence) or isinstance(
            section, (str, bytes, bytearray)
        ):
            continue

        values = list(section)
        if len(values) < 4:
            continue

        section_type = _as_text(values[0]).strip()
        field1 = _as_text(values[1])
        field2 = _as_text(values[2])
        field3 = _as_text(values[3])

        total_words += count_words(field1) + count_words(field2) + count_words(field3)
        if section_type == "vocab":
            vocab_terms += count_vocab_terms(field1)

    reading_minutes = total_words / READING_WPM
    recall_minutes = (vocab_terms * VOCAB_RECALL_SECONDS_PER_TERM) / 60
    return reading_minutes + recall_minutes


def calculate_quiz_minutes(quiz: Any) -> float:
    if not isinstance(quiz, Mapping):
        return 0.0

    total_seconds = 0
    for quiz_type, items in quiz.items():
        if not isinstance(items, list):
            continue
        per_question_seconds = QUIZ_TIME_SECONDS.get(
            str(quiz_type), DEFAULT_QUESTION_SECONDS
        )
        total_seconds += len(items) * per_question_seconds

    return total_seconds / 60


def estimate_lesson_duration(theory: Any, quiz: Any) -> int:
    raw_total = calculate_theory_minutes(theory) + calculate_quiz_minutes(quiz)
    clamped = min(max(raw_total, MIN_MINUTES), MAX_MINUTES)
    return round(clamped)
