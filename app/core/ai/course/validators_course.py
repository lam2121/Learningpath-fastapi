"""Validators for Generator B — Course Outline output (spec §9).

Validates topic outlines (B-1) and lesson shell arrays (B-2).
"""

import re
from typing import Any

from app.core.infra.config import app_config

VALID_SKILLS = {"D_doc", "C_comm", "T_trouble", "G_custom"}
VALID_SEED_TIERS = {"tier_1", "tier_2"}
VALID_DIFFICULTY_TIERS = {"basic", "intermediate", "advanced"}
NUM_TOPICS = app_config.NUM_TOPICS_PER_ROLE
NUM_LESSONS_PER_TOPIC = app_config.NUM_LESSONS_PER_TOPIC
EXPECTED_TIERS = app_config.LESSON_TIER_ORDER
TIER_SPLIT_MIN = NUM_TOPICS // 2 - 2
TIER_SPLIT_MAX = NUM_TOPICS // 2 + 2

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


def validate_more_topics(
    rows: Any, skill: str, count: int, existing_topics: list[tuple[str, str]]
) -> dict:
    """
    Validate the B-1 extension output (`count` extra topics for one skill).

    `existing_topics` is the role's current `(name, primary_skill)` list.

    Hard errors: row count, element count, empty name, skill other than the
    requested one, seed-tier enum, and a name that repeats an existing topic of
    the role or another row of the same batch (case-insensitive).

    Soft warning: a name that starts with the same opening word as an existing
    topic of the same skill or as another row of the batch (look-alike names).
    Like the B-1 tier-split warning, it triggers a retry but is accepted on the
    final attempt so it never blocks a run.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(rows, list):
        errors.append(f"Response is not a JSON array (got {type(rows).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if len(rows) != count:
        errors.append(f"Expected {count} topics, got {len(rows)}")

    seen = {name.strip().lower() for name, _ in existing_topics}
    used_openers = {
        name.split()[0].lower()
        for name, topic_skill in existing_topics
        if topic_skill == skill and name.split()
    }

    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 3:
            errors.append(f"Row {i} must have exactly 3 elements")
            continue

        name, row_skill, tier = row

        if not isinstance(name, str) or not name.strip():
            errors.append(f"Row {i}: topic name is empty")
        else:
            key = name.strip().lower()
            if key in seen:
                errors.append(
                    f"Row {i}: topic '{name}' duplicates an existing topic; "
                    "generate a different one"
                )
            seen.add(key)

            opener = key.split()[0]
            if opener in used_openers:
                warnings.append(
                    f"Row {i}: topic '{name}' starts with '{name.split()[0]}', "
                    f"an opening word already used by another '{skill}' topic; "
                    "start it with a different word"
                )
            used_openers.add(opener)

        if row_skill != skill:
            errors.append(f"Row {i}: skill '{row_skill}' must be exactly '{skill}'")

        if tier not in VALID_SEED_TIERS:
            errors.append(
                f"Row {i}: seed tier '{tier}' must be one of {sorted(VALID_SEED_TIERS)}"
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

    for i in range(NUM_LESSONS_PER_TOPIC - app_config.NUM_ADVANCED_PER_TOPIC, NUM_LESSONS_PER_TOPIC):
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
    "listening",
    "wrapup",
]
NUM_VOCAB = app_config.NUM_VOCAB
NUM_PATTERNS = app_config.NUM_PATTERNS
MIN_DIALOGUE_KEY_PHRASES = 1

