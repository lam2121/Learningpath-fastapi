"""Prompt templates for AI content generators.

This module retains the shared constants and skill-definition helpers used by
every prompt family. The large prompt templates, JSON schema definitions, and
enrichment/normalization logic have been extracted into focused sub-modules:

  - prompts_placement.py  — Prompt A (Placement Test)
  - prompts_course.py     — Prompt B-1/B-2 (Topic Outline + Lesson Shells)
  - prompts_lesson.py     — Prompt C-1/C-2 (Theory Content + Lesson Quiz)
  - prompts_quiz.py       — Prompt D/E/F (Evaluation, AI Coach, Pronunciation)
  - c1_enrichment.py      — parse_text_to_structured_reading, enrich_c1_object, etc.
  - c1_schema.py          — C-1 JSON Schema definitions

All public names are re-exported here for backward compatibility.
"""

import json
import re

# ─── Shared constants & helpers (from prompts_common) ─────────────────────────

from app.core.ai.dispatch.prompts_common import (  # noqa: F401
    NUM_PLACEMENT_QUESTIONS_PER_SKILL,
    SKILLS,
    SKILL_TITLES,
    NUM_VOCAB,
    NUM_PATTERNS,
    render_skill_definitions_block,
    get_skill_description,
)


# ─── Re-exports for backward compatibility ───────────────────────────────────
# Consumers can keep importing from `app.core.ai.prompts` without changes.

from app.core.ai.placement.prompts_placement import (  # noqa: E402, F401
    PROMPT_A_TEMPLATE,
    build_prompt_a,
    retry_prompt_a,
)

from app.core.ai.course.prompts_course import (  # noqa: E402, F401
    NUM_TOPICS_PER_ROLE,
    NUM_LESSONS_PER_TOPIC,
    NUM_BASIC_PER_TOPIC,
    NUM_INTERMEDIATE_PER_TOPIC,
    NUM_ADVANCED_PER_TOPIC,
    PROMPT_B1_TEMPLATE,
    PROMPT_B1_MORE_TEMPLATE,
    PROMPT_B2_TEMPLATE,
    build_prompt_b1,
    build_prompt_b1_more,
    build_prompt_b2,
    retry_prompt_b1,
    retry_prompt_b2,
)

from app.core.ai.lesson.prompts_lesson import (  # noqa: E402, F401
    PROMPT_C1_TEMPLATE,
    PROMPT_C1_V4_TEMPLATE,
    build_numbered_skeleton,
    build_prompt_c1,
    retry_prompt_c1,
)

from app.core.ai.lesson.c1_enrichment import (  # noqa: E402, F401
    parse_text_to_structured_reading,
    render_task_suggested_answer,
    render_task_suggested_answer_trilingual,
    KNOWN_TEACHER_NOTES,
    enrich_c1_object,
    enrich_c1_v3_object,
    normalize_c1_object,
)

from app.core.ai.lesson.c1_schema import (  # noqa: E402, F401
    get_c1_json_schema,
    get_c1_generation_schema,
    get_c1_stored_schema,
)

from app.core.ai.quiz.prompts_quiz import (  # noqa: E402, F401
    NUM_PER_TYPE,
    C2_EXAMPLE,
    build_prompt_c2,
    retry_prompt_c2,
    PROMPT_C2_TEMPLATE,
    PROMPT_D1_TEMPLATE,
    PROMPT_D2_TEMPLATE,
    PROMPT_D3_TEMPLATE,
    PROMPT_D4_TEMPLATE,
    PROMPT_E1_TEMPLATE,
    PROMPT_F1_TEMPLATE,
    PROMPT_F2_TEMPLATE,
    PROMPT_F3_OUTPUT_CONTRACT,
    PROMPT_F4_TEMPLATE,
    PROMPT_F5_TEMPLATE,
)
