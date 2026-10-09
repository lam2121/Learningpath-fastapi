"""Generator B — Course Outline generation pipeline (B1: Topics + B2: Lesson Shells).

Generates 20 topics per role then 6 lesson shells per topic.
Same retry/logging/rejection conventions as Generator A.

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
    logger,
)
from app.core.ai.dispatch.prompts import (
    SKILLS,
    build_prompt_b1,
    build_prompt_b1_more,
    build_prompt_b2,
    retry_prompt_b1,
    retry_prompt_b2,
)
from app.core.ai.dispatch.validators import (
    validate_lesson_shells,
    validate_more_topics,
    validate_topic_outline,
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
from app.models.user import LEARNING_ENROLLED, User
from app.models.user_roadmap import UserRoadmap

# Serializes background generation per role
_role_locks = KeyedMutex()

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
            response: LLMResponse = await client.generate_json(
                call_prompt, allowed_providers=["google", "mistral"]
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
            response: LLMResponse = await client.generate_json(
                call_prompt, allowed_providers=["google", "mistral"]
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


async def generate_course_for_role(role_id: int, resume: bool = False) -> dict:
    """Background job: generate 20 topics + 120 lesson shells for a role (B1+B2).

    `resume=True` (docs/07 deviation #28) picks up a failed/partial run without
    re-rolling the outline: any topics that already exist are kept, Prompt B-1 is
    skipped, and Prompt B-2 is re-run only for topics that do not yet have their
    full 6-shell set (partial leftovers from an interrupted run are cleared first).
    Topics that already carry >= 6 shells are left untouched. If no topics exist,
    resume degrades to exactly the full B-1+B-2 path.
    """
    async with _role_locks.lock(role_id):
        role_info: dict | None = None
        gen_id: int | None = None
        existing_topics_data: list[dict] = []
        is_resume_mode: bool = False

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
                gen.step = "b1"
                gen.error_message = str(exc)
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": str(exc)}

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

            # ── Resume vs full regeneration ─────────────────────────────────
            # Resume keeps whatever topics already exist (B-1 is NOT re-run) and
            # only repairs missing lesson shells in the B-2 loop below. A full
            # run first wipes the role's topics (lessons cascade) and re-runs
            # B-1 from scratch.
            existing_topics = (
                db.query(Topic)
                .filter(Topic.role_id == role_id)
                .order_by(Topic.sort_order.asc())
                .all()
            )
            if resume and existing_topics:
                is_resume_mode = True
                existing_topics_data = [
                    {
                        "id": t.id,
                        "name": t.name,
                        "primary_skill": t.primary_skill,
                        "seed_tier": t.seed_tier,
                    }
                    for t in existing_topics
                ]
                gen.step = "b2"
                gen.step_b1_count = len(existing_topics)
                gen.step_b1_errors = 0
                db.commit()
            else:
                if existing_topics:
                    # Idempotent: delete the role's existing topics (lessons cascade).
                    try:
                        db.query(Topic).filter(Topic.role_id == role_id).delete()
                        db.commit()
                    except IntegrityError as exc:
                        db.rollback()
                        gen.status = "failed"
                        gen.error_message = (
                            f"Cannot regenerate course outline: {exc.orig}"
                        )
                        gen.finished_at = datetime.now(timezone.utc)
                        db.commit()
                        return {"status": "failed", "error": gen.error_message}

                gen.step = "b1"
                db.commit()
        finally:
            db.close()

        role_ctx = SimpleNamespace(**role_info)
        client = get_gemini_client_pool()

        try:
            topics_data: list[dict] = []
            step_b1_count = 0
            step_b1_errors = 0

            if is_resume_mode:
                topics_data = existing_topics_data
                step_b1_count = len(topics_data)
                step_b1_errors = 0
            else:
                # ── B-1: 20 topics (runs async without DB connection) ────────
                (
                    topic_rows,
                    usage_logs,
                    b1_error,
                    b1_raw,
                    b1_checks,
                ) = await _generate_topic_outline(client, role_ctx)

                db = SessionLocal()
                try:
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

                    if topic_rows is not None:
                        _insert_topics(db, role_id, topic_rows)
                        db.commit()
                        inserted = (
                            db.query(Topic)
                            .filter(Topic.role_id == role_id)
                            .order_by(Topic.sort_order.asc())
                            .all()
                        )
                        topics_data = [
                            {
                                "id": t.id,
                                "name": t.name,
                                "primary_skill": t.primary_skill,
                                "seed_tier": t.seed_tier,
                            }
                            for t in inserted
                        ]
                        step_b1_count = len(topics_data)
                        step_b1_errors = 0
                    else:
                        step_b1_count = 0
                        step_b1_errors = 1
                        _record_rejected(
                            db,
                            "B1",
                            role_id,
                            f"role={role_info['name']}",
                            b1_error or "unknown",
                            b1_raw,
                            b1_checks,
                        )
                        _log_usage(db, "B1", role_id, 0, 0, "rejected")
                        db.commit()

                    gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                    if gen:
                        gen.step_b1_count = step_b1_count
                        gen.step_b1_errors = step_b1_errors
                        db.commit()
                finally:
                    db.close()

            # ── B-2: 6 lesson shells per topic ──────────────────────────────
            b2_count = 0
            b2_errors = 0
            if topics_data:
                for topic_dict in topics_data:
                    topic_ctx = SimpleNamespace(**topic_dict)
                    topic_id = topic_dict["id"]

                    if is_resume_mode:
                        db = SessionLocal()
                        try:
                            existing_count = (
                                db.query(Lesson).filter(Lesson.topic_id == topic_id).count()
                            )
                            if existing_count >= 6:
                                b2_count += existing_count
                                continue
                            db.query(Lesson).filter(Lesson.topic_id == topic_id).delete()
                            db.commit()
                        finally:
                            db.close()

                    db = SessionLocal()
                    try:
                        gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                        if gen:
                            gen.step = "b2"
                            db.commit()
                    finally:
                        db.close()

                    (
                        shell_rows,
                        usage_logs,
                        b2_error,
                        b2_raw,
                        b2_checks,
                    ) = await _generate_lesson_shells(client, role_ctx, topic_ctx)

                    db = SessionLocal()
                    try:
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
                            b2_count += _insert_lesson_shells(db, topic_id, shell_rows)
                            db.commit()
                        else:
                            b2_errors += 1
                            _record_rejected(
                                db,
                                "B2",
                                role_id,
                                f"role={role_info['name']}, topic={topic_dict['name']}",
                                b2_error or "unknown",
                                b2_raw,
                                b2_checks,
                            )
                            _log_usage(db, "B2", role_id, 0, 0, "rejected")
                            db.commit()
                    finally:
                        db.close()

            total_errors = step_b1_errors + b2_errors
            status_val = "completed" if total_errors == 0 else "failed"
            db = SessionLocal()
            try:
                gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                if gen:
                    gen.step_b2_count = b2_count
                    gen.step_b2_errors = b2_errors
                    gen.status = status_val
                    gen.step = "b2" if (topics_data or b2_count) else "b1"
                    gen.finished_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()

            logger.info(
                "Generator B finished for role %s: %s topics, %s lessons, %s errors",
                role_id,
                step_b1_count,
                b2_count,
                total_errors,
            )
            return {
                "status": status_val,
                "topics": step_b1_count,
                "lessons": b2_count,
                "errors": total_errors,
            }
        except Exception as exc:
            logger.exception("Generator B crashed for role %s", role_id)
            if gen_id is not None:
                role_label = role_info["name"] if role_info else f"id={role_id}"
                db = SessionLocal()
                try:
                    _record_rejected(
                        db, "B1", role_id, f"role={role_label}", str(exc), None, None
                    )
                    _log_usage(db, "B1", role_id, 0, 0, "rejected")
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


# ─── Generator B (extension): more topics for one skill ─────────────────────


async def _generate_more_topics(
    client: GeminiClientPool,
    role: JobRole,
    skill: str,
    count: int,
    existing_topics: list[tuple[str, str]],
) -> tuple:
    """
    Run the B-1 extension prompt (`count` extra topics for one skill) with
    retries. Returns
    (rows | None, usage_logs, error | None, raw_response | None, validator_checks | None).
    """
    prompt = build_prompt_b1_more(
        role=role.name,
        job_description=role.job_description,
        skill_definitions=role.skill_definitions or {},
        seed_tier_1=role.seed_tier_1,
        seed_tier_2=role.seed_tier_2,
        skill=skill,
        count=count,
        existing_topics=existing_topics,
    )
    usage_logs: list[dict] = []
    last_error = ""
    last_raw: str | None = None
    last_checks: dict | None = None

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_b1(prompt, last_error)
        try:
            response: LLMResponse = await client.generate_json(
                call_prompt, allowed_providers=["google", "mistral"]
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

        # LLMs frequently over-count; keep the first `count` rows.
        if len(rows) > count:
            logger.info("B1 (more) returned %d topics; trimming to %d", len(rows), count)
            rows = rows[:count]
        result = validate_more_topics(rows, skill, count, existing_topics)
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
            # Soft opening-word warning only: accept on the final attempt
            # (best-effort) so look-alike names never block a run.
            last_error = "; ".join(result["warnings"][:3])
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
        (last_error or "More-topics generation failed"),
        last_raw,
        last_checks,
    )


async def generate_more_topics_for_role(role_id: int, skill: str, count: int) -> dict:
    """Background job: extend a role's outline with `count` topics of one skill.

    Additive counterpart of `generate_course_for_role`: nothing is deleted, so
    there is no active-learner gate — existing `user_roadmap` rows keep pointing
    at their topics and the new ones only join the pool for later roadmaps.

    Each new topic is committed together with its 6 lesson shells (B-2), so a
    failed run never leaves a topic without lessons. The run's B1/B2 counters
    hold the role's totals (like resume mode), not just the added rows.
    """
    async with _role_locks.lock(role_id):
        role_info: dict | None = None
        gen_id: int | None = None
        existing_topics: list[tuple[str, str]] = []
        next_sort_order = 0
        topics_total = 0
        lessons_total = 0

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

            # The in_progress row is reserved synchronously by kickoff_more_topics_generation.
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
                gen.step = "b1"
                gen.error_message = str(exc)
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "failed", "error": str(exc)}

            topics = (
                db.query(Topic)
                .filter(Topic.role_id == role_id)
                .order_by(Topic.sort_order.asc())
                .all()
            )
            existing_topics = [(t.name, t.primary_skill) for t in topics]
            next_sort_order = max((t.sort_order for t in topics), default=-1) + 1
            topics_total = len(topics)
            lessons_total = (
                db.query(Lesson)
                .join(Topic, Lesson.topic_id == Topic.id)
                .filter(Topic.role_id == role_id)
                .count()
            )

            gen.step = "b1"
            gen.step_b1_count = topics_total
            gen.step_b2_count = lessons_total
            db.commit()
        finally:
            db.close()

        role_ctx = SimpleNamespace(**role_info)
        client = get_gemini_client_pool()

        try:
            # ── B-1 (more): `count` topic titles for the chosen skill ────────
            (
                topic_rows,
                usage_logs,
                b1_error,
                b1_raw,
                b1_checks,
            ) = await _generate_more_topics(
                client, role_ctx, skill, count, existing_topics
            )

            db = SessionLocal()
            try:
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
                if topic_rows is None:
                    _record_rejected(
                        db,
                        "B1",
                        role_id,
                        f"role={role_info['name']}, more topics: skill={skill}, count={count}",
                        b1_error or "unknown",
                        b1_raw,
                        b1_checks,
                    )
                    _log_usage(db, "B1", role_id, 0, 0, "rejected")

                gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                if gen:
                    if topic_rows is None:
                        gen.step_b1_errors = 1
                        gen.status = "failed"
                        gen.error_message = (
                            f"Could not generate new topics: {b1_error or 'unknown'}"
                        )[:500]
                        gen.finished_at = datetime.now(timezone.utc)
                    else:
                        gen.step = "b2"
                db.commit()
            finally:
                db.close()

            if topic_rows is None:
                return {"status": "failed", "error": b1_error}

            # ── B-2: 6 lesson shells per new topic, saved with the topic ─────
            added = 0
            b2_errors = 0
            for name, _, tier in topic_rows:
                name = name.strip()
                topic_ctx = SimpleNamespace(name=name, primary_skill=skill)

                (
                    shell_rows,
                    usage_logs,
                    b2_error,
                    b2_raw,
                    b2_checks,
                ) = await _generate_lesson_shells(client, role_ctx, topic_ctx)

                db = SessionLocal()
                try:
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
                        topic = Topic(
                            role_id=role_id,
                            name=name,
                            primary_skill=skill,
                            seed_tier=tier,
                            sort_order=next_sort_order + added,
                        )
                        db.add(topic)
                        db.flush()
                        lessons_total += _insert_lesson_shells(db, topic.id, shell_rows)
                        topics_total += 1
                        added += 1
                    else:
                        b2_errors += 1
                        _record_rejected(
                            db,
                            "B2",
                            role_id,
                            f"role={role_info['name']}, topic={name}",
                            b2_error or "unknown",
                            b2_raw,
                            b2_checks,
                        )
                        _log_usage(db, "B2", role_id, 0, 0, "rejected")

                    gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                    if gen:
                        gen.step_b1_count = topics_total
                        gen.step_b2_count = lessons_total
                        gen.step_b2_errors = b2_errors
                    db.commit()
                finally:
                    db.close()

            status_val = "completed" if b2_errors == 0 else "failed"
            db = SessionLocal()
            try:
                gen = db.query(RoleGeneration).filter(RoleGeneration.id == gen_id).first()
                if gen:
                    gen.status = status_val
                    if b2_errors:
                        gen.error_message = (
                            f"Added {added} of {len(topic_rows)} topics ({skill}); "
                            f"{b2_errors} failed lesson-shell generation."
                        )
                    gen.finished_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()

            logger.info(
                "Generator B (more topics) finished for role %s: +%s topics (%s), %s errors",
                role_id,
                added,
                skill,
                b2_errors,
            )
            return {
                "status": status_val,
                "topics": added,
                "lessons": added * app_config.NUM_LESSONS_PER_TOPIC,
                "errors": b2_errors,
            }
        except Exception as exc:
            logger.exception("Generator B (more topics) crashed for role %s", role_id)
            if gen_id is not None:
                role_label = role_info["name"] if role_info else f"id={role_id}"
                db = SessionLocal()
                try:
                    _record_rejected(
                        db, "B1", role_id, f"role={role_label}", str(exc), None, None
                    )
                    _log_usage(db, "B1", role_id, 0, 0, "rejected")
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


