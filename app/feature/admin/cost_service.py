"""AI cost analytics, dashboard stats, and preview.

Extracted from admin_service.py for single-responsibility.
"""

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.feature.admin.admin_schema import (
    CostAlert,
    CostBucket,
    CostDashboardData,
    CostGroup,
    DashboardData,
)
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent
from app.models.topic import Topic
from app.models.user import LEARNING_ENROLLED, User
from app.models.user_placement_test import UserPlacementTest

PLACEMENT_TARGET_COUNT = app_config.NUM_PLACEMENT_QUESTIONS_PER_SKILL * 4  # 4 skills
COURSE_TARGET_TOPICS = app_config.NUM_TOPICS_PER_ROLE
COURSE_TARGET_LESSONS = COURSE_TARGET_TOPICS * app_config.NUM_LESSONS_PER_TOPIC

# ─── Dashboard ───────────────────────────────────────────────────────────────


def get_dashboard(db: Session) -> DashboardData:
    now = datetime.now()
    since = now - timedelta(days=30)

    total_tracks = db.query(JobRole).count()
    active_tracks = db.query(JobRole).filter(JobRole.is_active.is_(True)).count()
    active_learners = (
        db.query(User)
        .filter(
            User.job_role_id.isnot(None),
            User.learning_status == LEARNING_ENROLLED,
        )
        .count()
    )
    ai_calls_30d = db.query(AiUsageLog).filter(AiUsageLog.created_at >= since).count()
    ai_cost_30d = (
        db.query(AiUsageLog)
        .filter(AiUsageLog.created_at >= since)
        .with_entities(AiUsageLog.cost_usd)
        .all()
    )
    pending_rejected = (
        db.query(RejectedContent).filter(RejectedContent.status == "pending").count()
    )

    return DashboardData(
        totalTracks=total_tracks,
        activeTracks=active_tracks,
        activeLearners=active_learners,
        aiCalls30d=ai_calls_30d,
        aiCost30d=round(sum(c[0] for c in ai_cost_30d), 6),
        pendingRejected=pending_rejected,
    )


# ─── AI Costs ────────────────────────────────────────────────────────────────

# ─── Costs ───────────────────────────────────────────────────────────────────

# Preset ranges, and the bucket size each one defaults to.
COST_RANGES = ("7d", "30d", "90d", "this_month", "last_month", "12m", "all")
COST_GRANULARITIES = ("daily", "weekly", "monthly")
DEFAULT_GRANULARITY = {
    "7d": "daily",
    "30d": "daily",
    "90d": "weekly",
    "this_month": "daily",
    "last_month": "daily",
    "12m": "monthly",
    "all": "monthly",
}
_DATE_FORMATS = {"daily": "%Y-%m-%d", "weekly": "%x-W%v", "monthly": "%Y-%m"}

# Models are logged as "provider/model" when the provider is known and as a bare
# model id otherwise (older rows). Don't invent a provider for the bare ones.
UNSPECIFIED_PROVIDER = "unspecified"


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _resolve_cost_range(
    db: Session, range_key: str, now: datetime
) -> tuple[datetime, datetime]:
    """Resolve a preset to a midnight-aligned [from, to) window.

    Aligning to midnight matters: the old rolling `now - 30 days` produced
    partial first/last buckets whose boundaries moved with the wall clock.
    """
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = today + timedelta(days=1)

    if range_key == "7d":
        return end - timedelta(days=7), end
    if range_key == "30d":
        return end - timedelta(days=30), end
    if range_key == "90d":
        return end - timedelta(days=90), end
    if range_key == "this_month":
        return _month_start(today), end
    if range_key == "last_month":
        this_month = _month_start(today)
        return _month_start(this_month - timedelta(days=1)), this_month
    if range_key == "12m":
        start = _month_start(today)
        for _ in range(11):
            start = _month_start(start - timedelta(days=1))
        return start, end
    # "all" — clamp to the oldest row, or today when the table is empty.
    earliest = db.query(func.min(AiUsageLog.created_at)).scalar()
    start = (
        earliest.replace(hour=0, minute=0, second=0, microsecond=0)
        if earliest
        else today
    )
    return start, end


def _bucket_series(
    start: datetime, end: datetime, granularity: str
) -> list[tuple[str, str]]:
    """Every (period_key, label) in the window, so the chart has no gaps."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    cursor = start
    while cursor < end:
        if granularity == "monthly":
            key = cursor.strftime("%Y-%m")
            label = cursor.strftime("%b %Y")
            nxt = _month_start(_month_start(cursor) + timedelta(days=32))
        elif granularity == "weekly":
            iso_year, iso_week, _ = cursor.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            label = f"W{iso_week:02d} {iso_year}"
            nxt = cursor + timedelta(days=7)
        else:
            key = cursor.strftime("%Y-%m-%d")
            label = cursor.strftime("%b %d")
            nxt = cursor + timedelta(days=1)
        if key not in seen:
            seen.add(key)
            out.append((key, label))
        cursor = nxt
    return out


def _apply_cost_filters(
    query,
    *,
    generator: str | None,
    model: str | None,
    role_id: int | None,
    status_filter: str | None,
):
    """Same optional-kwarg / "all"-sentinel idiom as `list_usage_logs`."""
    if generator and generator != "all":
        query = query.filter(AiUsageLog.generator == generator)
    if model and model != "all":
        query = query.filter(AiUsageLog.model == model)
    if role_id is not None:
        query = query.filter(AiUsageLog.role_id == role_id)
    if status_filter and status_filter != "all":
        query = query.filter(AiUsageLog.status == status_filter)
    return query


def _to_groups(rows: list[tuple], total_cost: float, labels: dict | None = None):
    """(key, count, prompt, completion, cost) tuples -> sorted CostGroup list."""
    groups = []
    for key, count, prompt, completion, cost in rows:
        key_str = str(key) if key is not None else "—"
        cost = float(cost or 0.0)
        prompt = int(prompt or 0)
        completion = int(completion or 0)
        count = int(count or 0)
        groups.append(
            CostGroup(
                key=key_str,
                label=(labels or {}).get(key),
                count=count,
                promptTokens=prompt,
                completionTokens=completion,
                totalTokens=prompt + completion,
                totalCost=round(cost, 6),
                avgCost=round(cost / count, 6) if count else 0.0,
                share=round(cost / total_cost * 100, 4) if total_cost else 0.0,
            )
        )
    groups.sort(key=lambda g: (-g.totalCost, -g.count, g.key))
    return groups


def _provider_of(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else UNSPECIFIED_PROVIDER


def get_costs(
    db: Session,
    *,
    range_key: str = "30d",
    granularity: str | None = None,
    generator: str | None = None,
    model: str | None = None,
    role_id: int | None = None,
    status_filter: str | None = None,
) -> CostDashboardData:
    """Filtered, bucketed AI spend for the cost dashboard.

    Aggregates in SQL rather than loading rows into Python, which matters once
    ranges span months. Every breakdown is returned in one response so the
    dashboard needs a single request instead of a fetch waterfall.
    """
    if range_key not in COST_RANGES:
        range_key = "30d"
    if granularity not in COST_GRANULARITIES:
        granularity = DEFAULT_GRANULARITY[range_key]

    now = datetime.now()
    start, end = _resolve_cost_range(db, range_key, now)
    date_fmt = _DATE_FORMATS[granularity]

    def scoped(*columns):
        query = db.query(*columns).filter(
            AiUsageLog.created_at >= start, AiUsageLog.created_at < end
        )
        return _apply_cost_filters(
            query,
            generator=generator,
            model=model,
            role_id=role_id,
            status_filter=status_filter,
        )

    # ── Totals ──────────────────────────────────────────────────────────────
    total_cost, total_calls, total_prompt, total_completion = scoped(
        func.coalesce(func.sum(AiUsageLog.cost_usd), 0.0),
        func.count(AiUsageLog.id),
        func.coalesce(func.sum(AiUsageLog.prompt_tokens), 0),
        func.coalesce(func.sum(AiUsageLog.completion_tokens), 0),
    ).one()
    total_cost = float(total_cost or 0.0)
    total_calls = int(total_calls or 0)
    total_tokens = int(total_prompt or 0) + int(total_completion or 0)

    # ── Time buckets, zero-filled and split per generator ───────────────────
    period = func.date_format(AiUsageLog.created_at, date_fmt)
    bucket_rows = (
        scoped(
            period.label("period"),
            AiUsageLog.generator,
            func.coalesce(func.sum(AiUsageLog.cost_usd), 0.0),
            func.count(AiUsageLog.id),
        )
        .group_by("period", AiUsageLog.generator)
        .all()
    )
    by_period: dict[str, dict] = {}
    for period_key, gen, cost, count in bucket_rows:
        entry = by_period.setdefault(str(period_key), {"total": 0.0, "calls": 0, "gen": {}})
        entry["total"] += float(cost or 0.0)
        entry["calls"] += int(count or 0)
        entry["gen"][gen] = entry["gen"].get(gen, 0.0) + float(cost or 0.0)

    buckets = []
    for key, label in _bucket_series(start, end, granularity):
        entry = by_period.get(key, {"total": 0.0, "calls": 0, "gen": {}})
        buckets.append(
            CostBucket(
                period=key,
                label=label,
                total=round(entry["total"], 6),
                calls=entry["calls"],
                byGenerator={g: round(c, 6) for g, c in entry["gen"].items()},
            )
        )

    # ── Breakdowns ──────────────────────────────────────────────────────────
    def grouped(column):
        return (
            scoped(
                column,
                func.count(AiUsageLog.id),
                func.coalesce(func.sum(AiUsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(AiUsageLog.completion_tokens), 0),
                func.coalesce(func.sum(AiUsageLog.cost_usd), 0.0),
            )
            .group_by(column)
            .all()
        )

    by_generator = _to_groups(grouped(AiUsageLog.generator), total_cost)
    model_rows = grouped(AiUsageLog.model)
    by_model = _to_groups(model_rows, total_cost)
    by_status = _to_groups(grouped(AiUsageLog.status), total_cost)

    role_names = dict(db.query(JobRole.id, JobRole.name).all())
    by_track = _to_groups(grouped(AiUsageLog.role_id), total_cost, labels=role_names)

    # Providers are derived from the model string, so roll the model rows up
    # rather than re-querying with SUBSTRING_INDEX.
    provider_acc: dict[str, list] = {}
    for model_name, count, prompt, completion, cost in model_rows:
        acc = provider_acc.setdefault(_provider_of(str(model_name)), [0, 0, 0, 0.0])
        acc[0] += int(count or 0)
        acc[1] += int(prompt or 0)
        acc[2] += int(completion or 0)
        acc[3] += float(cost or 0.0)
    by_provider = _to_groups(
        [(k, v[0], v[1], v[2], v[3]) for k, v in provider_acc.items()], total_cost
    )

    # Filter options stay stable regardless of the current filters.
    available_models = sorted(
        m for (m,) in db.query(AiUsageLog.model).distinct().all() if m
    )

    bucket_count = len(buckets) or 1
    return CostDashboardData(
        rangeKey=range_key,
        granularity=granularity,
        fromDate=start.strftime("%Y-%m-%d"),
        toDate=(end - timedelta(days=1)).strftime("%Y-%m-%d"),
        totalCost=round(total_cost, 6),
        totalCalls=total_calls,
        totalTokens=total_tokens,
        periodAverage=round(total_cost / bucket_count, 6),
        buckets=buckets,
        byGenerator=by_generator,
        byModel=by_model,
        byProvider=by_provider,
        byTrack=by_track,
        byStatus=by_status,
        availableModels=available_models,
        alerts=_detect_cost_alerts(buckets, granularity),
    )


def _detect_cost_alerts(
    buckets: list[CostBucket], granularity: str
) -> list[CostAlert]:
    """Flag the most recent bucket when it overshoots the preceding average.

    Computed here only, so the banner and the alerts list can never disagree
    (they previously used different averaging windows).
    """
    if granularity != "daily" or len(buckets) < 8:
        return []
    window = buckets[-7:]
    baseline = [b.total for b in window[:-1]]
    avg = sum(baseline) / len(baseline) if baseline else 0.0
    latest = window[-1]
    if avg <= 0 or latest.total <= avg * 1.5:
        return []
    return [
        CostAlert(
            date=latest.period,
            type="spike",
            message=(
                f"{latest.label} cost (${latest.total:.4f}) exceeded the previous "
                f"6-day average (${avg:.4f}) by {((latest.total / avg - 1) * 100):.0f}%"
            ),
        )
    ]


