"""Generator A (Placement Test) orchestrator.

Runs 4 Flash calls (one per skill) -> validates each block against spec §9
-> inserts 48 placement questions per role. Idempotent, retries max 2,
logs every call to ai_usage_log, records rejections, tracks role_generation.
"""

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
from app.core.ai.prompts import SKILLS, build_prompt_a, retry_prompt_a
from app.core.ai.validators import validate_placement_block
from app.core.config import app_config
from app.core.database import SessionLocal
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent

logger = logging.getLogger(__name__)

MODEL = app_config.GEMINI_FLASH_MODEL
QUIZ_TYPE_ID = 1  # quiz_type: 'multiple choice'
MAX_ATTEMPTS = 3  # original + max 2 retries (spec §8.1)
LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}

# Serializes background generation per role so concurrent clicks can never
# interleave deletes/inserts and multiply the question pool.
_role_locks: dict[int, asyncio.Lock] = {}


def _parse_json(text: str):
    """Parse the raw model output as JSON, tolerating code fences.

    Some providers run in json_object mode, which forces a top-level object
    even when an array is requested (e.g. `{"questions": [...]}`). Unwrap the
    first list value found in that case so the validator sees the array.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    parsed = json.loads(cleaned)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        preferred = ("questions", "rows", "data", "items", "results", "placement_test")
        for key in preferred:
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        for value in parsed.values():
            if isinstance(value, list):
                return value
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
            cost_usd=estimate_cost_usd(prompt_tokens, completion_tokens),
            status=status,
            role_id=role_id,
        )
    )


def _record_rejected(
    db: Session,
    role_id: int,
    input_preview: str,
    error: str,
    raw_response: str | None,
    validator_checks: dict | None,
) -> None:
    db.add(
        RejectedContent(
            generator="A",
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
        _, level, statement, options_str, answer_letter = row
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
                quiz_type_id=QUIZ_TYPE_ID,
                job_role_id=role_id,
            )
        )
    return len(rows)


async def _generate_skill_block(
    client: GeminiClientPool, role: JobRole, skill: str
) -> tuple:
    """
    Run Prompt A for one skill with retries. Returns
    (rows | None, usage_logs, error | None).
    """
    prompt = build_prompt_a(
        role=role.name,
        job_description=role.job_description,
        target_skill=skill,
        g_skill_description=role.g_skill_description,
        seed_tier_1=role.seed_tier_1,
        seed_tier_2=role.seed_tier_2,
    )

    usage_logs: list[dict] = []
    last_error = ""

    for attempt in range(MAX_ATTEMPTS):
        call_prompt = prompt if attempt == 0 else retry_prompt_a(prompt, last_error)
        response: LLMResponse = await client.generate_json(call_prompt)
        prompt_t, comp_t = extract_usage(response)
        raw = response.text

        try:
            rows = _parse_json(raw)
        except json.JSONDecodeError as exc:
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
            return rows, usage_logs, None

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
                return rows, usage_logs, None

        usage_logs.append(
            {
                "prompt_tokens": prompt_t,
                "completion_tokens": comp_t,
                "status": "retry",
                "provider": response.provider,
                "model": response.model,
            }
        )

    return None, usage_logs, (last_error or f"Skill block '{skill}' failed")


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
                    rows, usage_logs, error = await _generate_skill_block(
                        client, role, skill
                    )
                except (GenerationError, KillSwitchError) as exc:
                    rows, usage_logs, error = None, [], str(exc)

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
                        role_id,
                        f"role={role.name}, skill={skill}",
                        error or "unknown",
                        None,
                        None,
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
                gen.status = "failed"
                gen.error_message = str(exc)[:500]
                gen.finished_at = datetime.now(timezone.utc)
                db.commit()
            return {"status": "failed", "error": str(exc)}
        finally:
            db.close()
