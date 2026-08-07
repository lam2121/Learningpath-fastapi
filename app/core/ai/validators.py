"""Quality gates / validators for AI generator output (spec §9).

Currently implements only the Prompt A gate (placement test). Generators B1/B2
validators will be added in later phases.
"""

from typing import Any

NUM_PLACEMENT_QUESTIONS_PER_SKILL = 12
BANDS = [
    (1, 2),
    (3, 4),
    (5, 6),
    (7, 8),
]
VALID_SKILLS = {"D_doc", "C_comm", "T_trouble", "G_custom"}
VALID_ANSWERS = {"A", "B", "C", "D"}

# Soft band check: >= SOFT_BAND_THRESHOLD of 12 questions per skill must land
# in their contracted bands before a targeted re-roll is triggered (spec §9).
SOFT_BAND_THRESHOLD = 8


def band_of(level: int) -> int:
    """Return 1-based band index for a level, or -1 if out of 1-8 range."""
    for i, (lo, hi) in enumerate(BANDS, start=1):
        if lo <= level <= hi:
            return i
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
    Soft check: for each band contracted to hold 3 questions, count the
    questions that are correctly placed (min(count, 3)). Sum over bands.
    >= SOFT_BAND_THRESHOLD (8) passes; otherwise a targeted re-roll is triggered.
    """
    counts = band_distribution(rows)
    return sum(min(c, 3) for c in counts)


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
        if not isinstance(row, list) or len(row) != 5:
            errors.append(f"Row {i} must have exactly 5 elements")
            continue

        skill, level, text, options, answer = row

        if skill != target_skill:
            errors.append(
                f"Row {i}: skill '{skill}' does not match target '{target_skill}'"
            )

        if (
            not isinstance(level, int)
            or isinstance(level, bool)
            or not (1 <= level <= 8)
        ):
            errors.append(f"Row {i}: level '{level}' must be an integer 1-8")

        if not isinstance(text, str) or not text.strip():
            errors.append(f"Row {i}: question text is empty")

        if not isinstance(options, str) or options.count("|") != 3:
            errors.append(
                f"Row {i}: options must be exactly 4 pipe-separated options (3 pipes)"
            )

        if answer not in VALID_ANSWERS:
            errors.append(f"Row {i}: correct answer '{answer}' must be one of A/B/C/D")

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
