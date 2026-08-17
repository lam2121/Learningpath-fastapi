"""Quality gates / validators for AI generator output (spec §9).

Implements the Prompt A gate (placement test), Prompt B-1 gate (topic outline),
and Prompt B-2 gate (lesson shells).
"""

from typing import Any

NUM_PLACEMENT_QUESTIONS_PER_SKILL = 12
VALID_LEVELS = ["Easy", "Medium", "Hard", "Expert"]
VALID_SKILLS = {"D_doc", "C_comm", "T_trouble", "G_custom"}
VALID_ANSWERS = {"A", "B", "C", "D"}

# Generator B-1 / B-2 constants
NUM_TOPICS = 20
NUM_LESSONS_PER_TOPIC = 6
VALID_SEED_TIERS = {"tier_1", "tier_2"}
VALID_DIFFICULTY_TIERS = {"basic", "intermediate", "advanced"}
EXPECTED_TIERS = [
    "basic",
    "basic",
    "intermediate",
    "intermediate",
    "advanced",
    "advanced",
]
# Soft tier-split check: ~50/50 tier_1/tier_2 (spec §9 B-1), tolerance of ±2.
TIER_SPLIT_MIN = 8
TIER_SPLIT_MAX = 12

# Soft band check: >= SOFT_BAND_THRESHOLD of 12 questions per skill must land
# in their contracted bands before a targeted re-roll is triggered (spec §9).
SOFT_BAND_THRESHOLD = 8


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


def validate_topic_outline(rows: Any, baseline: dict[str, int]) -> dict:
    """
    Validate the Prompt B-1 output (20-topic course outline) against spec §9.

    Hard errors: row count, element count, skill/tier enums, and the EXACT
    per-skill distribution `baseline% × 20 / 100`. Soft warning: tier split
    ~50/50 (tier_1 in [8, 12]) — accepts an otherwise-valid outline on the
    final retry, mirroring the Prompt A band check.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(rows, list):
        errors.append(f"Response is not a JSON array (got {type(rows).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if len(rows) != NUM_TOPICS:
        errors.append(f"Expected {NUM_TOPICS} topics, got {len(rows)}")

    counts = {s: 0 for s in VALID_SKILLS}
    tier_counts = {t: 0 for t in VALID_SEED_TIERS}

    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 3:
            errors.append(f"Row {i} must have exactly 3 elements")
            continue

        name, skill, tier = row

        if not isinstance(name, str) or not name.strip():
            errors.append(f"Row {i}: topic name is empty")

        if skill not in VALID_SKILLS:
            errors.append(
                f"Row {i}: skill '{skill}' must be one of {sorted(VALID_SKILLS)}"
            )
        else:
            counts[skill] += 1

        if tier not in VALID_SEED_TIERS:
            errors.append(
                f"Row {i}: seed tier '{tier}' must be one of {sorted(VALID_SEED_TIERS)}"
            )
        else:
            tier_counts[tier] += 1

    expected = {s: baseline.get(s, 0) * NUM_TOPICS // 100 for s in VALID_SKILLS}
    for skill in VALID_SKILLS:
        if counts[skill] != expected[skill]:
            errors.append(
                f"Skill '{skill}' appears {counts[skill]} times, "
                f"expected exactly {expected[skill]}"
            )

    tier_1_count = tier_counts["tier_1"]
    if not (TIER_SPLIT_MIN <= tier_1_count <= TIER_SPLIT_MAX):
        warnings.append(
            f"Tier split off-balance: tier_1={tier_1_count}, "
            f"tier_2={NUM_TOPICS - tier_1_count} (expected ~50/50)"
        )

    return {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
    }


def validate_lesson_shells(rows: Any, topic_skill: str) -> dict:
    """
    Validate the Prompt B-2 output (6 lesson shells for one topic) against spec §9.

    Hard errors: row count, element count, skill/tier enums, tier ordering
    (basic → intermediate → advanced, 2/2/2), and the ADVANCED LESSON
    CONSTRAINT — both final (Advanced) lessons tagged with the topic's own
    primary skill.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(rows, list):
        errors.append(f"Response is not a JSON array (got {type(rows).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if len(rows) != NUM_LESSONS_PER_TOPIC:
        errors.append(f"Expected {NUM_LESSONS_PER_TOPIC} lessons, got {len(rows)}")

    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 3:
            errors.append(f"Row {i} must have exactly 3 elements")
            continue

        title, skill, tier = row

        if not isinstance(title, str) or not title.strip():
            errors.append(f"Row {i}: lesson title is empty")

        if skill not in VALID_SKILLS:
            errors.append(
                f"Row {i}: skill '{skill}' must be one of {sorted(VALID_SKILLS)}"
            )

        if tier not in VALID_DIFFICULTY_TIERS:
            errors.append(
                f"Row {i}: difficulty tier '{tier}' must be one of "
                f"{sorted(VALID_DIFFICULTY_TIERS)}"
            )
        elif i < NUM_LESSONS_PER_TOPIC and tier != EXPECTED_TIERS[i]:
            errors.append(
                f"Row {i}: tier '{tier}' must be '{EXPECTED_TIERS[i]}' "
                "(lessons must be ordered basic → intermediate → advanced)"
            )

    for i in (4, 5):
        if (
            i < len(rows)
            and isinstance(rows[i], list)
            and len(rows[i]) == 3
            and rows[i][1] != topic_skill
        ):
            errors.append(
                f"Row {i}: Advanced lesson must be tagged with the topic's "
                f"primary skill '{topic_skill}', got '{rows[i][1]}'"
            )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ─── Generator C-1: Theory Content (8 sections) ──────────────────────────────

C1_SECTION_ORDER = [
    "scenario",
    "vocab",
    "phrases",
    "reading",
    "dialogue",
    "process",
    "dos_donts",
    "wrapup",
]
NUM_VOCAB = 8
NUM_PATTERNS = 5
MIN_DIALOGUE_KEY_PHRASES = 1


def validate_theory_content(rows: Any) -> dict:
    """
    Validate the Prompt C-1 output (8-section theory content).

    Gate is deliberately minimal (deviation #21): ONLY the 8 section rows in
    the fixed order are checked. No per-row element counts, no word counts,
    and no pinned-count checks — the widest pass window for fallback models
    (llama-3.3-70b / mistral) until a funded Pro key is set.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(rows, list):
        errors.append(f"Response is not a JSON array (got {type(rows).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if len(rows) != len(C1_SECTION_ORDER):
        errors.append(
            f"Expected {len(C1_SECTION_ORDER)} theory sections, got {len(rows)}"
        )
        return {"ok": False, "errors": errors, "warnings": warnings}

    for i, expected in enumerate(C1_SECTION_ORDER):
        row = rows[i]
        section = row[0] if isinstance(row, list) and len(row) > 0 else None
        if section != expected:
            errors.append(f"Row {i}: section type '{section}' must be '{expected}'")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ─── Generator C-2: Combined Quiz (30 questions) ──────────────────────────────

NUM_PER_TYPE = 10
C2_TYPES = ["fill_blank", "multi_select", "ordering"]


def validate_quiz_content(obj: Any) -> dict:
    """
    Validate the Prompt C-2 output (30-question lesson quiz).

    Structural hard errors: exactly 3 keys, exactly `num_per_type` arrays per
    key, 4 elements per array, no empty strings, and per-type option/answer
    constraints (fill_blank: correct answer in options on stripped + case-folded
    text; multi_select: 4-5 options with 1-4 non-duplicate in-range indices;
    ordering: 3-6 options with a non-duplicate in-range index sequence of
    length >= 2). Duplicate stems are a warning, not an error (deviation #22).

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(obj, dict):
        errors.append(f"Response is not a JSON object (got {type(obj).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if set(obj.keys()) != set(C2_TYPES):
        errors.append(
            f"Quiz must have exactly 3 keys {sorted(C2_TYPES)}, got {sorted(obj.keys())}"
        )

    all_stems: list[str] = []

    for qtype in C2_TYPES:
        items = obj.get(qtype)
        if not isinstance(items, list):
            errors.append(f"'{qtype}' must be a list")
            continue
        if len(items) != NUM_PER_TYPE:
            errors.append(
                f"'{qtype}' has {len(items)} questions, expected {NUM_PER_TYPE}"
            )

        for i, item in enumerate(items):
            if not isinstance(item, list) or len(item) != 4:
                errors.append(f"'{qtype}'[{i}] must have exactly 4 elements")
                continue

            stem, options_str, answer, explanation = item

            if not isinstance(stem, str) or not stem.strip():
                errors.append(f"'{qtype}'[{i}]: stem (Index 0) is empty")
            else:
                all_stems.append(stem.strip())

            if not isinstance(explanation, str) or not explanation.strip():
                errors.append(f"'{qtype}'[{i}]: explanation (Index 3) is empty")

            if qtype == "fill_blank":
                if not isinstance(options_str, str) or options_str.count("|") != 3:
                    errors.append(
                        f"fill_blank[{i}]: options must be exactly 4 (3 pipes)"
                    )
                    continue
                options = [o.strip() for o in options_str.split("|") if o.strip()]
                if not isinstance(answer, str) or not answer.strip():
                    errors.append(f"fill_blank[{i}]: correct answer is empty")
                elif answer.strip().casefold() not in {o.casefold() for o in options}:
                    errors.append(
                        f"fill_blank[{i}]: correct answer must appear in the options "
                        "(compared on stripped, case-folded text)"
                    )
            elif qtype == "multi_select":
                if not isinstance(options_str, str) or not (
                    3 <= options_str.count("|") <= 4
                ):
                    errors.append(f"multi_select[{i}]: options must be 4-5 (3-4 pipes)")
                    continue
                num_options = options_str.count("|") + 1
                _check_index_list(
                    errors,
                    qtype,
                    i,
                    answer,
                    min_count=1,
                    max_count=4,
                    max_index=num_options - 1,
                )
            else:  # ordering
                if not isinstance(options_str, str) or not (
                    2 <= options_str.count("|") <= 5
                ):
                    errors.append(f"ordering[{i}]: options must be 3-6 (2-5 pipes)")
                    continue
                num_options = options_str.count("|") + 1
                _check_index_list(
                    errors,
                    qtype,
                    i,
                    answer,
                    min_count=2,
                    max_count=num_options,
                    max_index=num_options - 1,
                )

    # All 30 stems should be unique strings across the quiz (spec §9 C-2);
    # duplicates are a warning, not a hard error (deviation #22).
    if len(all_stems) != len(set(all_stems)):
        warnings.append(
            f"C-2: {len(all_stems) - len(set(all_stems))} duplicate stem(s) — "
            "all 30 stems (Index 0) should be unique strings across the quiz"
        )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _check_index_list(
    errors: list[str],
    qtype: str,
    i: int,
    answer: Any,
    *,
    min_count: int,
    max_count: int,
    max_index: int,
) -> None:
    """Validate a pipe-separated zero-based index list (multi_select / ordering)."""
    if not isinstance(answer, str):
        errors.append(f"{qtype}[{i}]: answer indices must be a string")
        return
    try:
        indices = [int(x) for x in answer.split("|") if x != ""]
    except ValueError:
        errors.append(f"{qtype}[{i}]: answer indices must be zero-based integers")
        return
    if not (min_count <= len(indices) <= max_count):
        errors.append(
            f"{qtype}[{i}]: expected {min_count}-{max_count} indices, got {len(indices)}"
        )
    if len(set(indices)) != len(indices):
        errors.append(f"{qtype}[{i}]: duplicate indices")
    for idx in indices:
        if not (0 <= idx <= max_index):
            errors.append(f"{qtype}[{i}]: index {idx} out of range (0-{max_index})")
