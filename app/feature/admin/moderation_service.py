"""Content moderation — rejected content, usage logs, and kill switch.

Extracted from admin_service.py for single-responsibility.
"""

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.ai.client.gemini import AI_GENERATION_ENABLED_KEY, generation_enabled
from app.core.infra.config import app_config
from app.feature.admin.admin_schema import (
    AiUsageLogResponse,
    KillSwitchState,
    RejectedContentResponse,
    UsageLogClearRequest,
    UsageLogClearResponse,
)
from app.models.ai_usage_log import AiUsageLog
from app.models.job_role import JobRole
from app.models.rejected_content import RejectedContent
from app.models.system_setting import SystemSetting

# ─── Rejected content ────────────────────────────────────────────────────────


def _rejected_to_response(db: Session, row: RejectedContent) -> RejectedContentResponse:
    role_name = None
    if row.role_id is not None:
        role = db.query(JobRole).filter(JobRole.id == row.role_id).first()
        role_name = role.name if role else None
    return RejectedContentResponse(
        id=row.id,
        generator=row.generator,
        roleId=row.role_id,
        roleName=role_name,
        inputPreview=row.input_preview,
        error=row.error,
        rawResponse=row.raw_response,
        validatorChecks=row.validator_checks,
        status=row.status,
        createdAt=row.created_at,
    )


def list_rejected(
    db: Session, generator: str | None = None, status_filter: str | None = None
) -> list[RejectedContentResponse]:
    query = db.query(RejectedContent).order_by(RejectedContent.created_at.desc())
    if generator and generator != "all":
        query = query.filter(RejectedContent.generator == generator)
    if status_filter and status_filter != "all":
        query = query.filter(RejectedContent.status == status_filter)
    rows = query.all()
    return [_rejected_to_response(db, r) for r in rows]


def update_rejected_status(
    db: Session, rejected_id: int, new_status: str
) -> RejectedContentResponse:
    if new_status not in ("pending", "fixed", "ignored"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be one of pending/fixed/ignored",
        )
    row = db.query(RejectedContent).filter(RejectedContent.id == rejected_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rejected content not found"
        )
    row.status = new_status
    db.commit()
    db.refresh(row)
    return _rejected_to_response(db, row)


# ─── AI usage logs ──────────────────────────────────────────────────────────


USAGE_LOG_DEFAULT_LIMIT = app_config.USAGE_LOG_DEFAULT_LIMIT
USAGE_LOG_MAX_LIMIT = app_config.USAGE_LOG_MAX_LIMIT


def _usage_to_response(db: Session, row: AiUsageLog) -> AiUsageLogResponse:
    role_name = None
    if row.role_id is not None:
        role = db.query(JobRole).filter(JobRole.id == row.role_id).first()
        role_name = role.name if role else None
    return AiUsageLogResponse(
        id=row.id,
        generator=row.generator,
        model=row.model,
        promptTokens=row.prompt_tokens,
        completionTokens=row.completion_tokens,
        costUsd=row.cost_usd,
        status=row.status,
        roleId=row.role_id,
        roleName=role_name,
        createdAt=row.created_at,
    )


def list_usage_logs(
    db: Session,
    generator: str | None = None,
    status_filter: str | None = None,
    role_id: int | None = None,
    limit: int = USAGE_LOG_DEFAULT_LIMIT,
) -> list[AiUsageLogResponse]:
    capped = max(1, min(limit, USAGE_LOG_MAX_LIMIT))
    query = db.query(AiUsageLog).order_by(
        AiUsageLog.created_at.desc(), AiUsageLog.id.desc()
    )
    if generator and generator != "all":
        query = query.filter(AiUsageLog.generator == generator)
    if status_filter and status_filter != "all":
        query = query.filter(AiUsageLog.status == status_filter)
    if role_id is not None:
        query = query.filter(AiUsageLog.role_id == role_id)
    rows = query.limit(capped).all()
    return [_usage_to_response(db, r) for r in rows]


def delete_usage_log(db: Session, log_id: int) -> None:
    row = db.query(AiUsageLog).filter(AiUsageLog.id == log_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usage log not found"
        )
    db.delete(row)
    db.commit()


def clear_usage_logs(
    db: Session, filters: UsageLogClearRequest | None = None
) -> UsageLogClearResponse:
    """Bulk-delete usage logs. With no filters, clears the ENTIRE table.

    Warning surfaced by the UI: irreversible audit-data loss — the AI Costs
    dashboard aggregates (30d) and dashboard stats are computed from this table.
    """
    query = db.query(AiUsageLog)
    if filters is not None:
        if filters.generator:
            query = query.filter(AiUsageLog.generator == filters.generator)
        if filters.status:
            query = query.filter(AiUsageLog.status == filters.status)
        if filters.roleId is not None:
            query = query.filter(AiUsageLog.role_id == filters.roleId)
    deleted = query.delete(synchronize_session=False)
    db.commit()
    return UsageLogClearResponse(deletedCount=int(deleted))


# ─── Kill switch ─────────────────────────────────────────────────────────────


def get_kill_switch(db: Session) -> KillSwitchState:
    row = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == AI_GENERATION_ENABLED_KEY)
        .first()
    )
    if row is None:
        return KillSwitchState(enabled=False)
    enabled = row.value.strip().lower() == "true"
    # Frontend semantics: `enabled` = kill switch ON (AI blocked) = NOT ai_generation_enabled
    return KillSwitchState(
        enabled=not enabled,
        enabledAt=row.updated_at if not enabled else None,
        enabledBy=row.updated_by,
        reason=row.reason,
    )


def set_kill_switch(
    db: Session, enabled: bool, reason: str | None, updated_by: int | None = None
) -> KillSwitchState:
    # enabled=True (kill switch ON) -> block generation
    new_value = "false" if enabled else "true"
    row = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == AI_GENERATION_ENABLED_KEY)
        .first()
    )
    if row is None:
        row = SystemSetting(key=AI_GENERATION_ENABLED_KEY, value=new_value)
        db.add(row)
    else:
        row.value = new_value
    row.updated_by = updated_by
    row.reason = reason
    db.commit()
    db.refresh(row)
    return KillSwitchState(
        enabled=not generation_enabled(db),
        enabledAt=row.updated_at if enabled else None,
        enabledBy=row.updated_by,
        reason=row.reason,
    )
