"""Generator A — Placement Test question generation pipeline.

Orchestrates Flash calls per skill, validates against spec §9, inserts
48 placement questions per role. Idempotent, retries max 2.

Extracted from generation.py for single-responsibility.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError
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
    _parse_json,
    _log_usage,
    _record_rejected,
    MODEL,
    MAX_ATTEMPTS,
    LETTER_TO_INDEX,
    MAX_PLACEMENT_OUTPUT_TOKENS,
    logger,
)
from app.core.ai.dispatch.prompts import (
    SKILLS,
    build_prompt_a,
    retry_prompt_a,
)
from app.core.ai.dispatch.validators import validate_placement_block
from app.core.infra.config import app_config
from app.core.infra.database import SessionLocal
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent

# Serializes background generation per role
_role_locks = KeyedMutex()

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
EXPECTED_LESSON_TIERS = app_config.LESSON_TIER_ORDER


def _normalize_topic_outline(rows: list, baseline: dict) -> list:
    """Trim B1 output to exactly 20 topics with correct skill distribution.

    Strategy: remove excess topics from the most over-represented skill,
    preferring to drop topics from the END of each skill group (preserving
    the user's early topics).  If the count is already 20, return as-is.
    """
    NUM_TOPICS = app_config.NUM_TOPICS_PER_ROLE
    if len(rows) == NUM_TOPICS:
        return rows

    # Build expected counts per skill
    expected = {s: baseline.get(s, 0) * NUM_TOPICS // 100 for s in VALID_SKILLS_LIST}

    if len(rows) < NUM_TOPICS:
        # Too few — rare, but return as-is; validator will report the error
        # and the retry prompt will ask for correction.
        logger.warning(
            "B1 returned %d topics (expected %d); returning as-is",
            len(rows),
            NUM_TOPICS,
        )
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
            i
            for i in range(len(trimmed) - 1, -1, -1)
            if isinstance(trimmed[i], list)
            and len(trimmed[i]) >= 2
            and trimmed[i][1] == skill
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
                i
                for i in range(len(trimmed) - 1, -1, -1)
                if isinstance(trimmed[i], list)
                and len(trimmed[i]) >= 2
                and trimmed[i][1] == skill
            ]
            while skill_indices and excess > 0:
                idx = skill_indices.pop(0)
                trimmed.pop(idx)
                counts[skill] -= 1
                excess -= 1

    logger.info(
        "After normalization: %d topics, distribution: %s", len(trimmed), counts
    )
    return trimmed


def _normalize_lesson_shells(rows: list, topic_skill: str) -> list:
    """Trim B2 output to exactly 6 lessons while preserving tier ordering.

    Strategy: keep the first 6 rows (preserves basic→intermediate→advanced
    order).  If the count is already 6, return as-is.
    """
    NUM_LESSONS = app_config.NUM_LESSONS_PER_TOPIC
    if len(rows) == NUM_LESSONS:
        return rows

    if len(rows) > NUM_LESSONS:
        logger.info("B2 returned %d lessons; trimming to %d", len(rows), NUM_LESSONS)
        return rows[:NUM_LESSONS]

    # len(rows) < NUM_LESSONS — rare, return as-is; validator will report
    logger.warning(
        "B2 returned %d lessons (expected %d); returning as-is", len(rows), NUM_LESSONS
    )
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
            response: LLMResponse = await client.generate_json(
                call_prompt,
                allowed_providers=["google", "mistral"],
                max_output_tokens=MAX_PLACEMENT_OUTPUT_TOKENS,
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
    async with _role_locks.lock(role_id):
        role_info: dict | None = None
        gen_id: int | None = None
        db = SessionLocal()
        try:
            role = db.query(JobRole).filter(JobRole.id == role_id).first()
            if role is None:
                return {"status": "failed", "error": "role not found"}

            role_info = {
                "id": role.id,
                "name": role.name,
                "job_description": role.job_description,
                "skill_definitions": role.skill_definitions or {},
                "seed_tier_1": role.seed_tier_1,
                "seed_tier_2": role.seed_tier_2,
                "baseline": role.baseline or {},
            }

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
            gen_id = gen.id

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
        finally:
            db.close()

        role_ctx = SimpleNamespace(**role_info)
        client = get_gemini_client_pool()
        total_count = 0
        total_errors = 0

        try:
            for skill in SKILLS:
                try:
                    (
                        rows,
                        usage_logs,
                        error,
                        raw_resp,
                        val_checks,
                    ) = await _generate_skill_block(client, role_ctx, skill)
                except (GenerationError, KillSwitchError) as exc:
                    rows, usage_logs, error, raw_resp, val_checks = (
                        None,
                        [],
                        str(exc),
                        None,
                        None,
                    )

                # Persist skill block in a short-lived DB session
                db = SessionLocal()
                try:
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
                    else:
                        total_errors += 1
                        _record_rejected(
                            db,
                            "A",
                            role_id,
                            f"role={role_info['name']}, skill={skill}",
                            error or "unknown",
                            raw_resp,
                            val_checks,
                        )
                        _log_usage(db, "A", role_id, 0, 0, "rejected")
                    db.commit()
                finally:
                    db.close()

            status_val = "completed" if total_errors == 0 else "failed"
            db = SessionLocal()
            try:
                gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                if gen:
                    gen.status = status_val
                    gen.step = "a"
                    gen.step_a_count = total_count
                    gen.step_a_errors = total_errors
                    gen.finished_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()

            logger.info(
                "Generator A finished for role %s: %s questions, %s errors",
                role_id,
                total_count,
                total_errors,
            )
            return {"status": status_val, "count": total_count, "errors": total_errors}
        except Exception as exc:
            logger.exception("Generator A crashed for role %s", role_id)
            if gen_id is not None:
                role_label = role_info["name"] if role_info else f"id={role_id}"
                db = SessionLocal()
                try:
                    _record_rejected(
                        db, "A", role_id, f"role={role_label}", str(exc), None, None
                    )
                    _log_usage(db, "A", role_id, 0, 0, "rejected")
                    gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                    if gen:
                        gen.status = "failed"
                        gen.error_message = str(exc)[:500]
                        gen.finished_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()
            return {"status": "failed", "error": str(exc)}

