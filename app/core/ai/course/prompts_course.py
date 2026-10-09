"""Prompt B — Course Outline generation (B-1 Topics + B-2 Lesson Shells).

Extracted from prompts.py to keep each generator's prompts in a focused module.
"""

from app.core.ai.dispatch.prompts_common import (
    SKILLS,
    SKILL_TITLES,
    render_skill_definitions_block,
)
from app.core.infra.config import app_config
from app.models.job_role import get_job_description_text

# ─── Generator B-1: Topic Outline ────────────────────────────────────────────

NUM_TOPICS_PER_ROLE = app_config.NUM_TOPICS_PER_ROLE

PROMPT_B1_TEMPLATE = """You are an expert IT Curriculum Architect specializing in professional IT communication.

Your task is to generate a course outline for the role "{role}".

====================
TASK
====

Generate EXACTLY {num_topics} unique IT communication topics.

The topics must be directly relevant to:

* The target role
* The provided job description
* The four communication skill categories
* The provided seed data

====================
SKILL DEFINITIONS
=================

{skill_definitions_block}

====================
EXACT SKILL DISTRIBUTION
========================

You MUST generate exactly the following number of topics:

* D_doc: EXACTLY {d_count}
* C_comm: EXACTLY {c_count}
* T_trouble: EXACTLY {t_count}
* G_custom: EXACTLY {g_count}

TOTAL: EXACTLY {num_topics}

These counts are HARD CONSTRAINTS.

Do not generate fewer or more topics for any skill.

====================
TIER DISTRIBUTION
=================

Each topic must have exactly one seed tier:

* "tier_1"
* "tier_2"

For each skill group, distribute tier_1 and tier_2 as evenly as mathematically possible.

If a skill group contains an even number of topics:

* tier_1 count MUST equal tier_2 count.

If a skill group contains an odd number of topics:

* tier_1 and tier_2 counts may differ by at most 1.

====================
CONTENT REQUIREMENTS
====================

Every topic MUST:

1. Represent a real and useful IT communication scenario.
2. Be relevant to the "{role}" role.
3. Be supported by the job description.
4. Represent a distinct communication skill.
5. Be specific enough to become a complete lesson module later.
6. Avoid being a duplicate or near-duplicate of another topic.
7. Avoid generic English-learning topics unless they are directly relevant to the IT role.
8. Avoid topics that are purely technical tasks with no communication component.

Examples of good topic concepts:

* Drafting project requirements
* Reporting production incidents
* Explaining technical trade-offs
* Clarifying ambiguous requirements
* Presenting architecture decisions

Avoid vague topics such as:

* English Communication
* IT Vocabulary
* Communication Skills
* General English

====================
INPUT DATA
==========

ROLE:
{role}

JOB DESCRIPTION:
{job_description}

SEED TIER 1 DATA:
{seed_tier_1}

SEED TIER 2 DATA:
{seed_tier_2}

Use the seed data as inspiration and coverage guidance.
Do NOT simply copy the seed data.
Generate original topics that fit the target role.

====================
OUTPUT FORMAT
=============

Return ONLY a valid JSON array.

The JSON array MUST contain EXACTLY {num_topics} elements.

Each element MUST be an array containing EXACTLY 3 strings:

[
["Topic name", "Primary skill", "Seed tier"],
...
]

Element 0:

* Topic name
* Maximum 7 words

Element 1:

* MUST be exactly one of:
  "D_doc"
  "C_comm"
  "T_trouble"
  "G_custom"

Element 2:

* MUST be exactly one of:
  "tier_1"
  "tier_2"

All strings MUST use standard JSON double quotes.

Single quotes may appear normally inside string values.

Do NOT use single quotes as JSON delimiters.

====================
ORDER
=====

Group the topics in this exact order:

1. All D_doc topics
2. All C_comm topics
3. All T_trouble topics
4. All G_custom topics

Within each skill group, mix tier_1 and tier_2 topics as evenly as possible.

====================
FINAL VALIDATION BEFORE OUTPUT
==============================

Before producing the answer, internally verify ALL of the following:

* Total topic count = EXACTLY {num_topics}
* D_doc count = EXACTLY {d_count}
* C_comm count = EXACTLY {c_count}
* T_trouble count = EXACTLY {t_count}
* G_custom count = EXACTLY {g_count}
* Every element contains exactly 3 strings
* Every topic name has at most 7 words
* Every skill value is valid
* Every tier value is valid
* No duplicate or near-duplicate topics
* Output is valid JSON
* No text exists before or after the JSON array

If any condition is not satisfied, correct the output before returning it.

====================
OUTPUT
======

Return ONLY the JSON array.
Start with "[" and end with "]".
"""

def build_prompt_b1(
    *,
    role: str,
    job_description: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    seed_tier_1: str,
    seed_tier_2: str,
    baseline: dict[str, int],
    num_topics: int = NUM_TOPICS_PER_ROLE,
) -> str:
    """Build the Prompt B-1 payload (20-topic course outline for a role).

    `baseline` is the role's `{D_doc, C_comm, T_trouble, G_custom}` percentage
    blob. The template's `{baseline}` placeholder renders the per-skill
    distribution inline so the EXACT DISTRIBUTION rule carries the real numbers.
    """
    d = baseline.get("D_doc", 25)
    c = baseline.get("C_comm", 25)
    t = baseline.get("T_trouble", 25)
    g = baseline.get("G_custom", 25)

    # Calculate exact topic counts based on the percentages
    d_count = (d * num_topics) // 100
    c_count = (c * num_topics) // 100
    t_count = (t * num_topics) // 100
    g_count = (g * num_topics) // 100

    distribution = f"D={d}%, C={c}%, T={t}%, G_custom={g}%"

    return PROMPT_B1_TEMPLATE.format(
        num_topics=num_topics,
        role=role,
        job_description=get_job_description_text(job_description, "en"),
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        seed_tier_1=seed_tier_1,
        seed_tier_2=seed_tier_2,
        d=d,
        c=c,
        t=t,
        g=g,
        d_count=d_count,
        c_count=c_count,
        t_count=t_count,
        g_count=g_count,
        baseline=distribution,
    )


def retry_prompt_b1(original_prompt: str, parse_error: str) -> str:
    """Re-send the B-1 prompt with the parser's error message (spec §8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON array. "
        "Remember: single quotes inside strings, never unescaped double quotes."
    )


# ─── Generator B-1 (extension): More Topics for one skill ────────────────────

PROMPT_B1_MORE_TEMPLATE = """You are an expert IT Curriculum Architect specializing in professional IT communication.

Your task is to EXTEND an existing course outline for the role "{role}".

====================
TASK
====

Generate EXACTLY {count} NEW IT communication topic(s).

Every new topic MUST have the primary skill "{skill}".

The topics must be directly relevant to:

* The target role
* The provided job description
* The "{skill}" skill definition
* The provided seed data

====================
SKILL DEFINITIONS
=================

{skill_definitions_block}

====================
EXISTING TOPICS (DO NOT REPEAT)
===============================

The course already contains these topics:

{existing_topics_block}

Every new topic MUST cover a communication scenario that is NOT already covered above.

Do NOT duplicate, rename, or closely paraphrase any existing topic.

====================
NAMING VARIETY
==============

Existing "{skill}" topics already start with these opening words:

{used_openers_block}

Every new topic name MUST start with an opening word that is NOT in the list above.

The new topics MUST NOT share an opening word with each other.

Every new topic MUST be about a different document, situation, or audience than every existing topic — not an existing scenario described with different wording.

====================
TIER DISTRIBUTION
=================

Each topic must have exactly one seed tier:

* "tier_1"
* "tier_2"

Distribute tier_1 and tier_2 across the new topics as evenly as mathematically possible.

====================
CONTENT REQUIREMENTS
====================

Every topic MUST:

1. Represent a real and useful IT communication scenario.
2. Be relevant to the "{role}" role.
3. Be supported by the job description.
4. Represent a distinct communication skill.
5. Be specific enough to become a complete lesson module later.
6. Avoid being a duplicate or near-duplicate of another topic.
7. Avoid generic English-learning topics unless they are directly relevant to the IT role.
8. Avoid topics that are purely technical tasks with no communication component.

====================
INPUT DATA
==========

ROLE:
{role}

JOB DESCRIPTION:
{job_description}

SEED TIER 1 DATA:
{seed_tier_1}

SEED TIER 2 DATA:
{seed_tier_2}

Use the seed data as inspiration and coverage guidance.
Do NOT simply copy the seed data.
Generate original topics that fit the target role.

====================
OUTPUT FORMAT
=============

Return ONLY a valid JSON array.

The JSON array MUST contain EXACTLY {count} element(s).

Each element MUST be an array containing EXACTLY 3 strings:

[
["Topic name", "Primary skill", "Seed tier"],
...
]

Element 0:

* Topic name
* Maximum 7 words

Element 1:

* MUST be exactly "{skill}"

Element 2:

* MUST be exactly one of:
  "tier_1"
  "tier_2"

All strings MUST use standard JSON double quotes.

Single quotes may appear normally inside string values.

Do NOT use single quotes as JSON delimiters.

====================
FINAL VALIDATION BEFORE OUTPUT
==============================

Before producing the answer, internally verify ALL of the following:

* Total topic count = EXACTLY {count}
* Every element contains exactly 3 strings
* Every topic name has at most 7 words
* Every skill value is exactly "{skill}"
* Every tier value is valid
* No topic duplicates or closely paraphrases an existing topic
* No duplicate or near-duplicate topics among the new ones
* No new topic starts with an opening word already used by an existing "{skill}" topic
* No two new topics start with the same opening word
* Output is valid JSON
* No text exists before or after the JSON array

If any condition is not satisfied, correct the output before returning it.

====================
OUTPUT
======

Return ONLY the JSON array.
Start with "[" and end with "]".
"""


def build_prompt_b1_more(
    *,
    role: str,
    job_description: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    seed_tier_1: str,
    seed_tier_2: str,
    skill: str,
    count: int,
    existing_topics: list[tuple[str, str]],
) -> str:
    """Build the B-1 extension payload (`count` extra topics for one skill).

    `existing_topics` is the role's current `(name, primary_skill)` list; it is
    rendered into the prompt so the new topics do not repeat the outline, and
    the opening words of the same-skill topics are listed so the new names do
    not look like the existing ones. Retries reuse `retry_prompt_b1`.
    """
    existing_topics_block = (
        "\n".join(f"- {name} ({topic_skill})" for name, topic_skill in existing_topics)
        or "(none)"
    )
    # First word of each existing same-skill topic, de-duplicated in outline order.
    used_openers = list(
        dict.fromkeys(
            name.split()[0]
            for name, topic_skill in existing_topics
            if topic_skill == skill and name.split()
        )
    )
    used_openers_block = "\n".join(f"- {word}" for word in used_openers) or "(none)"
    return PROMPT_B1_MORE_TEMPLATE.format(
        used_openers_block=used_openers_block,
        count=count,
        skill=skill,
        role=role,
        job_description=get_job_description_text(job_description, "en"),
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        existing_topics_block=existing_topics_block,
        seed_tier_1=seed_tier_1,
        seed_tier_2=seed_tier_2,
    )


# ─── Generator B-2: Lesson Shells ────────────────────────────────────────────

NUM_LESSONS_PER_TOPIC = app_config.NUM_LESSONS_PER_TOPIC
NUM_BASIC_PER_TOPIC = app_config.NUM_BASIC_PER_TOPIC
NUM_INTERMEDIATE_PER_TOPIC = app_config.NUM_INTERMEDIATE_PER_TOPIC
NUM_ADVANCED_PER_TOPIC = app_config.NUM_ADVANCED_PER_TOPIC

PROMPT_B2_TEMPLATE = """You are an expert IT English Curriculum Designer.

Your task is to break down the topic "{topic_name}" into EXACTLY {num_lessons} distinct lesson titles for a "{role}" professional.

====================
SKILL DEFINITIONS
=================

{skill_definitions_block}

====================
INPUT
=====

Role:
{role}

Topic:
{topic_name}

Topic Primary Skill:
{topic_skill}

Lesson Count:
{num_lessons}

====================
HARD OUTPUT STRUCTURE
=====================

Return EXACTLY {num_lessons} lesson arrays.

Each lesson array MUST contain EXACTLY 3 strings:

[
["Lesson title", "Primary skill", "Difficulty"],
...
]

The {num_lessons} lessons MUST have these exact difficulty positions:

{tier_positions_block}

Lessons MUST appear in this exact order.

====================
ADVANCED SKILL CONSTRAINT
=========================

{advanced_must_block}

Therefore:

{advanced_example_block}

This is a HARD CONSTRAINT.

====================
LESSON REQUIREMENTS
===================

Every lesson must:

1. Be directly related to the topic.
2. Be relevant to the "{role}" role.
3. Represent a distinct communication skill.
4. Be actionable and teachable.
5. Progress in difficulty from basic to advanced.
6. Have a title of no more than 7 words.
7. Avoid duplicate or near-duplicate lessons.

Basic lessons should introduce foundational communication skills.

Intermediate lessons should require more contextual judgment and professional interaction.

Advanced lessons should involve complex professional communication, ambiguity, negotiation, conflict, decision-making, or high-impact situations.

The {num_adv} advanced lessons MUST remain focused on the topic's own primary skill.

====================
PRIMARY SKILL
=============

Each lesson's primary skill MUST be one of:

"D_doc"
"C_comm"
"T_trouble"
"G_custom"

Basic and intermediate lessons may use different skills when appropriate, but they must remain relevant to the topic.

Advanced lessons MUST use "{topic_skill}".

====================
JSON REQUIREMENTS
=================

All strings MUST use standard JSON double quotes.

Single quotes may appear normally inside string values.

Do NOT use single quotes as JSON delimiters.

Return raw JSON only.

Do NOT return:

* Markdown
* ```json
  ```
* Explanations
* Comments
* Additional fields
* Additional lessons

====================
FINAL VALIDATION
================

Before returning the answer, internally verify:

* Exactly {num_lessons} lessons
* Every lesson has exactly 3 elements
{tier_checklist_block}
{advanced_checklist_block}
* Every title <= 7 words
* No duplicate lessons
* Valid JSON
* No text before or after JSON

If any condition fails, fix it before returning the output.

====================
OUTPUT
======

Return ONLY the JSON array.
Start with "[" and end with "]".
"""



def build_prompt_b2(
    *,
    role: str,
    topic_name: str,
    topic_skill: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    num_lessons: int = NUM_LESSONS_PER_TOPIC,
) -> str:
    """Build the Prompt B-2 payload (6 lesson shells for one topic)."""
    tiers = (
        ["basic"] * NUM_BASIC_PER_TOPIC
        + ["intermediate"] * NUM_INTERMEDIATE_PER_TOPIC
        + ["advanced"] * NUM_ADVANCED_PER_TOPIC
    )
    # 1-based positions of the advanced lessons (always the last ones)
    advanced = [n for n, tier in enumerate(tiers, start=1) if tier == "advanced"]
    return PROMPT_B2_TEMPLATE.format(
        tier_positions_block="\n".join(
            f'Lesson {n} → "{tier}"' for n, tier in enumerate(tiers, start=1)
        ),
        advanced_must_block="\n\n".join(
            f"Lesson {n} MUST use the topic's primary skill:\n\n\"{topic_skill}\""
            for n in advanced
        ),
        advanced_example_block="\n\n".join(
            f'Lesson {n}:\n["...", "{topic_skill}", "advanced"]' for n in advanced
        ),
        tier_checklist_block="\n".join(
            f"* Lesson {n} = {tier}" for n, tier in enumerate(tiers, start=1)
        ),
        advanced_checklist_block="\n".join(
            f'* Lesson {n} skill = "{topic_skill}"' for n in advanced
        ),
        role=role,
        topic_name=topic_name,
        topic_skill=topic_skill,
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        num_lessons=num_lessons,
        num_basic=NUM_BASIC_PER_TOPIC,
        num_inter=NUM_INTERMEDIATE_PER_TOPIC,
        num_adv=NUM_ADVANCED_PER_TOPIC,
    )


def retry_prompt_b2(original_prompt: str, parse_error: str) -> str:
    """Re-send the B-2 prompt with the parser's error message (spec §8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON array. "
        "Remember: single quotes inside strings, never unescaped double quotes."
    )
