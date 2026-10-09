"""Quality gates / validators for AI generator output (spec §9).

The actual validation logic has been extracted to focused sub-modules:

  - validators_placement.py — Prompt A gate (placement test)
  - validators_course.py    — Prompt B-1/B-2 gate (topic outline + lesson shells)
  - validators_lesson.py    — Prompt C gate (theory content + quiz content)

All public names are re-exported here for backward compatibility.
"""

# ─── Re-exports ──────────────────────────────────────────────────────────────

from app.core.ai.placement.validators_placement import (  # noqa: F401
    band_of,
    band_distribution,
    soft_band_score,
    validate_placement_block,
    NUM_PLACEMENT_QUESTIONS_PER_SKILL,
    VALID_LEVELS,
    VALID_SKILLS,
    VALID_EXPANDED_SKILLS,
    VALID_ANSWERS,
    SOFT_BAND_THRESHOLD,
)

from app.core.ai.course.validators_course import (  # noqa: F401
    validate_topic_outline,
    validate_more_topics,
    validate_lesson_shells,
    NUM_TOPICS,
    NUM_LESSONS_PER_TOPIC,
    VALID_SEED_TIERS,
    VALID_DIFFICULTY_TIERS,
    EXPECTED_TIERS,
    TIER_SPLIT_MIN,
    TIER_SPLIT_MAX,
)

from app.core.ai.lesson.validators_lesson import (  # noqa: F401
    repair_practice_tasks,
    repair_stem_templates,
    repair_theory_furigana,
    validate_theory_content,
    validate_quiz_content,
    STOCK_BANNED_PHRASES,
    STOCK_BANNED_PREFIXES,
)

# Legacy re-export kept from original file
from app.core.ai.dispatch.prompts import render_task_suggested_answer  # noqa: F401
