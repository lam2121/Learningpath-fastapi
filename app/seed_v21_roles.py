"""Seed v2.1 columns for existing job roles (baselines, G-skill, seed tiers).

Run with: python -m app.seed_v21_roles
"""

from app.core.database import SessionLocal
from app.models.job_role import JobRole

# Sensible v2.1 defaults per role name keyword (sum=100, each >=10, mult of 5)
ROLE_DEFAULTS = [
    {
        "keywords": ["project manager", "pm", "project"],
        "baseline": {"d": 15, "c": 45, "t": 15, "g": 25},
        "g_skill": "Project planning, scope management, risk management, stakeholder communication, status reporting, change control, resource allocation, lessons learned.",
        "tier1": "project plan, scope, timeline, budget, risk, stakeholder, milestone, deliverable, status report, change request",
        "tier2": "critical path, earned value, agile hybrid, portfolio management, benefits realization, governance, escalation, negotiation, conflict resolution",
    },
    {
        "keywords": ["business analyst", "ba", "business"],
        "baseline": {"d": 30, "c": 35, "t": 15, "g": 20},
        "g_skill": "Eliciting requirements, clarifying scope, stakeholder communication, writing BRD/FSD, acceptance criteria definition, user story mapping, process modeling, gap analysis, facilitating workshops.",
        "tier1": "stakeholder, requirement, scope, business process, user story, acceptance criteria, workshop, interview, documentation, validation",
        "tier2": "gap analysis, traceability matrix, impact assessment, change request, baseline, sign-off, elicitation techniques, prioritization frameworks, conflict resolution, negotiation",
    },
    {
        "keywords": ["tech lead", "technical lead"],
        "baseline": {"d": 20, "c": 25, "t": 45, "g": 10},
        "g_skill": "Technical decision making, mentoring junior engineers, code review leadership, architecture advocacy, effort estimation, technical debt negotiation.",
        "tier1": "code review, mentor, estimation, sprint, backlog, refactor, regression, deployment, ticket, standup",
        "tier2": "technical debt, architecture decision record, service mesh, observability, SLA, capacity planning, incident command, blameless post-mortem",
    },
    {
        "keywords": [
            "architect",
            "sw architect",
            "software architect",
            "solution architect",
        ],
        "baseline": {"d": 30, "c": 25, "t": 25, "g": 20},
        "g_skill": "Architecture decision records, technical design docs, trade-off analysis, technology evaluation, proof of concept, non-functional requirements, security architecture, integration patterns, cost optimization.",
        "tier1": "architecture, design, scalability, security, integration, technology, evaluation, documentation, decision, trade-off",
        "tier2": "domain-driven design, event-driven, microservices, serverless, API gateway, service mesh, data mesh, zero trust, compliance, technical debt management",
    },
    {
        "keywords": ["qa", "tester", "quality"],
        "baseline": {"d": 30, "c": 20, "t": 35, "g": 15},
        "g_skill": "Writing bug reports, test plans, test cases, automation scripts, regression testing, defect triage, severity/priority classification, root cause analysis, test metrics reporting.",
        "tier1": "bug report, test case, test plan, regression, automation, severity, priority, defect, verification, validation",
        "tier2": "root cause analysis, flaky test, test pyramid, CI/CD integration, test coverage, mutation testing, contract testing, performance testing, security testing, test strategy",
    },
    {
        "keywords": ["devops", "sre", "operations", "infrastructure"],
        "baseline": {"d": 15, "c": 20, "t": 50, "g": 15},
        "g_skill": "Incident response, runbook writing, post-mortem analysis, capacity planning, infrastructure as code, deployment strategies, monitoring/alerting, disaster recovery, SLO/SLI definition.",
        "tier1": "deployment, pipeline, monitoring, incident, alert, rollback, infrastructure, container, orchestration, cloud",
        "tier2": "chaos engineering, SRE practices, error budgets, SLI/SLO, canary deployment, blue-green, feature flags, observability, distributed tracing, runbook automation",
    },
    {
        "keywords": ["frontend", "ui", "ux", "front-end"],
        "baseline": {"d": 25, "c": 30, "t": 30, "g": 15},
        "g_skill": "Communicating UI/UX decisions, writing technical frontend docs, accessibility advocacy, design handoff, performance budgets, user research synthesis.",
        "tier1": "component, responsive, accessibility, wireframe, prototype, design system, user flow, state, render, interaction",
        "tier2": "performance budget, Core Web Vitals, bundle splitting, server-side rendering, design tokens, headless UI, test-driven design, web accessibility audit",
    },
    {
        "keywords": ["data", "ai", "machine learning", "ml"],
        "baseline": {"d": 25, "c": 20, "t": 35, "g": 20},
        "g_skill": "Explaining model trade-offs, data pipeline documentation, feature engineering communication, presenting experiment results, ML model governance, metric reporting to stakeholders.",
        "tier1": "dataset, feature, model, accuracy, pipeline, training, inference, validation, label, baseline",
        "tier2": "precision-recall, overfitting, drift, shadow deployment, feature store, experiment tracking, reproducibility, fairness audit, model registry, data quality checks",
    },
]

DEFAULT_BASELINE = {"d": 25, "c": 25, "t": 25, "g": 25}
DEFAULT_G_SKILL = "Professional skill development aligned to the role: driving growth initiatives, stakeholder influence, and continuous improvement in software delivery."
DEFAULT_TIER1 = "requirement, deliverable, stakeholder, status, report, review, deployment, support, meeting, documentation"
DEFAULT_TIER2 = "risk mitigation, negotiation, root cause analysis, escalation, trade-off, governance, observability, incident response, technical debt, alignment"


def seed_v21_roles():
    db = SessionLocal()
    try:
        roles = db.query(JobRole).order_by(JobRole.id.asc()).all()
        updated = 0
        for role in roles:
            matched = next(
                (
                    r
                    for r in ROLE_DEFAULTS
                    if any(k in role.name.lower() for k in r["keywords"])
                ),
                None,
            )
            if matched is None:
                matched = {
                    "baseline": dict(DEFAULT_BASELINE),
                    "g_skill": DEFAULT_G_SKILL,
                    "tier1": DEFAULT_TIER1,
                    "tier2": DEFAULT_TIER2,
                }

            changed = False

            # Apply the keyword-matched baseline as a single JSON blob.
            role.baseline = {
                "D_doc": matched["baseline"]["d"],
                "C_comm": matched["baseline"]["c"],
                "T_trouble": matched["baseline"]["t"],
                "G_custom": matched["baseline"]["g"],
            }
            changed = True
            if not role.g_skill_description:
                role.g_skill_description = matched["g_skill"]
                changed = True
            if not role.seed_tier_1:
                role.seed_tier_1 = matched["tier1"]
                changed = True
            if not role.seed_tier_2:
                role.seed_tier_2 = matched["tier2"]
                changed = True

            if changed:
                db.add(role)
                updated += 1
                print(
                    f"Enriched role: {role.name} "
                    f"(baseline={role.baseline})"
                )

        db.commit()
        print(f"Done. {updated} role(s) updated out of {len(roles)}.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_v21_roles()
