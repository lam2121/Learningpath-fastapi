"""Generator A (Placement Test) + Generator B (Course Outline) + Generator C (Lesson Content).

The actual pipeline implementations have been extracted to focused sub-modules:

  - generation_utils.py       — Shared utilities (JSON parsing, logging, KeyedMutex)
  - generation_placement.py   — Generator A (Placement Test questions)
  - generation_course.py      — Generator B (Topic Outline + Lesson Shells)
  - generation_lesson.py      — Generator C (Theory + Quiz content per lesson)

All public names are re-exported here for backward compatibility.
"""

# ─── Re-exports for backward compatibility ───────────────────────────────────

from app.core.ai.dispatch.generation_utils import (  # noqa: F401
    KeyedMutex,
    _find_first_list,
    _strip_code_fences,
    _extract_json_start,
    _try_literal_eval,
    _unescape_json_string,
    _parse_json,
    _log_usage,
    _record_rejected,
    MODEL,
    MAX_ATTEMPTS,
    LETTER_TO_INDEX,
    MAX_PLACEMENT_OUTPUT_TOKENS,
)

from app.core.ai.placement.generation_placement import (  # noqa: F401
    _insert_questions,
    _generate_skill_block,
    generate_placement_for_role,
)

from app.core.ai.course.generation_course import (  # noqa: F401
    _normalize_topic_outline,
    _normalize_lesson_shells,
    _generate_topic_outline,
    _generate_more_topics,
    _generate_lesson_shells,
    _insert_topics,
    _insert_lesson_shells,
    generate_course_for_role,
    generate_more_topics_for_role,
)

from app.core.ai.lesson.generation_lesson import (  # noqa: F401
    _parse_json_object,
    extract_vocab_and_phrases,
    _clean_stem,
    extract_topic_progression,
    _base_doc_category,
    resolve_reading_doc_type,
    _generate_lesson_theory,
    _generate_lesson_quiz,
    generate_lesson_content,
)
