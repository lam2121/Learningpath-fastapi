"""Generator C — Lesson Content generation pipeline (C-1 Theory + C-2 Quiz).

Lazy per-lesson generation: theory content via C-1, quiz content via C-2.
Includes topic progression analysis and reading doc-type resolution.

Extracted from generation.py for single-responsibility.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import jsonschema
from sqlalchemy.orm import Session

from app.core.ai.client.cost import extract_usage
from app.core.ai.client.gemini import (
    GeminiClientPool,
    GenerationError,
    KillSwitchError,
    LLMResponse,
    assert_generation_enabled,
    get_gemini_client_pool,
)
from app.core.ai.dispatch.generation_utils import (
    KeyedMutex,
    _extract_json_start,
    _log_usage,
    _parse_json,
    _record_rejected,
    _strip_code_fences,
    _try_literal_eval,
    MODEL,
    MAX_ATTEMPTS,
    logger,
)
from app.core.ai.dispatch.prompts import (
    build_prompt_c1,
    build_prompt_c2,
    retry_prompt_c1,
    retry_prompt_c2,
    get_c1_json_schema,
    get_c1_generation_schema,
    get_c1_stored_schema,
    normalize_c1_object,
)
from app.core.ai.dispatch.validators import (
    repair_practice_tasks,
    repair_stem_templates,
    repair_theory_furigana,
    validate_quiz_content,
    validate_theory_content,
    STOCK_BANNED_PHRASES,
)
from app.core.infra.config import app_config
from app.core.infra.database import SessionLocal
from app.core.domain.lesson_duration import estimate_lesson_duration
from app.core.infra.notification_stream import notification_stream_broker
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.rejected_content import RejectedContent
from app.models.topic import Topic
from app.models.user import ADMIN_ROLE_ID, User
from app.models.user_roadmap import UserRoadmap

# ─── Generator C (C-1 Theory + C-2 Quiz) — lazy per-lesson ───────────────────
#
# C-1/C-2 are generated LAZILY per lesson on demand (admin or dev-mode trigger).
# They deliberately bypass the `role_generation` batch table and the 240-call
# batch (~$13 for role 3); a lesson is generated at most once per role and then
# reused by every learner (role-scoped content on the `lesson` row).
#
# Hyperparameters per docs/06 §8.2: C-1 0.3/0.8/8192, C-2 0.15/0.8/4096.
# Both run on GEMINI_PRO_MODEL (routed through the google provider only).

# Serializes regeneration per lesson so concurrent clicks never interleave.
_lesson_locks = KeyedMutex()

C1_MAX_OUTPUT_TOKENS = app_config.LLM_C1_MAX_OUTPUT_TOKENS
C2_MAX_OUTPUT_TOKENS = app_config.LLM_C2_MAX_OUTPUT_TOKENS
C2_TEMPERATURE = app_config.LLM_C2_TEMPERATURE


def _parse_json_object(text: str) -> dict:
    """Parse the raw model output as a JSON object (dict), tolerating fences.

    NEVER array-unwraps — C-2's `{fill_blank:[...], multi_select:[...],
    ordering:[...]}` dict would be destroyed by `_parse_json`'s unwrap logic.
    """
    cleaned = text.strip()
    cleaned = _strip_code_fences(cleaned)
    cleaned = _extract_json_start(cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _try_literal_eval(cleaned)
    if isinstance(parsed, dict):
        return parsed
    raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")


def extract_vocab_and_phrases(theory_content: Any) -> tuple[list[str], list[str]]:
    """
    Extract all vocabulary terms and phrase stems from theory_content,
    supporting both structured JSON object, canonical 4-cell rows,
    and legacy multi-cell rows.
    """
    terms: list[str] = []
    phrases: list[str] = []
    if not theory_content:
        return terms, phrases

    if isinstance(theory_content, dict):
        items = theory_content.get("vocab", {}).get("items", [])
        for it in items:
            if isinstance(it, dict) and it.get("term"):
                raw_term = it["term"]
                # Defensive: term may be a dict (e.g. {"en": "...", "vi": "..."}) in legacy data
                if isinstance(raw_term, dict):
                    raw_term = raw_term.get("en") or next(iter(raw_term.values()), "")
                if isinstance(raw_term, str):
                    t = raw_term.strip()
                    if t:
                        terms.append(t)
        p_items = theory_content.get("phrases", {}).get("items", [])
        for it in p_items:
            if isinstance(it, dict):
                raw_phrase = it.get("stem_template") or it.get("phrase")
                # Defensive: phrase may be a dict in legacy data
                if isinstance(raw_phrase, dict):
                    raw_phrase = raw_phrase.get("en") or next(iter(raw_phrase.values()), "")
                if isinstance(raw_phrase, str):
                    p = raw_phrase.strip()
                    if p:
                        phrases.append(p)
        return terms, phrases

    if isinstance(theory_content, list):
        for row in theory_content:
            if not isinstance(row, list) or len(row) < 2:
                continue
            section = row[0]
            if section == "vocab":
                for cell in row[1:]:
                    if isinstance(cell, str) and "|" in cell:
                        for part in cell.split(" # "):
                            if "|" in part:
                                term = part.split("|")[0].strip()
                                lower = term.lower()
                                if term and not lower.startswith(("pronunciation", "drills", "teacher", "part")):
                                    terms.append(term)
            elif section == "phrases":
                for cell in row[1:]:
                    if isinstance(cell, str) and "|" in cell:
                        for part in cell.split(" # "):
                            if "|" in part:
                                phrase = part.split("|")[0].strip()
                                lower = phrase.lower()
                                if phrase and not lower.startswith(("scenario", "practice", "teacher", "part")):
                                    phrases.append(phrase)
    return terms, phrases


def _clean_stem(p_text: str) -> str:
    """Helper to clean and normalize phrase stems while preserving {{completion}} syntax."""
    s = p_text.strip()
    if "->" in s:
        s = s.split("->")[-1].strip()
    # Keep {{completion}} token intact so the prompt shows the exact template syntax
    if "..." in s and "{{completion}}" not in s:
        s = s.replace("...", "{{completion}}")
    return s


def extract_topic_progression(
    topic: Topic | SimpleNamespace,
    current_lesson: Lesson | SimpleNamespace,
    sibling_lessons: list[Lesson] | None = None,
    role_lessons: list[Lesson] | None = None,
    role_name: str = "",
) -> dict[str, str]:
    """Dynamically compute topic progression and deduplication context across sibling and role lessons for Prompt C-1."""
    siblings = sibling_lessons or []
    curr_idx = 0
    curr_id = getattr(current_lesson, "id", None)
    for i, s in enumerate(siblings):
        if getattr(s, "id", None) == curr_id:
            curr_idx = i
            break
    total_lessons = len(siblings) or 1

    position_str = f"Lesson {curr_idx + 1} of {total_lessons}"
    if siblings:
        sequence_str = " -> ".join(f"[{i + 1}] {s.title}" for i, s in enumerate(siblings))
    else:
        sequence_str = f"[1] {getattr(current_lesson, 'title', '')}"

    skill_labels = {
        "D_doc": "Documentation & Specifications",
        "C_comm": "Communication & Collaboration",
        "T_trouble": "Troubleshooting & Incident Analysis",
        "G_custom": "General Professional Skills",
    }
    skill_code = getattr(topic, "primary_skill", "") or getattr(current_lesson, "primary_skill", "")
    skill_label = skill_labels.get(skill_code, skill_code)
    role_ctx = f" in {role_name} contexts" if role_name else ""
    topic_name = getattr(topic, "name", "")
    goal_str = f"Master practical workplace communication for '{topic_name}' ({skill_label}){role_ctx}."

    lesson_title = getattr(current_lesson, "title", "")
    tier = getattr(current_lesson, "difficulty_tier", "intermediate")
    role_mention = f" for {role_name}" if role_name else ""
    focus_str = f"Focus on '{lesson_title}' at {tier} tier: practical workplace communication, terminology, and interaction patterns{role_mention}."

    prev_concepts: list[str] = []
    sibling_banned_terms: list[str] = []
    sibling_banned_phrases: list[str] = []

    if siblings and curr_idx > 0:
        for idx_p, p in enumerate(siblings[:curr_idx]):
            p_terms, p_phrases = extract_vocab_and_phrases(getattr(p, "theory_content", None))
            sibling_banned_terms.extend(p_terms)
            sibling_banned_phrases.extend(p_phrases)

            p_title = getattr(p, "title", "")
            p_tier = getattr(p, "difficulty_tier", "")
            # Only include full details for the 2 most recent sibling lessons to conserve token budget
            if idx_p >= curr_idx - 2:
                details: list[str] = []
                if p_terms:
                    details.append(f"terms: {', '.join(p_terms[:3])}")
                if p_phrases:
                    details.append(f"phrases: {', '.join(p_phrases[:2])}")
                if details:
                    prev_concepts.append(f"{p_title} ({p_tier}) [{'; '.join(details)}]")
                else:
                    prev_concepts.append(f"{p_title} ({p_tier})")
            else:
                prev_concepts.append(f"{p_title} ({p_tier})")

    prev_str = " | ".join(prev_concepts) if prev_concepts else "None (Initial foundational lesson of this topic)"

    if siblings and curr_idx < total_lessons - 1:
        next_concepts = [
            f"[{i + curr_idx + 2}] {s.title} ({s.difficulty_tier})"
            for i, s in enumerate(siblings[curr_idx + 1:])
        ]
        next_str = " | ".join(next_concepts)
    else:
        next_str = "None (Capstone / final lesson in this topic)"

    # Cross-topic deduplication: collect from already-generated lessons in this role
    other_role_terms: list[str] = []
    other_role_phrases: list[str] = []
    if role_lessons:
        for rl in role_lessons:
            if getattr(rl, "id", None) != curr_id:
                r_terms, r_phrases = extract_vocab_and_phrases(getattr(rl, "theory_content", None))
                other_role_terms.extend(r_terms)
                other_role_phrases.extend(r_phrases)

    # Deduplicate terms: prioritize sibling terms first, then frequent & recent role terms (up to 45 total)
    seen_terms: set[str] = set()
    deduped_terms: list[str] = []
    for t in sibling_banned_terms:
        tl = t.strip().lower()
        if tl and tl not in seen_terms:
            seen_terms.add(tl)
            deduped_terms.append(t.strip())

    for t in other_role_terms:
        tl = t.strip().lower()
        if tl and tl not in seen_terms:
            seen_terms.add(tl)
            deduped_terms.append(t.strip())
            if len(deduped_terms) >= 45:
                break

    # Deduplicate phrases: seed with generic stock phrases, prioritize sibling stems, then role stems up to 80
    seen_phrases: set[str] = set()
    deduped_phrases: list[str] = []

    # 1. Hard-seed generic stock boilerplate phrases to ensure LLM is always warned against them
    for p in STOCK_BANNED_PHRASES:
        clean = _clean_stem(p)
        cl = clean.lower()
        if cl and cl not in seen_phrases:
            seen_phrases.add(cl)
            deduped_phrases.append(clean)

    # 2. Add all sibling stems from the same topic
    for p in sibling_banned_phrases:
        clean = _clean_stem(p)
        cl = clean.lower()
        if cl and cl not in seen_phrases:
            seen_phrases.add(cl)
            deduped_phrases.append(clean)

    # 3. Add stems from prior lessons in the role up to 80 total
    for p in other_role_phrases:
        clean = _clean_stem(p)
        cl = clean.lower()
        if cl and cl not in seen_phrases:
            seen_phrases.add(cl)
            deduped_phrases.append(clean)
            if len(deduped_phrases) >= 80:
                break

    banned_terms_str = ", ".join(f'"{t}"' for t in deduped_terms) if deduped_terms else "None"
    banned_phrases_str = "; ".join(f'"{p}"' for p in deduped_phrases) if deduped_phrases else "None"

    prev_doc_type = None
    if siblings and curr_idx > 0:
        prev_sibling = siblings[curr_idx - 1]
        prev_tc = getattr(prev_sibling, "theory_content", None)
        if prev_tc and isinstance(prev_tc, list):
            for row in prev_tc:
                if len(row) > 1 and "reading" in str(row[0]).lower():
                    prev_doc_type = str(row[1])[:100]
                    break
        if not prev_doc_type:
            prev_doc_type = resolve_reading_doc_type(getattr(prev_sibling, "title", ""), curr_idx - 1)
    elif role_lessons:
        # Cross-topic boundary: check the most recently generated lesson across the role
        for rl in reversed(role_lessons):
            if getattr(rl, "id", None) != curr_id:
                rl_tc = getattr(rl, "theory_content", None)
                if rl_tc and isinstance(rl_tc, list):
                    for row in rl_tc:
                        if len(row) > 1 and "reading" in str(row[0]).lower():
                            prev_doc_type = str(row[1])[:100]
                            break
                if prev_doc_type:
                    break

    reading_doc_type = resolve_reading_doc_type(lesson_title, curr_idx, prev_doc_type)

    return {
        "topic_learning_goal": goal_str,
        "lesson_sequence": sequence_str,
        "current_lesson_position": position_str,
        "previous_lesson_key_concepts": prev_str,
        "current_lesson_focus": focus_str,
        "next_lesson_key_concepts": next_str,
        "banned_terms": banned_terms_str,
        "banned_phrases": banned_phrases_str,
        "sibling_banned_phrases": sibling_banned_phrases,
        "reading_doc_type": reading_doc_type,
    }


READING_DOC_WORKFLOW = [
    "Jira User Story & Acceptance Criteria Spec",
    "Slack / Teams Multi-speaker Discussion Thread",
    "Architecture Decision Record (ADR) or Technical Design Spec",
    "Meeting Minutes & Action Items Log",
    "Scope Change Request (CR) & Impact Analysis",
    "Incident Post-Mortem (RCA) & Root Cause Analysis",
    "Formal Workplace Email or Client Memo",
    "Executive Status Report or Client Sign-off Memo",
]


def _base_doc_category(doc: str | None) -> str:
    if not doc:
        return ""
    dl = doc.lower()
    if "slack" in dl or "teams" in dl or "chat" in dl:
        return "slack"
    if "jira" in dl or "story" in dl or "acceptance criteria" in dl:
        return "jira"
    if "adr" in dl or "architecture" in dl:
        return "adr"
    if "meeting" in dl or "minutes" in dl:
        return "meeting"
    if "post-mortem" in dl or "rca" in dl or "incident" in dl or "troubleshoot" in dl:
        return "incident"
    if "change request" in dl or "cr" in dl:
        return "change_request"
    if "email" in dl or "mail" in dl:
        return "email"
    if "status report" in dl or "memo" in dl:
        return "status_report"
    return dl


def resolve_reading_doc_type(
    lesson_title: str,
    curr_idx: int,
    prev_doc_type: str | None = None,
) -> str:
    """
    Select an authentic workplace document type for the Reading section
    using a hybrid strategy: semantic keywords + positional workflow rotation
    with category-based anti-collision guard against the previous lesson.
    """
    lower = lesson_title.lower() if lesson_title else ""
    matched_type: str | None = None

    if any(k in lower for k in ("incident", "post-mortem", "rca", "troubleshoot", "bug", "constraint", "workaround", "failure")):
        matched_type = "Incident Post-Mortem (RCA) & Root Cause Analysis"
    elif any(k in lower for k in ("meeting", "sync", "standup", "minutes", "alignment", "debrief", "retrospective")):
        matched_type = "Meeting Minutes & Action Items Log"
    elif any(k in lower for k in ("chat", "slack", "teams", "quick", "daily", "channel", "inquiry")):
        matched_type = "Slack / Teams Multi-speaker Discussion Thread"
    elif any(k in lower for k in ("email", "mail", "letter", "memo", "announcement", "outreach", "proposal")):
        matched_type = "Formal Workplace Email or Client Memo"
    elif any(k in lower for k in ("decision", "trade-off", "adr", "architecture", "design", "technical approach")):
        matched_type = "Architecture Decision Record (ADR) or Technical Design Spec"
    elif any(k in lower for k in ("criteria", "story", "spec", "acceptance", "user story", "requirement")):
        matched_type = "Jira User Story & Acceptance Criteria Spec"
    elif any(k in lower for k in ("scope", "change", "negotiat", "adjustment")):
        matched_type = "Scope Change Request (CR) & Impact Analysis"
    elif any(k in lower for k in ("status", "report", "summary", "sign-off", "executive", "closure")):
        matched_type = "Executive Status Report or Client Sign-off Memo"

    prev_cat = _base_doc_category(prev_doc_type)

    # Anti-collision: if semantic match shares the same base category as previous lesson, ignore match
    if matched_type and _base_doc_category(matched_type) == prev_cat:
        matched_type = None

    if matched_type:
        return matched_type

    # Positional workflow rotation fallback
    rotation_idx = curr_idx % len(READING_DOC_WORKFLOW)
    chosen = READING_DOC_WORKFLOW[rotation_idx]

    # If rotational choice collides with previous lesson's category, advance
    while _base_doc_category(chosen) == prev_cat:
        rotation_idx = (rotation_idx + 1) % len(READING_DOC_WORKFLOW)
        chosen = READING_DOC_WORKFLOW[rotation_idx]

    return chosen


async def _generate_lesson_theory(
    client: GeminiClientPool,
    role: JobRole | SimpleNamespace,
    topic: Topic | SimpleNamespace,
    lesson: Lesson | SimpleNamespace,
    progression: dict[str, str] | None = None,
) -> tuple:
    """
    Run Prompt C-1 (7-section theory) for one lesson with retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prog = progression or getattr(lesson, "progression", None) or {}
    prompt = build_prompt_c1(
        role=role.name,
        job_description=role.job_description,
        parent_topic=topic.name,
        lesson_title=lesson.title,
        primary_skill=lesson.primary_skill,
        difficulty_tier=lesson.difficulty_tier,
        skill_definitions=role.skill_definitions or {},
        topic_learning_goal=prog.get("topic_learning_goal"),
        lesson_sequence=prog.get("lesson_sequence"),
        current_lesson_position=prog.get("current_lesson_position"),
        previous_lesson_key_concepts=prog.get("previous_lesson_key_concepts"),
        current_lesson_focus=prog.get("current_lesson_focus"),
        next_lesson_key_concepts=prog.get("next_lesson_key_concepts"),
        banned_terms=prog.get("banned_terms"),
        banned_phrases=prog.get("banned_phrases"),
        reading_doc_type=prog.get("reading_doc_type"),
        schema_version=4,
    )

    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    c1_gen_schema = get_c1_generation_schema(schema_version=4)
    c1_stored_schema = get_c1_stored_schema(schema_version=4)
    c1_model = app_config.GEMINI_PRO_MODEL or "gemini-3.5-flash-lite"

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = (
            prompt
            if (attempt == 0 or not last_error or last_error.startswith("Provider error"))
            else retry_prompt_c1(prompt, last_error)
        )
        try:
            response: LLMResponse = await client.generate_json(
                call_prompt,
                allowed_providers=["google"],
                schema=c1_gen_schema,
                schema_name="c1_theory_schema",
                model=c1_model,
                require_strict_schema=False,
                strict_raw_response=False,
                max_output_tokens=C1_MAX_OUTPUT_TOKENS,
            )
        except GenerationError as exc:
            last_error = f"Provider error: {exc}"
            usage_logs.append(
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "status": "retry",
                    "provider": "none",
                    "model": "none",
                }
            )
            await asyncio.sleep(2.0 * (attempt + 1))
            continue
        prompt_t, comp_t = extract_usage(response)
        raw = response.text.strip()
        last_raw = raw

        # Zero-permissive validation: reject markdown fences or preamble
        if raw.startswith("```"):
            last_error = "Response must be a raw JSON object and cannot contain markdown fences."
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        try:
            rows = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"Invalid JSON syntax ({exc}). Raw preview: {raw[:200]}"
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        if not isinstance(rows, dict):
            last_error = f"Theory generator must output a JSON object with 7 sections and schema_version: 4, got {type(rows).__name__}"
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        # Pre-validation auto-repair: normalize token syntax, furigana, and task collisions
        repair_stem_templates(rows)
        repair_theory_furigana(rows)
        repair_practice_tasks(rows)

        # Step 1: Server-Side Generation Schema Validation on raw AI output (canonical fields only)
        try:
            jsonschema.validate(instance=rows, schema=c1_gen_schema)
        except jsonschema.ValidationError as s_err:
            json_path = ".".join(str(p) for p in s_err.absolute_path) or "root"
            last_error = f"Generation Schema validation error at '{json_path}': {s_err.message}"
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        # Step 2: Validate canonical content before enrichment.  A malformed
        # stem cannot produce derived display fields such as `phrase`; report
        # the actionable stem error to the retry prompt instead of a misleading
        # Stored Schema error about a missing derived field.
        canonical_result = validate_theory_content(
            rows,
            banned_terms=prog.get("banned_terms"),
            banned_phrases=prog.get("banned_phrases"),
            sibling_banned_phrases=prog.get("sibling_banned_phrases"),
        )
        last_checks = canonical_result
        if canonical_result["errors"]:
            last_error = "; ".join(canonical_result["errors"][:4])
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        # Step 3: Safe key normalization & enrichment with derived frontend fields
        rows = normalize_c1_object(rows)

        # Step 3b: Server-Side Stored Schema Validation on enriched output
        try:
            jsonschema.validate(instance=rows, schema=c1_stored_schema)
        except jsonschema.ValidationError as s_err:
            json_path = ".".join(str(p) for p in s_err.absolute_path) or "root"
            last_error = f"Stored Schema validation error at '{json_path}': {s_err.message}"
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        # Step 4: Recheck enriched content before persisting it.
        result = validate_theory_content(
            rows,
            banned_terms=prog.get("banned_terms"),
            banned_phrases=prog.get("banned_phrases"),
            sibling_banned_phrases=prog.get("sibling_banned_phrases"),
        )
        last_checks = result
        if result["ok"]:
            # Store pure structured C-1 JSON object directly (preserving 100% schema fidelity)
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "success",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            return rows, usage_logs, None, last_raw, last_checks

        if result["errors"]:
            last_error = "; ".join(result["errors"][:4])
        else:
            # Soft warning only: accept on the final attempt (best-effort) so a
            # minor nit never blocks a lesson.
            last_error = "; ".join(result["warnings"][:2])
            if attempt == MAX_ATTEMPTS - 1:
                usage_logs.append(
                    {
                        "prompt_tokens": prompt_t,
                        "completion_tokens": comp_t,
                        "status": "success",
                        "provider": response.provider,
                        "model": response.model,
                    }
                )
                return rows, usage_logs, None, last_raw, last_checks

        usage_logs.append(
            {
                "prompt_tokens": prompt_t,
                "completion_tokens": comp_t,
                "status": "retry",
                "provider": response.provider,
                "model": response.model,
            }
        )

    return (
        None,
        usage_logs,
        (last_error or "Theory content generation failed"),
        last_raw,
        last_checks,
    )


async def _generate_lesson_quiz(
    client: GeminiClientPool,
    role: JobRole,
    topic: Topic,
    lesson: Lesson,
    theory: list,
) -> tuple:
    """
    Run Prompt C-2 (30-question quiz grounded in the theory) for one lesson
    with retries. Returns (obj | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_c2(
        role=role.name,
        topic_name=topic.name,
        lesson_title=lesson.title,
        primary_skill=lesson.primary_skill,
        difficulty_tier=lesson.difficulty_tier,
        skill_definitions=role.skill_definitions or {},
        theory_content=json.dumps(theory, ensure_ascii=False),
    )

    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    c2_model = app_config.GEMINI_PRO_MODEL or "gemini-3.5-flash-lite"

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_c2(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(
                call_prompt,
                allowed_providers=["google"],
                model=c2_model,
                temperature=C2_TEMPERATURE,
                max_output_tokens=C2_MAX_OUTPUT_TOKENS,
            )
        except GenerationError as exc:
            last_error = f"Provider error: {exc}"
            usage_logs.append(
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "status": "retry",
                    "provider": "none",
                    "model": "none",
                }
            )
            continue
        prompt_t, comp_t = extract_usage(response)
        raw = response.text
        last_raw = raw

        try:
            obj = _parse_json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"Invalid JSON: {exc}"
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "retry",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            continue

        result = validate_quiz_content(obj)
        last_checks = result
        if result["ok"]:
            usage_logs.append(
                {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": comp_t,
                    "status": "success",
                    "provider": response.provider,
                    "model": response.model,
                }
            )
            return obj, usage_logs, None, last_raw, last_checks

        last_error = "; ".join(result["errors"][:3])
        usage_logs.append(
            {
                "prompt_tokens": prompt_t,
                "completion_tokens": comp_t,
                "status": "retry",
                "provider": response.provider,
                "model": response.model,
            }
        )

    return (
        None,
        usage_logs,
        (last_error or "Lesson quiz generation failed"),
        last_raw,
        last_checks,
    )


async def generate_lesson_content(
    lesson_id: int, *, force: bool = False, resume: bool = False
) -> dict:
    """Lazily generate a lesson's theory (C-1) + quiz (C-2), in that order.

    - Skips silently when the lesson is already generated (role-scoped cache).
    - `force=True` clears theory/quiz and regenerates from scratch (~$0.05 per rerun).
    - `resume=True` reuses already generated valid theory content (C-1) and only
      generates the quiz (C-2), saving ~70% tokens.
    - Notifies all admins in real-time when generation fails or succeeds.
    - Per-lesson lock; usage/rejected/cost plumbing identical to Generators A/B.
    """
    async with _lesson_locks.lock(lesson_id):
        db = SessionLocal()
        try:
            lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
            if lesson is None:
                return {"status": "failed", "error": "lesson not found"}

            topic = db.query(Topic).filter(Topic.id == lesson.topic_id).first()
            if topic is None or not topic.role_id:
                return {
                    "status": "failed",
                    "error": "lesson has no parent topic/role",
                }
            role_id = topic.role_id
            role = db.query(JobRole).filter(JobRole.id == role_id).first()
            if role is None:
                return {"status": "failed", "error": "role not found"}

            # Validate whether theory_content already exists and has valid structure
            has_valid_theory = False
            if isinstance(lesson.theory_content, dict):
                val_res = validate_theory_content(lesson.theory_content)
                if val_res.get("ok"):
                    has_valid_theory = True

            if force and not resume:
                lesson.theory_content = None
                lesson.quiz_content = None
                lesson.estimated_minutes = None
                lesson.is_generated = 0
                has_valid_theory = False
                db.commit()

            # Robust check: A lesson is genuinely complete if both theory and quiz are present
            if lesson.is_generated == 1 and has_valid_theory and lesson.quiz_content and not force:
                return {
                    "status": "skipped",
                    "message": "lesson already generated (shared — reused by all learners of this role)",
                }

            if lesson.is_generated == 1 and not has_valid_theory:
                logger.warning(
                    "Lesson %s marked is_generated=1 but theory_content has invalid/legacy structure (%s). Auto-regenerating cleanly.",
                    lesson_id,
                    type(lesson.theory_content).__name__,
                )
                lesson.theory_content = None
                lesson.quiz_content = None
                lesson.estimated_minutes = None
                lesson.is_generated = 0
                has_valid_theory = False
                db.commit()

            try:
                assert_generation_enabled(db)
            except KillSwitchError as exc:
                lesson.is_generated = -1
                db.commit()
                return {"status": "failed", "error": str(exc)}

            # Query sibling lessons in the same topic to extract dynamic progression
            sibling_lessons = (
                db.query(Lesson)
                .filter(Lesson.topic_id == topic.id)
                .order_by(Lesson.id.asc())
                .all()
            )
            # Query already-generated lessons across this entire role for cross-topic deduplication
            role_lessons = (
                db.query(Lesson)
                .join(Topic, Lesson.topic_id == Topic.id)
                .filter(
                    Topic.role_id == role.id,
                    Lesson.theory_content.isnot(None),
                    Lesson.id != lesson.id,
                )
                .order_by(Lesson.id.desc())
                .all()
            )
            progression = extract_topic_progression(
                topic,
                lesson,
                sibling_lessons,
                role_lessons=role_lessons,
                role_name=role.name,
            )

            lesson_info = {
                "id": lesson.id,
                "title": lesson.title,
                "primary_skill": lesson.primary_skill,
                "difficulty_tier": lesson.difficulty_tier,
                "topic_id": topic.id,
                "topic_name": topic.name,
                "role_id": role.id,
                "role_name": role.name,
                "job_description": role.job_description,
                "skill_definitions": role.skill_definitions or {},
                "progression": progression,
                "has_valid_theory": has_valid_theory,
                "existing_theory": lesson.theory_content if has_valid_theory else None,
            }
        finally:
            db.close()

        # Build lightweight context objects so AI generator functions receive expected attributes
        role_ctx = SimpleNamespace(
            id=lesson_info["role_id"],
            name=lesson_info["role_name"],
            job_description=lesson_info["job_description"],
            skill_definitions=lesson_info["skill_definitions"],
        )
        topic_ctx = SimpleNamespace(
            id=lesson_info["topic_id"],
            name=lesson_info["topic_name"],
            role_id=lesson_info["role_id"],
            primary_skill=lesson_info["primary_skill"],
        )
        lesson_ctx = SimpleNamespace(
            id=lesson_info["id"],
            title=lesson_info["title"],
            primary_skill=lesson_info["primary_skill"],
            difficulty_tier=lesson_info["difficulty_tier"],
            topic_id=lesson_info["topic_id"],
            progression=lesson_info["progression"],
        )

        client = get_gemini_client_pool()
        role_id = lesson_info["role_id"]
        topic_id = lesson_info["topic_id"]
        lesson_title = lesson_info["title"]
        logger.info(
            "Generator C starting for lesson %s ('%s', role %s, force=%s, resume=%s, has_theory=%s)",
            lesson_id,
            lesson_title,
            role_id,
            force,
            resume,
            lesson_info["has_valid_theory"],
        )

        try:
            # ── C-1: theory (runs async without holding any DB connection) ────
            if lesson_info["has_valid_theory"] and (resume or not force):
                logger.info(
                    "Generator C resuming for lesson %s ('%s'): reusing existing theory content, skipping C-1 to save tokens.",
                    lesson_id,
                    lesson_title,
                )
                theory = lesson_info["existing_theory"]
                theory_usage = []
                theory_error = None
                c1_raw = None
                c1_checks = None
            else:
                (
                    theory,
                    theory_usage,
                    theory_error,
                    c1_raw,
                    c1_checks,
                ) = await _generate_lesson_theory(
                    client,
                    role_ctx,
                    topic_ctx,
                    lesson_ctx,
                    progression=lesson_info["progression"],
                )

            if theory is None:
                logger.error(
                    "Generator C-1 failed for lesson %s ('%s'): %s",
                    lesson_id,
                    lesson_title,
                    theory_error or "C-1 failed",
                )
                db = SessionLocal()
                admin_ids = []
                try:
                    for log in theory_usage:
                        _log_usage(
                            db,
                            "C1",
                            role_id,
                            log["prompt_tokens"],
                            log["completion_tokens"],
                            log["status"],
                            log.get("provider"),
                            log.get("model"),
                        )
                    _record_rejected(
                        db,
                        "C1",
                        role_id,
                        f"lesson_id={lesson_id}&title={lesson_title}&step=C1",
                        theory_error or "unknown",
                        c1_raw,
                        c1_checks,
                    )
                    _log_usage(
                        db,
                        "C1",
                        role_id,
                        0,
                        0,
                        "rejected",
                        provider="google",
                        model=app_config.GEMINI_PRO_MODEL or "gemini-3.5-flash-lite",
                    )
                    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
                    if lesson:
                        lesson.is_generated = -1
                    db.commit()
                    admins = db.query(User).filter(User.role_id == ADMIN_ROLE_ID).all()
                    admin_ids = [int(u.id) for u in admins]
                finally:
                    db.close()

                if admin_ids:
                    await notification_stream_broker.publish_many(
                        admin_ids,
                        {
                            "type": "admin_notification",
                            "reason": "lesson_generation_failed",
                            "lesson_id": int(lesson_id),
                            "lesson_title": lesson_title,
                            "topic_id": int(topic_id),
                            "topic_name": topic_ctx.name,
                            "role_id": int(role_id),
                            "role_name": role_ctx.name,
                            "failed_step": "C1",
                            "has_partial_theory": False,
                            "error": str(theory_error or "C-1 theory generation failed"),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )

                return {
                    "status": "failed",
                    "error": theory_error or "C-1 failed",
                    "failed_step": "C1",
                    "has_partial_theory": False,
                }

            # Persist C-1 theory content immediately so it acts as a checkpoint for resume
            if not lesson_info["has_valid_theory"]:
                db = SessionLocal()
                try:
                    chk_lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
                    if chk_lesson:
                        chk_lesson.theory_content = theory
                        db.commit()
                finally:
                    db.close()

            # ── C-2: quiz (grounded in the generated theory, async without DB connection) ─
            (
                quiz,
                quiz_usage,
                quiz_error,
                c2_raw,
                c2_checks,
            ) = await _generate_lesson_quiz(client, role_ctx, topic_ctx, lesson_ctx, theory)

            if quiz is None:
                logger.error(
                    "Generator C-2 failed for lesson %s ('%s'): %s",
                    lesson_id,
                    lesson_title,
                    quiz_error or "C-2 failed",
                )
                db = SessionLocal()
                admin_ids = []
                try:
                    for log in theory_usage:
                        _log_usage(
                            db,
                            "C1",
                            role_id,
                            log["prompt_tokens"],
                            log["completion_tokens"],
                            log["status"],
                            log.get("provider"),
                            log.get("model"),
                        )
                    for log in quiz_usage:
                        _log_usage(
                            db,
                            "C2",
                            role_id,
                            log["prompt_tokens"],
                            log["completion_tokens"],
                            log["status"],
                            log.get("provider"),
                            log.get("model"),
                        )
                    _record_rejected(
                        db,
                        "C2",
                        role_id,
                        f"lesson_id={lesson_id}&title={lesson_title}&step=C2",
                        quiz_error or "unknown",
                        c2_raw,
                        c2_checks,
                    )
                    _log_usage(
                        db,
                        "C2",
                        role_id,
                        0,
                        0,
                        "rejected",
                        provider="google",
                        model=app_config.GEMINI_PRO_MODEL or "gemini-3.5-flash-lite",
                    )
                    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
                    if lesson:
                        lesson.is_generated = -1
                        lesson.theory_content = theory  # Retain theory checkpoint
                    db.commit()
                    admins = db.query(User).filter(User.role_id == ADMIN_ROLE_ID).all()
                    admin_ids = [int(u.id) for u in admins]
                finally:
                    db.close()

                if admin_ids:
                    await notification_stream_broker.publish_many(
                        admin_ids,
                        {
                            "type": "admin_notification",
                            "reason": "lesson_generation_failed",
                            "lesson_id": int(lesson_id),
                            "lesson_title": lesson_title,
                            "topic_id": int(topic_id),
                            "topic_name": topic_ctx.name,
                            "role_id": int(role_id),
                            "role_name": role_ctx.name,
                            "failed_step": "C2",
                            "has_partial_theory": True,
                            "error": str(quiz_error or "C-2 quiz generation failed"),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )

                return {
                    "status": "failed",
                    "error": quiz_error or "C-2 failed",
                    "failed_step": "C2",
                    "has_partial_theory": True,
                }

            # Persist successful generation results with a short-lived DB session
            db = SessionLocal()
            admin_ids = []
            try:
                for log in theory_usage:
                    _log_usage(
                        db,
                        "C1",
                        role_id,
                        log["prompt_tokens"],
                        log["completion_tokens"],
                        log["status"],
                        log.get("provider"),
                        log.get("model"),
                    )
                for log in quiz_usage:
                    _log_usage(
                        db,
                        "C2",
                        role_id,
                        log["prompt_tokens"],
                        log["completion_tokens"],
                        log["status"],
                        log.get("provider"),
                        log.get("model"),
                    )

                lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
                if lesson:
                    lesson.theory_content = theory
                    lesson.quiz_content = quiz
                    lesson.estimated_minutes = estimate_lesson_duration(theory, quiz)
                    lesson.is_generated = 1

                # Auto-resolve any pending rejected_content records for this lesson
                pending_rejected = (
                    db.query(RejectedContent)
                    .filter(
                        RejectedContent.role_id == role_id,
                        RejectedContent.input_preview.like(f"%lesson_id={lesson_id}%"),
                        RejectedContent.status == "pending",
                    )
                    .all()
                )
                for it in pending_rejected:
                    it.status = "fixed"

                assigned_user_ids = [
                    int(row.user_id)
                    for row in db.query(UserRoadmap.user_id)
                    .filter(UserRoadmap.topic_id == topic_id)
                    .distinct()
                    .all()
                ]
                db.commit()
                admins = db.query(User).filter(User.role_id == ADMIN_ROLE_ID).all()
                admin_ids = [int(u.id) for u in admins]
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            # Publish notification to learners
            await notification_stream_broker.publish_many(
                assigned_user_ids,
                {
                    "type": "roadmap_updated",
                    "reason": "lesson_generated",
                    "lesson_id": int(lesson_id),
                    "topic_id": int(topic_id),
                },
            )

            # Publish notification to admins that lesson generation has succeeded/fixed
            if admin_ids:
                await notification_stream_broker.publish_many(
                    admin_ids,
                    {
                        "type": "admin_notification",
                        "reason": "lesson_generation_succeeded",
                        "lesson_id": int(lesson_id),
                        "lesson_title": lesson_title,
                        "topic_id": int(topic_id),
                        "topic_name": topic_ctx.name,
                        "role_id": int(role_id),
                        "role_name": role_ctx.name,
                    },
                )

            logger.info(
                "Generator C finished for lesson %s (role %s)", lesson_id, role_id
            )
            return {"status": "completed", "message": "lesson generated (C1 + C2)"}
        except Exception as exc:
            logger.exception("Generator C crashed for lesson %s", lesson_id)
            db = SessionLocal()
            admin_ids = []
            try:
                _record_rejected(
                    db,
                    "C1",
                    role_id,
                    f"lesson_id={lesson_id}&title={lesson_title}&step=C1",
                    str(exc),
                    None,
                    None,
                )
                _log_usage(db, "C1", role_id, 0, 0, "rejected")
                lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
                if lesson:
                    lesson.is_generated = -1
                db.commit()
                admins = db.query(User).filter(User.role_id == ADMIN_ROLE_ID).all()
                admin_ids = [int(u.id) for u in admins]
            except Exception:
                db.rollback()
            finally:
                db.close()

            if admin_ids:
                await notification_stream_broker.publish_many(
                    admin_ids,
                    {
                        "type": "admin_notification",
                        "reason": "lesson_generation_failed",
                        "lesson_id": int(lesson_id),
                        "lesson_title": lesson_title,
                        "topic_id": int(topic_id),
                        "topic_name": topic_ctx.name,
                        "role_id": int(role_id),
                        "role_name": role_ctx.name,
                        "failed_step": "C1",
                        "has_partial_theory": False,
                        "error": str(exc),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

            return {"status": "failed", "error": str(exc)}
