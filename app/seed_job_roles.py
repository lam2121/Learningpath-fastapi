"""Seed the default v2 job-role catalog for a fresh database.

Run with: python -m app.seed_job_roles
"""

from app.core.database import SessionLocal
from app.models.job_role import JobRole

ROLE_CATALOG = [
    {
        "name": "Project Manager",
        "job_description": (
            "Plans and coordinates software projects, aligns teams on scope, "
            "tracks delivery risks, and communicates progress with stakeholders."
        ),
        "baseline": {"D_doc": 15, "C_comm": 45, "T_trouble": 15, "G_custom": 25},
        "seed_tier_1": (
            "project plan, scope, timeline, budget, risk, stakeholder, milestone, "
            "deliverable, status report, change request"
        ),
        "seed_tier_2": (
            "critical path, earned value, agile hybrid, portfolio management, "
            "benefits realization, governance, escalation, negotiation, conflict "
            "resolution"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing and reviewing project documents such as status reports, "
                    "meeting minutes, action logs, and change records."
                ),
                "example_questions": [
                    "How do you write a concise weekly project status update?",
                    "What details should be captured in meeting minutes after a steering review?",
                ],
            },
            "C_comm": {
                "description": (
                    "Running meetings, setting expectations, giving updates, and "
                    "communicating professionally with stakeholders and delivery teams."
                ),
                "example_questions": [
                    "How would you explain a delivery delay to a client without causing panic?",
                    "How do you keep a standup focused when multiple teams join the call?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Handling project blockers, conflicting priorities, delayed inputs, "
                    "and scope issues before they derail delivery."
                ),
                "example_questions": [
                    "How do you respond when a critical dependency is still unresolved before release?",
                ],
            },
            "G_custom": {
                "description": (
                    "Project planning, scope management, risk control, stakeholder "
                    "alignment, resource negotiation, and delivery governance."
                ),
                "example_questions": [
                    "How would you negotiate a scope cut to protect a fixed release date?",
                    "What is the best way to escalate a delivery risk to senior stakeholders?",
                ],
            },
        },
    },
    {
        "name": "Business Analyst",
        "job_description": (
            "Elicits requirements, clarifies scope, documents business flows, and "
            "bridges communication between stakeholders and engineering teams."
        ),
        "baseline": {"D_doc": 30, "C_comm": 35, "T_trouble": 15, "G_custom": 20},
        "seed_tier_1": (
            "stakeholder, requirement, scope, business process, user story, "
            "acceptance criteria, workshop, interview, documentation, validation"
        ),
        "seed_tier_2": (
            "gap analysis, traceability matrix, impact assessment, change request, "
            "baseline, sign-off, elicitation techniques, prioritization frameworks, "
            "conflict resolution, negotiation"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing BRDs, user stories, process notes, acceptance criteria, "
                    "and clear requirement clarifications."
                ),
                "example_questions": [
                    "How do you rewrite a vague stakeholder request into actionable acceptance criteria?",
                    "What structure makes a requirement clarification easy for developers to follow?",
                ],
            },
            "C_comm": {
                "description": (
                    "Facilitating requirement workshops, asking clarifying questions, "
                    "and aligning stakeholders with engineering teams."
                ),
                "example_questions": [
                    "How would you ask a stakeholder to clarify a conflicting requirement?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Resolving ambiguity, handling conflicting inputs, and negotiating "
                    "workarounds when business and technical constraints collide."
                ),
                "example_questions": [
                    "What do you say when two stakeholders request incompatible outcomes?",
                ],
            },
            "G_custom": {
                "description": (
                    "Requirement elicitation, scope clarification, process modeling, "
                    "workshop facilitation, and impact analysis."
                ),
                "example_questions": [
                    "How do you run a discovery workshop that turns vague needs into prioritised stories?",
                ],
            },
        },
    },
    {
        "name": "Tech Lead",
        "job_description": (
            "Leads implementation decisions, mentors engineers, drives code quality, "
            "and communicates technical tradeoffs across the team."
        ),
        "baseline": {"D_doc": 20, "C_comm": 25, "T_trouble": 45, "G_custom": 10},
        "seed_tier_1": (
            "code review, mentor, estimation, sprint, backlog, refactor, regression, "
            "deployment, ticket, standup"
        ),
        "seed_tier_2": (
            "technical debt, architecture decision record, service mesh, observability, "
            "SLA, capacity planning, incident command, blameless post-mortem"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing technical proposals, implementation notes, decision records, "
                    "and actionable code review comments."
                ),
                "example_questions": [
                    "How do you document a technical decision so the team can revisit it later?",
                ],
            },
            "C_comm": {
                "description": (
                    "Giving technical guidance clearly, mentoring engineers, and aligning "
                    "delivery expectations with cross-functional teams."
                ),
                "example_questions": [
                    "How would you explain a risky implementation shortcut to your team?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Diagnosing delivery issues, unblocking the team, handling production "
                    "pressure, and driving resolution under uncertainty."
                ),
                "example_questions": [
                    "What would you say when the team discovers a release blocker late in sprint?",
                    "How do you guide a debugging discussion when multiple theories are competing?",
                ],
            },
            "G_custom": {
                "description": (
                    "Technical leadership, mentoring, estimation, architecture advocacy, "
                    "and negotiating technical debt priorities."
                ),
                "example_questions": [
                    "How do you justify spending sprint capacity on refactoring work?",
                ],
            },
        },
    },
    {
        "name": "Software Architect",
        "job_description": (
            "Designs system architecture, evaluates tradeoffs, defines standards, and "
            "communicates technical direction to engineering and business audiences."
        ),
        "baseline": {"D_doc": 30, "C_comm": 25, "T_trouble": 25, "G_custom": 20},
        "seed_tier_1": (
            "architecture, design, scalability, security, integration, technology, "
            "evaluation, documentation, decision, trade-off"
        ),
        "seed_tier_2": (
            "domain-driven design, event-driven, microservices, serverless, API gateway, "
            "service mesh, data mesh, zero trust, compliance, technical debt management"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing architecture decision records, technical design docs, and "
                    "structured tradeoff analyses."
                ),
                "example_questions": [
                    "How do you document a tradeoff between short-term delivery and long-term maintainability?",
                ],
            },
            "C_comm": {
                "description": (
                    "Explaining architecture clearly to engineering teams, leadership, "
                    "and non-technical stakeholders."
                ),
                "example_questions": [
                    "How would you explain a microservice decomposition decision to a product stakeholder?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Handling design conflicts, integration risks, scalability concerns, "
                    "and architecture issues in high-stakes situations."
                ),
                "example_questions": [
                    "What do you say when two teams propose incompatible integration patterns?",
                ],
            },
            "G_custom": {
                "description": (
                    "Architecture governance, technology evaluation, non-functional "
                    "requirements, integration strategy, and cost-aware design."
                ),
                "example_questions": [
                    "How do you justify a more expensive architecture choice based on long-term operational risk?",
                ],
            },
        },
    },
    {
        "name": "QA / Tester",
        "job_description": (
            "Validates software quality through test design, bug reporting, defect triage, "
            "and close collaboration with product and engineering teams."
        ),
        "baseline": {"D_doc": 30, "C_comm": 20, "T_trouble": 35, "G_custom": 15},
        "seed_tier_1": (
            "bug report, test case, test plan, regression, automation, severity, "
            "priority, defect, verification, validation"
        ),
        "seed_tier_2": (
            "root cause analysis, flaky test, test pyramid, CI/CD integration, test "
            "coverage, mutation testing, contract testing, performance testing, "
            "security testing, test strategy"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing reproducible bug reports, clear test cases, execution notes, "
                    "and concise test summaries."
                ),
                "example_questions": [
                    "What makes a bug report actionable for developers?",
                    "How do you write expected results when a workflow has multiple dependent steps?",
                ],
            },
            "C_comm": {
                "description": (
                    "Discussing defects professionally, clarifying expected behaviour, "
                    "and collaborating with developers during triage."
                ),
                "example_questions": [
                    "How would you push back when a defect is downgraded but still blocks testing?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Investigating failures, narrowing root causes, handling flaky results, "
                    "and escalating quality risks before release."
                ),
                "example_questions": [
                    "What do you say when an intermittent bug cannot be reproduced consistently?",
                ],
            },
            "G_custom": {
                "description": (
                    "Test strategy, defect triage, automation quality, root cause analysis, "
                    "and release-readiness assessment."
                ),
                "example_questions": [
                    "How do you explain the release risk when multiple medium-severity defects cluster in one area?",
                ],
            },
        },
    },
    {
        "name": "DevOps / SRE",
        "job_description": (
            "Operates CI/CD pipelines, infrastructure, reliability tooling, and incident "
            "response processes for production systems."
        ),
        "baseline": {"D_doc": 15, "C_comm": 20, "T_trouble": 50, "G_custom": 15},
        "seed_tier_1": (
            "deployment, pipeline, monitoring, incident, alert, rollback, infrastructure, "
            "container, orchestration, cloud"
        ),
        "seed_tier_2": (
            "chaos engineering, SRE practices, error budgets, SLI/SLO, canary deployment, "
            "blue-green, feature flags, observability, distributed tracing, runbook automation"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Writing runbooks, incident updates, handover notes, and operational "
                    "documentation that teams can act on under pressure."
                ),
                "example_questions": [
                    "How do you write a rollback runbook that another engineer can execute safely?",
                ],
            },
            "C_comm": {
                "description": (
                    "Communicating status clearly during incidents, coordinating responders, "
                    "and updating stakeholders without noise."
                ),
                "example_questions": [
                    "How would you announce an active production incident to engineering and management?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Handling outages, tracing operational failures, choosing recovery actions, "
                    "and restoring service quickly and safely."
                ),
                "example_questions": [
                    "What should you say when a deployment causes elevated error rates in production?",
                    "How do you guide the team when multiple alerts fire at once and the root cause is unclear?",
                ],
            },
            "G_custom": {
                "description": (
                    "Incident response, reliability engineering, infrastructure automation, "
                    "observability, and disaster recovery planning."
                ),
                "example_questions": [
                    "How do you justify pausing a release to protect an SLO?",
                ],
            },
        },
    },
    {
        "name": "Frontend / UI-UX",
        "job_description": (
            "Builds user interfaces, collaborates with design and product, and communicates "
            "interaction, accessibility, and performance tradeoffs."
        ),
        "baseline": {"D_doc": 25, "C_comm": 30, "T_trouble": 30, "G_custom": 15},
        "seed_tier_1": (
            "component, responsive, accessibility, wireframe, prototype, design system, "
            "user flow, state, render, interaction"
        ),
        "seed_tier_2": (
            "performance budget, Core Web Vitals, bundle splitting, server-side rendering, "
            "design tokens, headless UI, test-driven design, web accessibility audit"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Documenting UI behaviour, component usage, acceptance notes, and "
                    "handoff details between design and engineering."
                ),
                "example_questions": [
                    "How do you document a component state so QA can verify it correctly?",
                ],
            },
            "C_comm": {
                "description": (
                    "Discussing design intent, clarifying interactions, and negotiating UI "
                    "changes with design, product, and engineering partners."
                ),
                "example_questions": [
                    "How would you explain an accessibility concern to a designer and product owner?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Debugging rendering issues, cross-browser problems, and regressions while "
                    "communicating clear next steps to the team."
                ),
                "example_questions": [
                    "What do you say when a production UI bug only appears on one device class?",
                ],
            },
            "G_custom": {
                "description": (
                    "Frontend architecture, accessibility advocacy, design system alignment, "
                    "performance tradeoffs, and user-centred implementation decisions."
                ),
                "example_questions": [
                    "How do you justify spending time on accessibility fixes before a launch?",
                ],
            },
        },
    },
    {
        "name": "Data / AI Engineer",
        "job_description": (
            "Builds data pipelines and ML workflows, reports model outcomes, and explains "
            "data quality or model tradeoffs to technical and business stakeholders."
        ),
        "baseline": {"D_doc": 25, "C_comm": 20, "T_trouble": 35, "G_custom": 20},
        "seed_tier_1": (
            "dataset, feature, model, accuracy, pipeline, training, inference, validation, "
            "label, baseline"
        ),
        "seed_tier_2": (
            "precision-recall, overfitting, drift, shadow deployment, feature store, "
            "experiment tracking, reproducibility, fairness audit, model registry, "
            "data quality checks"
        ),
        "skill_definitions": {
            "D_doc": {
                "description": (
                    "Documenting datasets, experiments, feature logic, model assumptions, "
                    "and reproducible pipeline steps."
                ),
                "example_questions": [
                    "How do you document a feature engineering change so downstream users understand its impact?",
                ],
            },
            "C_comm": {
                "description": (
                    "Presenting findings, explaining model results, and discussing data risks "
                    "with engineers, analysts, and business stakeholders."
                ),
                "example_questions": [
                    "How would you explain model drift to a non-technical stakeholder?",
                ],
            },
            "T_trouble": {
                "description": (
                    "Diagnosing pipeline failures, debugging data quality issues, and handling "
                    "unexpected model behaviour under delivery pressure."
                ),
                "example_questions": [
                    "What do you say when a training job fails shortly before a release deadline?",
                ],
            },
            "G_custom": {
                "description": (
                    "Machine learning operations, experiment reporting, data governance, "
                    "feature engineering communication, and metric interpretation."
                ),
                "example_questions": [
                    "How do you justify choosing recall over precision for a business-critical model?",
                ],
            },
        },
    },
]


def seed_job_roles() -> None:
    db = SessionLocal()
    try:
        for role_data in ROLE_CATALOG:
            role = db.query(JobRole).filter(JobRole.name == role_data["name"]).first()
            if role is None:
                role = JobRole(name=role_data["name"])
                db.add(role)

            role.job_description = role_data["job_description"]
            role.baseline = role_data["baseline"]
            role.skill_definitions = role_data["skill_definitions"]
            role.seed_tier_1 = role_data["seed_tier_1"]
            role.seed_tier_2 = role_data["seed_tier_2"]
            role.is_active = True

        db.commit()
        print(f"Seeded {len(ROLE_CATALOG)} job roles.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_job_roles()
