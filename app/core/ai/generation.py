"""Generator A (Placement Test) + Generator B (Course Outline) orchestrators.

Generator A: 4 Flash calls (one per skill) -> validates each block against spec
§9 -> inserts 48 placement questions per role. Idempotent, retries max 2, logs
every call to ai_usage_log, records rejections, tracks role_generation.

Generator B: `generate_course_for_role` runs Prompt B-1 (1 call -> 20 topics)
then Prompt B-2 (1 call per topic -> 6 lesson shells each). Same retry/logging/
rejection/exception-proofing conventions as Generator A.
"""

import ast
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ai.cost import estimate_cost_usd, extract_usage
from app.core.ai.gemini import (
    GeminiClientPool,
    GenerationError,
    KillSwitchError,
    LLMResponse,
    assert_generation_enabled,
)
from app.core.lesson_duration import estimate_lesson_duration
from app.core.ai.prompts import (
    SKILLS,
    build_prompt_a,
    build_prompt_b1,
    build_prompt_b2,
    build_prompt_c1,
    build_prompt_c2,
    retry_prompt_a,
    retry_prompt_b1,
    retry_prompt_b2,
    retry_prompt_c1,
    retry_prompt_c2,
)
from app.core.ai.validators import (
    validate_lesson_shells,
    validate_placement_block,
    validate_quiz_content,
    validate_theory_content,
    validate_topic_outline,
)
from app.core.config import app_config
from app.core.database import SessionLocal
from app.core.notification_stream import notification_stream_broker
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent
from app.models.topic import Topic
from app.models.user import LEARNING_ENROLLED, User
from app.models.user_roadmap import UserRoadmap

logger = logging.getLogger(__name__)

MODEL = app_config.GEMINI_FLASH_MODEL
QUIZ_TYPE_ID = 1  # quiz_type: 'multiple choice'
MAX_ATTEMPTS = 3  # original + max 2 retries (spec §8.1)
LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}

# Serializes background generation per role so concurrent clicks can never
# interleave deletes/inserts and multiply the question pool.
_role_locks: dict[int, asyncio.Lock] = {}


def _find_first_list(node, depth: int = 0):
    """First list found in a (possibly nested) dict, bounded to shallow depth."""
    if isinstance(node, list):
        return node
    if isinstance(node, dict) and depth < 3:
        for value in node.values():
            found = _find_first_list(value, depth + 1)
            if found is not None:
                return found
    return None


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences (``` or ```json)."""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_start(text: str) -> str:
    """Locate the first `[` or `{` and return everything from there.

    Some models prepend preamble text (e.g. "Here is the JSON:") before the
    actual payload despite explicit instructions.  This strips that prefix so
    ``json.loads`` does not choke on it.
    """
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            trimmed = text[i:]
            # Also strip trailing non-JSON text: find the last ] or } and
            # drop anything after it (e.g. "```\\nEnd text").
            for j in range(len(trimmed) - 1, -1, -1):
                if trimmed[j] in ("]", "}"):
                    return trimmed[: j + 1]
            return trimmed
    return text


def _try_literal_eval(text: str):
    """Fallback parser using ast.literal_eval for single-quoted Python literals.

    Some models output single-quoted strings (valid Python, invalid JSON).
    This safely parses that format as a last resort before giving up.
    """
    return ast.literal_eval(text)


def _parse_json(text: str):
    """Parse the raw model output as JSON, tolerating code fences.

    Some providers run in json_object mode, which forces a top-level object
    even when an array is requested (e.g. `{"questions": [...]}`). Unwrap the
    first list value found (also one level deeper, for nested wrappers like
    `{"lesson": {"sections": [...]}}`) so the validator sees the array.
    """
    cleaned = text.strip()
    cleaned = _strip_code_fences(cleaned)
    cleaned = _extract_json_start(cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _try_literal_eval(cleaned)
    if isinstance(parsed, list):
        # Unwrap superfluous outer array if model returned [[ [...], ... ]]
        while (
            len(parsed) == 1
            and isinstance(parsed[0], list)
            and (len(parsed[0]) == 0 or isinstance(parsed[0][0], list))
        ):
            parsed = parsed[0]
        return parsed
    if isinstance(parsed, dict):
        preferred = ("questions", "rows", "data", "items", "results", "placement_test")
        for key in preferred:
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        unwrapped = _find_first_list(parsed)
        if unwrapped is not None:
            return unwrapped
    raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")


def _log_usage(
    db: Session,
    generator: str,
    role_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    status: str,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    db.add(
        AiUsageLog(
            generator=generator,
            model=f"{provider}/{model}" if provider and model else (model or MODEL),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost_usd(prompt_tokens, completion_tokens, model=model),
            status=status,
            role_id=role_id,
        )
    )


def _record_rejected(
    db: Session,
    generator: str,
    role_id: int,
    input_preview: str,
    error: str,
    raw_response: str | None,
    validator_checks: dict | None,
) -> None:
    db.add(
        RejectedContent(
            generator=generator,
            role_id=role_id,
            input_preview=input_preview[:500],
            error=error[:500],
            raw_response=raw_response,
            validator_checks=validator_checks,
            status="pending",
        )
    )


def _insert_questions(db: Session, role_id: int, skill: str, rows: list) -> int:
    now = datetime.now(timezone.utc)
    for row in rows:
        _, level, statement, options_str, answer_letter, expanded_skill = row
        options = [str(o).strip() for o in options_str.split("|")]
        idx = LETTER_TO_INDEX.get(answer_letter)
        correct_answer = options[idx] if idx is not None and idx < len(options) else ""
        question_json = {
            "statement": statement,
            "options": options,
            "correct_answer": correct_answer,
        }
        db.add(
            PlacementTestQuestion(
                question=json.dumps(question_json, ensure_ascii=False),
                created_at=now,
                skill=skill,
                level=level,
                expanded_skill=expanded_skill,
                quiz_type_id=QUIZ_TYPE_ID,
                job_role_id=role_id,
            )
        )
    return len(rows)


# ─── Post-processing normalizers ──────────────────────────────────────────────
# LLMs frequently miscount when generating sequential groups (e.g. 21 topics
# instead of 20, or 7 lessons instead of 6).  These normalizers trim or adjust
# the output *before* validation so the validator always sees the correct count.

VALID_SKILLS_LIST = ["D_doc", "C_comm", "T_trouble", "G_custom"]
VALID_TIERS = ["tier_1", "tier_2"]
EXPECTED_LESSON_TIERS = ["basic", "basic", "intermediate", "intermediate", "advanced", "advanced"]


def _normalize_topic_outline(rows: list, baseline: dict) -> list:
    """Trim B1 output to exactly 20 topics with correct skill distribution.

    Strategy: remove excess topics from the most over-represented skill,
    preferring to drop topics from the END of each skill group (preserving
    the user's early topics).  If the count is already 20, return as-is.
    """
    NUM_TOPICS = 20
    if len(rows) == NUM_TOPICS:
        return rows

    # Build expected counts per skill
    expected = {s: baseline.get(s, 0) * NUM_TOPICS // 100 for s in VALID_SKILLS_LIST}

    if len(rows) < NUM_TOPICS:
        # Too few — rare, but return as-is; validator will report the error
        # and the retry prompt will ask for correction.
        logger.warning("B1 returned %d topics (expected %d); returning as-is", len(rows), NUM_TOPICS)
        return rows

    # len(rows) > NUM_TOPICS — trim excess
    excess = len(rows) - NUM_TOPICS
    logger.info("B1 returned %d topics; trimming %d excess", len(rows), excess)

    # Count current distribution
    counts = {s: 0 for s in VALID_SKILLS_LIST}
    for row in rows:
        if isinstance(row, list) and len(row) >= 2 and row[1] in counts:
            counts[row[1]] += 1

    # Calculate over-representation per skill (positive = has excess)
    over_rep = {s: counts[s] - expected.get(s, 0) for s in VALID_SKILLS_LIST}
    # Sort by most over-represented first
    over_skills = sorted(
        [s for s in VALID_SKILLS_LIST if over_rep[s] > 0],
        key=lambda s: over_rep[s],
        reverse=True,
    )

    trimmed = list(rows)
    for skill in over_skills:
        if excess <= 0:
            break
        # Find indices of topics for this skill (from the end, to preserve early ones)
        skill_indices = [
            i for i in range(len(trimmed) - 1, -1, -1)
            if isinstance(trimmed[i], list) and len(trimmed[i]) >= 2 and trimmed[i][1] == skill
        ]
        while skill_indices and excess > 0 and counts[skill] > expected.get(skill, 0):
            idx = skill_indices.pop(0)  # remove from end
            trimmed.pop(idx)
            counts[skill] -= 1
            excess -= 1

    # If still excess (all skills at expected but total still over), trim from
    # the skill with the most topics regardless
    if excess > 0:
        for skill in sorted(VALID_SKILLS_LIST, key=lambda s: counts[s], reverse=True):
            if excess <= 0:
                break
            skill_indices = [
                i for i in range(len(trimmed) - 1, -1, -1)
                if isinstance(trimmed[i], list) and len(trimmed[i]) >= 2 and trimmed[i][1] == skill
            ]
            while skill_indices and excess > 0:
                idx = skill_indices.pop(0)
                trimmed.pop(idx)
                counts[skill] -= 1
                excess -= 1

    logger.info("After normalization: %d topics, distribution: %s", len(trimmed), counts)
    return trimmed


def _normalize_lesson_shells(rows: list, topic_skill: str) -> list:
    """Trim B2 output to exactly 6 lessons while preserving tier ordering.

    Strategy: keep the first 6 rows (preserves basic→intermediate→advanced
    order).  If the count is already 6, return as-is.
    """
    NUM_LESSONS = 6
    if len(rows) == NUM_LESSONS:
        return rows

    if len(rows) > NUM_LESSONS:
        logger.info("B2 returned %d lessons; trimming to %d", len(rows), NUM_LESSONS)
        return rows[:NUM_LESSONS]

    # len(rows) < NUM_LESSONS — rare, return as-is; validator will report
    logger.warning("B2 returned %d lessons (expected %d); returning as-is", len(rows), NUM_LESSONS)
    return rows


async def _generate_skill_block(
    client: GeminiClientPool, role: JobRole, skill: str
) -> tuple:
    """
    Run Prompt A for one skill with retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_a(
        role=role.name,
        job_description=role.job_description,
        target_skill=skill,
        skill_definitions=role.skill_definitions or {},
        seed_tier_1=role.seed_tier_1,
        seed_tier_2=role.seed_tier_2,
    )

    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_a(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(call_prompt)
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
            rows = _parse_json(raw)
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

        result = validate_placement_block(rows, skill)
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
            return rows, usage_logs, None, last_raw, last_checks

        if result["errors"]:
            last_error = "; ".join(result["errors"][:3])
        else:
            # Soft band violation only: one targeted re-roll, but accept on the
            # final attempt (best-effort) so a borderline band never blocks a role.
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
        (last_error or f"Skill block '{skill}' failed"),
        last_raw,
        last_checks,
    )


async def generate_placement_for_role(role_id: int) -> dict:
    """Background job: generate 48 placement questions for a role (Generator A)."""
    lock = _role_locks.setdefault(role_id, asyncio.Lock())
    async with lock:
        db = SessionLocal()
        gen: RoleGeneration | None = None
        try:
            role = db.query(JobRole).filter(JobRole.id == role_id).first()
            if role is None:
                return {"status": "failed", "error": "role not found"}

            # The in_progress row is reserved synchronously by kickoff_generation.
            # Reuse it; fall back to creating one if it was never persisted.
            gen = (
                db.query(RoleGeneration)
                .filter(
                    RoleGeneration.role_id == role_id,
                    RoleGeneration.status == "in_progress",
                )
                .order_by(RoleGeneration.id.desc())
                .first()
            )
            if gen is None:
                gen = RoleGeneration(
                    role_id=role_id,
                    status="in_progress",
                    step="a",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(gen)
                db.commit()
                db.refresh(gen)

            # Belt & braces: another run for this role must not be active.
            active = (
                db.query(RoleGeneration)
                .filter(
                    RoleGeneration.role_id == role_id,
                    RoleGeneration.status.in_(["in_progress", "pending"]),
                    RoleGeneration.id != gen.id,
                )
                .first()
            )
            if active is not None:
                gen.status = "failed"
                gen.error_message = "Superseded by another generation run"
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": gen.error_message}

            try:
                assert_generation_enabled(db)
            except KillSwitchError as exc:
                gen.status = "failed"
                gen.step = "a"
                gen.error_message = str(exc)
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": str(exc)}

            client = GeminiClientPool()
            total_count = 0
            total_errors = 0

            # Idempotent: delete the role's existing placement pool before
            # re-inserting. Guarded at kickoff, but fail cleanly (never hang)
            # if learner answers still reference these questions.
            try:
                db.query(PlacementTestQuestion).filter(
                    PlacementTestQuestion.job_role_id == role_id
                ).delete()
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                gen.status = "failed"
                gen.error_message = (
                    "Cannot regenerate: existing learner answers reference these "
                    f"questions ({exc.orig})"
                )
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": gen.error_message}

            for skill in SKILLS:
                try:
                    (
                        rows,
                        usage_logs,
                        error,
                        raw_resp,
                        val_checks,
                    ) = await _generate_skill_block(client, role, skill)
                except (GenerationError, KillSwitchError) as exc:
                    rows, usage_logs, error, raw_resp, val_checks = (
                        None,
                        [],
                        str(exc),
                        None,
                        None,
                    )

                for log in usage_logs:
                    _log_usage(
                        db,
                        "A",
                        role_id,
                        log["prompt_tokens"],
                        log["completion_tokens"],
                        log["status"],
                        log.get("provider"),
                        log.get("model"),
                    )

                if rows is not None:
                    count = _insert_questions(db, role_id, skill, rows)
                    total_count += count
                    db.commit()
                else:
                    total_errors += 1
                    _record_rejected(
                        db,
                        "A",
                        role_id,
                        f"role={role.name}, skill={skill}",
                        error or "unknown",
                        raw_resp,
                        val_checks,
                    )
                    _log_usage(db, "A", role_id, 0, 0, "rejected")
                    db.commit()

            gen.status = "completed" if total_errors == 0 else "failed"
            gen.step = "a"
            gen.step_a_count = total_count
            gen.step_a_errors = total_errors
            gen.finished_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(
                "Generator A finished for role %s: %s questions, %s errors",
                role_id,
                total_count,
                total_errors,
            )
            return {"status": gen.status, "count": total_count, "errors": total_errors}
        except Exception as exc:
            logger.exception("Generator A crashed for role %s", role_id)
            if gen is not None:
                db.rollback()
                _record_rejected(
                    db, "A", role_id, f"role={role.name}", str(exc), None, None
                )
                _log_usage(db, "A", role_id, 0, 0, "rejected")
                gen.status = "failed"
                gen.error_message = str(exc)[:500]
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()


# ─── Generator B (B1: Topic Outline, B2: Lesson Shells) ─────────────────────


async def _generate_topic_outline(client: GeminiClientPool, role: JobRole) -> tuple:
    """
    Run Prompt B-1 for a role with retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_b1(
        role=role.name,
        job_description=role.job_description,
        skill_definitions=role.skill_definitions or {},
        seed_tier_1=role.seed_tier_1,
        seed_tier_2=role.seed_tier_2,
        baseline=role.baseline or {},
    )

    usage_logs: list[dict] = []
    last_error = ""
    baseline = role.baseline or {}
    last_raw: str | None = None
    last_checks: dict | None = None

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_b1(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(call_prompt)
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
            rows = _parse_json(raw)
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

        rows = _normalize_topic_outline(rows, baseline)
        result = validate_topic_outline(rows, baseline)
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
            return rows, usage_logs, None, last_raw, last_checks

        if result["errors"]:
            last_error = "; ".join(result["errors"][:3])
        else:
            # Soft tier-split warning only: accept on the final attempt
            # (best-effort) so a borderline split never blocks a role.
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
        (last_error or "Topic outline generation failed"),
        last_raw,
        last_checks,
    )


async def _generate_lesson_shells(
    client: GeminiClientPool, role: JobRole, topic: Topic
) -> tuple:
    """
    Run Prompt B-2 for one topic with retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_b2(
        role=role.name,
        topic_name=topic.name,
        topic_skill=topic.primary_skill,
        skill_definitions=role.skill_definitions or {},
    )

    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_b2(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(call_prompt)
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
            rows = _parse_json(raw)
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

        rows = _normalize_lesson_shells(rows, topic.primary_skill)
        result = validate_lesson_shells(rows, topic.primary_skill)
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
            return rows, usage_logs, None, last_raw, last_checks

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
        (last_error or "Lesson shells generation failed"),
        last_raw,
        last_checks,
    )


def _insert_topics(db: Session, role_id: int, rows: list) -> int:
    for i, row in enumerate(rows):
        name, skill, tier = row
        db.add(
            Topic(
                role_id=role_id,
                name=name,
                primary_skill=skill,
                seed_tier=tier,
                sort_order=i,
            )
        )
    return len(rows)


def _insert_lesson_shells(db: Session, topic_id: int, rows: list) -> int:
    for row in rows:
        title, skill, tier = row
        db.add(
            Lesson(
                topic_id=topic_id,
                title=title,
                primary_skill=skill,
                difficulty_tier=tier,
                estimated_minutes=None,
                theory_content=None,
                quiz_content=None,
                is_generated=False,
            )
        )
    return len(rows)


async def generate_course_for_role(role_id: int) -> dict:
    """Background job: generate 20 topics + 120 lesson shells for a role (B1+B2)."""
    lock = _role_locks.setdefault(role_id, asyncio.Lock())
    async with lock:
        db = SessionLocal()
        gen: RoleGeneration | None = None
        try:
            role = db.query(JobRole).filter(JobRole.id == role_id).first()
            if role is None:
                return {"status": "failed", "error": "role not found"}

            # The in_progress row is reserved synchronously by kickoff_course_generation.
            gen = (
                db.query(RoleGeneration)
                .filter(
                    RoleGeneration.role_id == role_id,
                    RoleGeneration.status == "in_progress",
                )
                .order_by(RoleGeneration.id.desc())
                .first()
            )
            if gen is None:
                gen = RoleGeneration(
                    role_id=role_id,
                    status="in_progress",
                    step="b1",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(gen)
                db.commit()
                db.refresh(gen)

            # Belt & braces: another run for this role must not be active.
            active = (
                db.query(RoleGeneration)
                .filter(
                    RoleGeneration.role_id == role_id,
                    RoleGeneration.status.in_(["in_progress", "pending"]),
                    RoleGeneration.id != gen.id,
                )
                .first()
            )
            if active is not None:
                gen.status = "failed"
                gen.error_message = "Superseded by another generation run"
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": gen.error_message}

            try:
                assert_generation_enabled(db)
            except KillSwitchError as exc:
                gen.status = "failed"
                gen.step = "b1"
                gen.error_message = str(exc)
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": str(exc)}

            client = GeminiClientPool()

            # Guard against the kickoff-then-enroll race (docs/07 deviation #23):
            # a learner could complete the placement test after the synchronous
            # kickoff gate passed but before this job deletes the topics, which
            # would cascade-wipe their fresh roadmap. Re-check here and abort.
            active_learners = (
                db.query(User)
                .filter(
                    User.job_role_id == role_id,
                    User.learning_status == LEARNING_ENROLLED,
                )
                .count()
            )
            if active_learners > 0:
                gen.status = "failed"
                gen.error_message = (
                    f"{active_learners} active learner(s) enrolled on this role. "
                    "Reset learners before regenerating the course outline."
                )
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": gen.error_message}

            # Idempotent: delete the role's existing topics (lessons cascade).
            try:
                db.query(Topic).filter(Topic.role_id == role_id).delete()
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                gen.status = "failed"
                gen.error_message = f"Cannot regenerate course outline: {exc.orig}"
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": gen.error_message}

            # ── B-1: 20 topics ──────────────────────────────────────────────
            gen.step = "b1"
            db.commit()
            (
                topic_rows,
                usage_logs,
                b1_error,
                b1_raw,
                b1_checks,
            ) = await _generate_topic_outline(client, role)
            for log in usage_logs:
                _log_usage(
                    db,
                    "B1",
                    role_id,
                    log["prompt_tokens"],
                    log["completion_tokens"],
                    log["status"],
                    log.get("provider"),
                    log.get("model"),
                )

            topics: list[Topic] = []
            if topic_rows is not None:
                _insert_topics(db, role_id, topic_rows)
                db.commit()
                topics = (
                    db.query(Topic)
                    .filter(Topic.role_id == role_id)
                    .order_by(Topic.sort_order.asc())
                    .all()
                )
                gen.step_b1_count = len(topics)
                gen.step_b1_errors = 0
            else:
                gen.step_b1_count = 0
                gen.step_b1_errors = 1
                _record_rejected(
                    db,
                    "B1",
                    role_id,
                    f"role={role.name}",
                    b1_error or "unknown",
                    b1_raw,
                    b1_checks,
                )
                _log_usage(db, "B1", role_id, 0, 0, "rejected")
                db.commit()

            # ── B-2: 6 lesson shells per topic ──────────────────────────────
            b2_count = 0
            b2_errors = 0
            if topics:
                for topic in topics:
                    gen.step = "b2"
                    db.commit()
                    (
                        shell_rows,
                        usage_logs,
                        b2_error,
                        b2_raw,
                        b2_checks,
                    ) = await _generate_lesson_shells(client, role, topic)
                    for log in usage_logs:
                        _log_usage(
                            db,
                            "B2",
                            role_id,
                            log["prompt_tokens"],
                            log["completion_tokens"],
                            log["status"],
                            log.get("provider"),
                            log.get("model"),
                        )
                    if shell_rows is not None:
                        b2_count += _insert_lesson_shells(db, topic.id, shell_rows)
                        db.commit()
                    else:
                        b2_errors += 1
                        _record_rejected(
                            db,
                            "B2",
                            role_id,
                            f"role={role.name}, topic={topic.name}",
                            b2_error or "unknown",
                            b2_raw,
                            b2_checks,
                        )
                        _log_usage(db, "B2", role_id, 0, 0, "rejected")
                        db.commit()

            gen.step_b2_count = b2_count
            gen.step_b2_errors = b2_errors
            total_errors = gen.step_b1_errors + b2_errors
            gen.status = "completed" if total_errors == 0 else "failed"
            gen.step = "b2" if (topics or b2_count) else "b1"
            gen.finished_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(
                "Generator B finished for role %s: %s topics, %s lessons, %s errors",
                role_id,
                gen.step_b1_count,
                b2_count,
                total_errors,
            )
            return {
                "status": gen.status,
                "topics": gen.step_b1_count,
                "lessons": b2_count,
                "errors": total_errors,
            }
        except Exception as exc:
            logger.exception("Generator B crashed for role %s", role_id)
            if gen is not None:
                db.rollback()
                _record_rejected(
                    db, "B1", role_id, f"role={role.name}", str(exc), None, None
                )
                _log_usage(db, "B1", role_id, 0, 0, "rejected")
                gen.status = "failed"
                gen.error_message = str(exc)[:500]
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()


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
_lesson_locks: dict[int, asyncio.Lock] = {}

C1_MAX_OUTPUT_TOKENS = 8192
C2_MAX_OUTPUT_TOKENS = 4096
C2_TEMPERATURE = 0.15


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


async def _generate_lesson_theory(
    client: GeminiClientPool, role: JobRole, topic: Topic, lesson: Lesson
) -> tuple:
    """
    Run Prompt C-1 (8-section theory) for one lesson with retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_c1(
        role=role.name,
        job_description=role.job_description,
        parent_topic=topic.name,
        lesson_title=lesson.title,
        primary_skill=lesson.primary_skill,
        difficulty_tier=lesson.difficulty_tier,
        skill_definitions=role.skill_definitions or {},
    )

    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_c1(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(
                call_prompt,
                max_output_tokens=C1_MAX_OUTPUT_TOKENS,
                model=app_config.GEMINI_PRO_MODEL,
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
            rows = _parse_json(raw)
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

        result = validate_theory_content(rows)
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
            return rows, usage_logs, None, last_raw, last_checks

        if result["errors"]:
            last_error = "; ".join(result["errors"][:3])
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

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_c2(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(
                call_prompt,
                temperature=C2_TEMPERATURE,
                max_output_tokens=C2_MAX_OUTPUT_TOKENS,
                model=app_config.GEMINI_PRO_MODEL,
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


async def generate_lesson_content(lesson_id: int, *, force: bool = False) -> dict:
    """Lazily generate a lesson's theory (C-1) + quiz (C-2), in that order.

    - Skips silently when the lesson is already generated (role-scoped cache).
    - `force=True` clears theory/quiz and regenerates (~$0.05 per rerun).
    - Per-lesson lock; usage/rejected/cost plumbing identical to Generators A/B.
    """
    lock = _lesson_locks.setdefault(lesson_id, asyncio.Lock())
    async with lock:
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

            if force:
                lesson.theory_content = None
                lesson.quiz_content = None
                lesson.estimated_minutes = None
                lesson.is_generated = False
                db.commit()

            if lesson.is_generated:
                return {
                    "status": "skipped",
                    "message": "lesson already generated (shared — reused by all learners of this role)",
                }

            try:
                assert_generation_enabled(db)
            except KillSwitchError as exc:
                return {"status": "failed", "error": str(exc)}

            client = GeminiClientPool()

            # ── C-1: theory ──────────────────────────────────────────────────
            (
                theory,
                theory_usage,
                theory_error,
                c1_raw,
                c1_checks,
            ) = await _generate_lesson_theory(client, role, topic, lesson)
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
            if theory is None:
                _record_rejected(
                    db,
                    "C1",
                    role_id,
                    f"lesson={lesson.title}",
                    theory_error or "unknown",
                    c1_raw,
                    c1_checks,
                )
                _log_usage(db, "C1", role_id, 0, 0, "rejected")
                db.commit()
                return {"status": "failed", "error": theory_error or "C-1 failed"}

            # ── C-2: quiz (grounded in the generated theory) ─────────────────
            (
                quiz,
                quiz_usage,
                quiz_error,
                c2_raw,
                c2_checks,
            ) = await _generate_lesson_quiz(client, role, topic, lesson, theory)
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
            if quiz is None:
                _record_rejected(
                    db,
                    "C2",
                    role_id,
                    f"lesson={lesson.title}",
                    quiz_error or "unknown",
                    c2_raw,
                    c2_checks,
                )
                _log_usage(db, "C2", role_id, 0, 0, "rejected")
                db.commit()
                return {"status": "failed", "error": quiz_error or "C-2 failed"}

            lesson.theory_content = theory
            lesson.quiz_content = quiz
            lesson.estimated_minutes = estimate_lesson_duration(theory, quiz)
            lesson.is_generated = True
            db.commit()

            assigned_user_ids = [
                int(row.user_id)
                for row in db.query(UserRoadmap.user_id)
                .filter(UserRoadmap.topic_id == lesson.topic_id)
                .distinct()
                .all()
            ]
            await notification_stream_broker.publish_many(
                assigned_user_ids,
                {
                    "type": "roadmap_updated",
                    "reason": "lesson_generated",
                    "lesson_id": int(lesson_id),
                    "topic_id": int(lesson.topic_id),
                },
            )

            logger.info(
                "Generator C finished for lesson %s (role %s)", lesson_id, role_id
            )
            return {"status": "completed", "message": "lesson generated (C1 + C2)"}
        except Exception as exc:
            logger.exception("Generator C crashed for lesson %s", lesson_id)
            db.rollback()
            _record_rejected(
                db, "C1", role_id, f"lesson={lesson.title}", str(exc), None, None
            )
            _log_usage(db, "C1", role_id, 0, 0, "rejected")
            db.commit()
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()
