"""Validators for Generator A — Placement Test output (spec §9).

Validates skill block arrays for correct structure, band distribution,
and field constraints.
"""

import re
from typing import Any

from app.core.infra.config import app_config

NUM_PLACEMENT_QUESTIONS_PER_SKILL = app_config.NUM_PLACEMENT_QUESTIONS_PER_SKILL
VALID_LEVELS = ["Easy", "Medium", "Hard", "Expert"]
VALID_SKILLS = {"D_doc", "C_comm", "T_trouble", "G_custom"}
VALID_EXPANDED_SKILLS = {"Context_layer", "Language_layer"}
VALID_ANSWERS = {"A", "B", "C", "D"}

# Generator B-1 / B-2 constants
NUM_TOPICS = app_config.NUM_TOPICS_PER_ROLE
NUM_LESSONS_PER_TOPIC = app_config.NUM_LESSONS_PER_TOPIC
VALID_SEED_TIERS = {"tier_1", "tier_2"}
VALID_DIFFICULTY_TIERS = {"basic", "intermediate", "advanced"}
EXPECTED_TIERS = app_config.LESSON_TIER_ORDER
# Soft tier-split check: ~50/50 tier_1/tier_2 (spec §9 B-1), tolerance of ±2.
TIER_SPLIT_MIN = NUM_TOPICS // 2 - 2
TIER_SPLIT_MAX = NUM_TOPICS // 2 + 2

# Soft band check: >= SOFT_BAND_THRESHOLD (two thirds) of the questions per skill must land
# in their contracted bands before a targeted re-roll is triggered (spec §9).
SOFT_BAND_THRESHOLD = NUM_PLACEMENT_QUESTIONS_PER_SKILL * 2 // 3


def band_of(level: str) -> int:
    """Return 1-based band index for a level string, or -1 if invalid."""
    try:
        return VALID_LEVELS.index(level) + 1
    except ValueError:
        return -1


def band_distribution(rows: list[list[Any]]) -> list[int]:
    """Count questions per band (list of 4 ints, one per band 1-4)."""
    counts = [0, 0, 0, 0]
    for row in rows:
        level = row[1]
        idx = band_of(level) - 1
        if 0 <= idx < 4:
            counts[idx] += 1
    return counts


def soft_band_score(rows: list[list[Any]]) -> int:
    """
    Soft check: for each band contracted to hold 4 questions, count the
    questions that are correctly placed (min(count, 4)). Sum over bands.
    >= SOFT_BAND_THRESHOLD (8) passes; otherwise a targeted re-roll is triggered.
    """
    counts = band_distribution(rows)
    return sum(min(c, app_config.PLACEMENT_QUESTIONS_PER_BAND) for c in counts)


def validate_placement_block(rows: Any, target_skill: str) -> dict:
    """
    Validate one skill block (12 questions) from Prompt A against spec §9.

    Returns a dict:
    {
      "ok": bool,
      "errors": [str, ...],   # hard failures
      "warnings": [str, ...], # soft band violations (trigger re-roll)
    }
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(rows, list):
        errors.append(f"Response is not a JSON array (got {type(rows).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if len(rows) != NUM_PLACEMENT_QUESTIONS_PER_SKILL:
        errors.append(
            f"Expected {NUM_PLACEMENT_QUESTIONS_PER_SKILL} questions for skill '{target_skill}', got {len(rows)}"
        )

    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 6:
            errors.append(f"Row {i} must have exactly 6 elements")
            continue

        skill, level, text, options, answer, expanded_skill = row

        if skill != target_skill:
            errors.append(
                f"Row {i}: skill '{skill}' does not match target '{target_skill}'"
            )

        if not isinstance(level, str) or level not in VALID_LEVELS:
            errors.append(
                f"Row {i}: level '{level}' must be one of {VALID_LEVELS}"
            )

        if not isinstance(text, str) or not text.strip():
            errors.append(f"Row {i}: question text is empty")

        if not isinstance(options, str) or options.count("|") != 3:
            errors.append(
                f"Row {i}: options must be exactly 4 pipe-separated options (3 pipes)"
            )

        if answer not in VALID_ANSWERS:
            errors.append(f"Row {i}: correct answer '{answer}' must be one of A/B/C/D")

        if not isinstance(expanded_skill, str) or expanded_skill not in VALID_EXPANDED_SKILLS:
            errors.append(
                f"Row {i}: expanded_skill '{expanded_skill}' must be one of {VALID_EXPANDED_SKILLS}"
            )

    if not errors:
        score = soft_band_score(rows)
        if score < SOFT_BAND_THRESHOLD:
            warnings.append(
                f"Soft band check failed: {score}/{NUM_PLACEMENT_QUESTIONS_PER_SKILL} "
                f"questions in contracted bands (threshold {SOFT_BAND_THRESHOLD})"
            )

    return {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
    }


