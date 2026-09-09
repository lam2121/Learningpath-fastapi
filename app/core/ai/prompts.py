"""Prompt templates for AI content generators.

Prompt A is copied verbatim from docs/06-consolidated-v2-spec.md §5.2.
Do not modify the template text unless explicitly requested.
"""

NUM_PLACEMENT_QUESTIONS_PER_SKILL = 12
SKILLS = ["D_doc", "C_comm", "T_trouble", "G_custom"]
SKILL_TITLES = {
    "D_doc": "Document",
    "C_comm": "Communication",
    "T_trouble": "Trouble",
    "G_custom": "Custom",
}


def render_skill_definitions_block(
    skill_definitions: dict[str, dict[str, str | list[str]]],
) -> str:
    lines = ["[SKILL DEFINITIONS]"]
    for skill in SKILLS:
        item = skill_definitions.get(skill) or {}
        description = str(item.get("description", "")).strip()
        lines.append(f"- {skill} ({SKILL_TITLES[skill]}): {description}")
    return "\n".join(lines)


def get_skill_description(
    skill_definitions: dict[str, dict[str, str | list[str]]], skill: str
) -> str:
    item = skill_definitions.get(skill) or {}
    return str(item.get("description", "")).strip()

PROMPT_A_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT English Assessment Architect.
Generate EXACTLY {num_questions} multiple-choice questions for the "{role}" role,
testing the "{target_skill}" skill.

{skill_definitions_block}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array of arrays.
- NO markdown formatting, NO backticks, NO object keys, NO conversational text.
- Start directly with [ and end directly with ].

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Target Skill: "{target_skill}"  (one of "D_doc" | "C_comm" | "T_trouble" | "G_custom")
- Target Skill Description: "{target_skill_description}"
- Seed Tier 1 Data (Basic): "{seed_tier_1}"
- Seed Tier 2 Data (Advanced): "{seed_tier_2}"
- Questions: {num_questions} per call (distribute as 4 questions per difficulty band)

[REQUIREMENTS]
1. Each inner array has EXACTLY 6 elements:
   Index 0: Target skill code (must be "{target_skill}")
   Index 1: Difficulty level (must be one of three: Easy, Medium, Hard)
   Index 2: Question text (max 100 words, authentic IT scenario)
   Index 3: "OptionA|OptionB|OptionC|OptionD" (pipe-separated)
   Index 4: Correct answer letter ("A", "B", "C", or "D")
   Index 5: Expanded skill layer ("Context_layer" or "Language_layer")
2. Distribute the {num_questions} questions across **3 difficulty bands** (4 questions per band):
   Band 1 = Easy (Tier 1 vocabulary), Band 2 = Medium,
   Band 3 = Hard (Tier 2 vocabulary).

3. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.
4. two questions of Each Difficulty are Context layer, others are Language layer    
[EXAMPLE]
[
  ["{target_skill}", "Easy", "During a meeting, the client presents an unclear requirement. Which response is most appropriate for seeking clarification without causing discomfort?", "What do you mean?|Could you elaborate a bit more on that requirement so I can make sure I capture it correctly?|That does not make sense to me.|I do not understand. Please explain.", "B","Context_layer"],
  ["{target_skill}", "Hard", "You need to reject a colleague's architectural proposal because you are concerned about its scalability. Which response demonstrates the most professional and constructive disagreement?", "This will not work; we need another approach.|I see the value in this approach, but I am concerned it might not scale well under peak load. Could we explore a caching layer as an alternative?|I disagree with this design.|Let us just do it my way instead.", "B","Context_layer"],
  ["{target_skill}", "Easy", "Which sentence is the most grammatically correct and professional way for a Project Manager to provide a progress update?", "The team have complete the task yesterday.|The team completed the task yesterday and is now preparing the deliverables for review.|The team completing the task yesterday.|The task has complete by the team yesterday.", "B","Language_layer"],
  ["{target_skill}", "Medium", "Which Project Management term refers to the uncontrolled expansion of project requirements without corresponding adjustments to time, budget, or resources?", "Risk mitigation|Scope creep|Resource allocation|Quality assurance", "B","Language_layer"],
  ["{target_skill}", "Hard", "Which sentence communicates a potential project delay most fluently and professionally?", "The project will be late because the development team did not finish.|We regret to inform you that we cannot do it on time.|Due to an unexpected technical dependency, the milestone may be delayed by three working days; however, we are evaluating mitigation options to minimize the impact.|The deadline is impossible, so we need more time.", "C","Language_layer"]
]
"""
def build_prompt_a(
    *,
    role: str,
    job_description: str,
    target_skill: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    seed_tier_1: str,
    seed_tier_2: str,
    num_questions: int = NUM_PLACEMENT_QUESTIONS_PER_SKILL,
) -> str:
    """Build the Prompt A payload for one skill block (12 questions)."""
    return PROMPT_A_TEMPLATE.format(
        num_questions=num_questions,
        role=role,
        job_description=job_description,
        target_skill=target_skill,
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        target_skill_description=get_skill_description(skill_definitions, target_skill),
        seed_tier_1=seed_tier_1,
        seed_tier_2=seed_tier_2,
    )


def retry_prompt_a(original_prompt: str, parse_error: str) -> str:
    """Re-send the prompt with the parser's error message so the AI can self-correct (spec §8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON array. "
        "Remember: single quotes inside strings, never unescaped double quotes."
    )


# ─── Generator B-1: Topic Outline ────────────────────────────────────────────

NUM_TOPICS_PER_ROLE = 20

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
        job_description=job_description,
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


# ─── Generator B-2: Lesson Shells ────────────────────────────────────────────

NUM_LESSONS_PER_TOPIC = 6
NUM_BASIC_PER_TOPIC = 2
NUM_INTERMEDIATE_PER_TOPIC = 2
NUM_ADVANCED_PER_TOPIC = 2

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

Return EXACTLY 6 lesson arrays.

Each lesson array MUST contain EXACTLY 3 strings:

[
["Lesson title", "Primary skill", "Difficulty"],
...
]

The six lessons MUST have these exact difficulty positions:

Lesson 1 → "basic"
Lesson 2 → "basic"
Lesson 3 → "intermediate"
Lesson 4 → "intermediate"
Lesson 5 → "advanced"
Lesson 6 → "advanced"

Lessons MUST appear in this exact order.

====================
ADVANCED SKILL CONSTRAINT
=========================

Lesson 5 MUST use the topic's primary skill:

"{topic_skill}"

Lesson 6 MUST use the topic's primary skill:

"{topic_skill}"

Therefore:

Lesson 5:
["...", "{topic_skill}", "advanced"]

Lesson 6:
["...", "{topic_skill}", "advanced"]

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

The two advanced lessons MUST remain focused on the topic's own primary skill.

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

* Exactly 6 lessons
* Every lesson has exactly 3 elements
* Lesson 1 = basic
* Lesson 2 = basic
* Lesson 3 = intermediate
* Lesson 4 = intermediate
* Lesson 5 = advanced
* Lesson 6 = advanced
* Lesson 5 skill = "{topic_skill}"
* Lesson 6 skill = "{topic_skill}"
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
    return PROMPT_B2_TEMPLATE.format(
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


# ─── Generator C-1: Theory Content (8 sections) ──────────────────────────────

NUM_VOCAB = 8
NUM_PATTERNS = 5

PROMPT_C1_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT English Instructor and Curriculum Architect specialized in software development workplace communication.
Write the complete teaching content (Theory) for ONE practical workplace lesson for an IT professional.
Output ONLY a raw, valid JSON array of EXACTLY 7 inner arrays.

{skill_definitions_block}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array containing EXACTLY 7 inner arrays.
- NO markdown formatting (no ```json or ```), NO backticks, NO object keys, NO conversational text.
- Start directly with [ and end directly with ].
- Every string must stay on ONE single line (NO literal line breaks inside a string; use escaped \\n if needed).
- CRITICAL: Use single quotes (') inside strings, NEVER unescaped double quotes.

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Parent Topic: "{parent_topic}"
- Lesson Title: "{lesson_title}"
- Primary Skill: "{primary_skill}"
- Difficulty Tier: "{difficulty_tier}"

[STRUCTURE]
Each of the 7 inner arrays has EXACTLY 4 elements:
  Index 0: Section name (must be in exact order: scenario | vocab | phrases | reading | dialogue | listening | wrapup)
  Index 1: Primary teaching content (see specifications below)
  Index 2: Supporting practice / analytical / pronunciation content (see specifications below)
  Index 3: Teacher note / pedagogical guidance (one short concise sentence on how to study/apply this section)

[SECTION SPECIFICATIONS]

1. scenario
   - Index 0: 'scenario'
   - Index 1: A realistic role-specific workplace situation tied to the job description, in ENGLISH followed by a natural VIETNAMESE translation. Minimum 60 English words. Format strictly as: "English scenario text | Tiếng Việt: Bản dịch tiếng Việt tự nhiên"
   - Index 2: EXACTLY 3 communication decision points the learner must resolve. Format: "1. [Decision 1] | 2. [Decision 2] | 3. [Decision 3]"
   - Index 3: Teacher note on analyzing communication challenges in this scenario.

2. vocab (Integrated with Speaking & Pronunciation)
   - Index 0: 'vocab'
   - Index 1: EXACTLY {num_vocab} role-specific IT English terms. All terms must be directly relevant to the lesson communication scenario. Format each entry as "term|/ipa/|pos|VN meaning|English explanation & nuance|workplace example & usage note|pronunciation guide & syllable stress", separated by " # ".
   - Index 2: Speaking & pronunciation drills for these terms: common pronunciation mistakes (e.g. silent letters, missing ending consonants /s/, /t/, /ks/, wrong syllable stress) + 3 spoken practice drill sentences to read aloud. Format: "Pronunciation Guide: [Specific phonetic tips for IT learners] | Drills: 1. [Practice sentence 1 with target term] | 2. [Practice sentence 2 with target term] | 3. [Practice sentence 3 with target term]"
   - Index 3: Teacher note on vocal placement, mouth shape, and shadowing exercises to speak these technical terms clearly and confidently.

3. phrases
   - Index 0: 'phrases'
   - Index 1: EXACTLY {num_patterns} genuine, professional IT workplace phrases/collocations (NOT sentence templates with blanks). Format each entry as "phrase|VN meaning|when to use (context & tone)|workplace example", separated by " # ".
   - Index 2: 3 realistic mini-scenarios where the learner must choose the best phrase among options. Format: "Scenario 1: [Context] -> Best phrase: [Phrase] | Scenario 2: ... | Scenario 3: ..."
   - Index 3: Teacher note on adapting tone and formality when delivering these phrases.

4. reading
   - Index 0: 'reading'
   - Index 1: An authentic 200-300 word workplace document (such as an Incident Post-Mortem, Architecture Decision Record, PR Review Thread, Client Escalation Email, or Technical Release Note) tied to the lesson.
   - Index 2: EXACTLY 6 comprehension questions with detailed reference answers covering 6 taxonomy dimensions: Detail, Main Purpose, Inference, Communication Tone/Strategy, Vocabulary in Context, and Next Action. Format strictly as: "Q1. [Question] || A1. [Detailed answer] | Q2. [Question] || A2. [Detailed answer] | Q3. [Question] || A3. [Detailed answer] | Q4. [Question] || A4. [Detailed answer] | Q5. [Question] || A5. [Detailed answer] | Q6. [Question] || A6. [Detailed answer]"
   - Index 3: Teacher note on reading strategies for technical workplace documents.

5. dialogue
   - Index 0: 'dialogue'
   - Index 1: A 150-250 word realistic workplace dialogue with a clear context setup. Format strictly as: "Context: [1-2 sentences setting the scene: participants, setting, goal] || Dialogue: Speaker 1: [Turn] | Speaker 2: [Turn] | Speaker 1: [Turn] | ..."
   - Index 2: Two parts separated by " || ":
     Part A: At least 3 key communicative phrases used and why they work (format: "phrase - why it works | phrase2 - why it works").
     Part B: 4 interactive completion tasks (2 questions to ask + 2 responses to give) for the learner to practice replying, with suggested answers. Format: "Practice Tasks: 1. (Ask): [Prompt] -> Suggested Answer: [Answer] | 2. (Ask): [Prompt] -> Suggested Answer: [Answer] | 3. (Reply): [Prompt] -> Suggested Answer: [Answer] | 4. (Reply): [Prompt] -> Suggested Answer: [Answer]"
   - Index 3: Teacher note on pronunciation, rhythm, and active listening in IT meetings.

6. listening
   - Index 0: 'listening'
   - Index 1: An authentic workplace spoken monologue/audio transcript (e.g. an engineering lead debriefing an outage, a scrum master delivering sprint blockers update, or a client providing verbal feedback in a sync). Length: 120-180 words. Format strictly as: "Audio Script: [Narrator/Speaker name]: '[Spoken text script with natural pauses and spoken markers]'"
   - Index 2: 4-5 focused listening comprehension questions with answers testing key numbers, decisions, urgency, and technical root causes. Format: "Q1. [Question] || A1. [Detailed answer] | Q2. [Question] || A2. [Detailed answer] | Q3. [Question] || A3. [Detailed answer] | Q4. [Question] || A4. [Detailed answer]"
   - Index 3: Teacher note on listening for keywords, intonation cues, and action items in fast-paced IT spoken English.

7. wrapup
   - Index 0: 'wrapup'
   - Index 1: EXACTLY 4 core linguistic takeaways covering: (1) Key Vocabulary & Pronunciation, (2) Strategic Phrase, (3) Essential Spoken/Communication Rule, (4) Critical Pitfall to avoid. Format: "1. [Vocab & Pronunciation Takeaway] | 2. [Phrase Takeaway] | 3. [Rule Takeaway] | 4. [Pitfall Takeaway]"
   - Index 2: One practical, 5-10 minute productive English output task that the learner can write or speak immediately. Format: "Action Task: [Specific task prompt instructing the learner to draft an email, Slack update, or speech outline using lesson concepts]"
   - Index 3: Teacher note: Checklist and self-evaluation criteria before proceeding to the quiz.

ANTI-DECAY: Every section must be generated with maximum depth. Do NOT shorten the later sections — reading, dialogue, and listening must hit their word counts.
"""



def build_prompt_c1(
    *,
    role: str,
    job_description: str,
    parent_topic: str,
    lesson_title: str,
    primary_skill: str,
    difficulty_tier: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
) -> str:
    """Build the Prompt C-1 payload (7-section theory content for one lesson)."""
    return PROMPT_C1_TEMPLATE.format(
        role=role,
        job_description=job_description,
        parent_topic=parent_topic,
        lesson_title=lesson_title,
        primary_skill=primary_skill,
        difficulty_tier=difficulty_tier,
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        num_vocab=num_vocab,
        num_patterns=num_patterns,
    )


def retry_prompt_c1(original_prompt: str, parse_error: str) -> str:
    """Re-send the C-1 prompt with the parser's error message (spec §8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON array. "
        "Remember: single quotes inside strings, never unescaped double quotes."
    )


# ─── Generator C-2: Combined Quiz (30 questions) ──────────────────────────────

NUM_PER_TYPE = 10

C2_EXAMPLE = """{
  "fill_blank": [
    ["The server crashed due to a memory ___", "lake|leak|lock|leakage", "leak", "A memory leak is a bug where a program fails to release unused memory, which crashes the server."]
  ],
  "multi_select": [
    ["Which responses are appropriate when the client pushes new scope?", "Let's add it to the backlog for next sprint|Sure, I will add it now|I need to check the impact on this sprint first|No, we are too busy", "0|2", "These responses assess the impact and route new scope into the backlog; the others overpromise or refuse outright."]
  ],
  "ordering": [
    ["Order the deployment steps", "Run tests|Merge PR|Deploy to staging|Monitor logs", "1|0|2|3", "You must test changes before merging so broken code never reaches staging or production."]
  ]
}"""


def build_prompt_c2(
    *,
    role: str,
    topic_name: str,
    lesson_title: str,
    primary_skill: str,
    difficulty_tier: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    theory_content: str,
    num_per_type: int = NUM_PER_TYPE,
    example: str = C2_EXAMPLE,
) -> str:
    """Build the Prompt C-2 payload (30-question lesson quiz grounded in theory).

    `theory_content` must be the C-1 JSON array rendered as a string (embedded
    verbatim in the prompt). `example` is the strict structure-example block.
    """
    return PROMPT_C2_TEMPLATE.format(
        role=role,
        topic_name=topic_name,
        lesson_title=lesson_title,
        primary_skill=primary_skill,
        difficulty_tier=difficulty_tier,
        skill_definitions_block=render_skill_definitions_block(skill_definitions),
        theory_content=theory_content,
        num_per_type=num_per_type,
        num_total=num_per_type * 3,
        example=example,
    )


def retry_prompt_c2(original_prompt: str, parse_error: str) -> str:
    """Re-send the C-2 prompt with the parser's error message (spec §8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON object "
        'with exactly 3 keys: "fill_blank", "multi_select", "ordering". '
        "Remember: single quotes inside strings, never unescaped double quotes."
    )


PROMPT_C2_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT Quiz Generator.
Generate a lesson quiz composed of EXACTLY 3 types: "fill_blank", "multi_select", "ordering",
with EXACTLY {num_per_type} questions per type (Total: {num_total} questions).
Every question MUST be grounded ONLY in the provided Reference Theory Content: each stem, every
option, and the correct answer must be drawn from the theory itself. Never invent facts, terms,
options, or procedures that are not present in the theory.

{skill_definitions_block}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON object with exactly 3 keys: "fill_blank", "multi_select", "ordering".
- NO markdown, NO backticks, NO conversational text.
- Start directly with {{ and end directly with }}.

[EXAMPLE]
Structure example only — produce your OWN content, with {num_per_type} questions per type (not the single one shown here):
{example}

[INPUT DATA]
- Role: "{role}"
- Parent Topic: "{topic_name}"
- Lesson Title: "{lesson_title}"
- Primary Skill: "{primary_skill}"
- Difficulty Tier: "{difficulty_tier}"
- Reference Theory Content (the ONLY allowed source for all question content): {theory_content}

[REQUIREMENTS]

TYPE 1: "fill_blank" — {num_per_type} inner arrays, each with 4 elements:
  Index 0: Professional sentence with a blank ___ (max 25 words)
  Index 1: "OptionA|OptionB|OptionC|OptionD" (pipe-separated)
  Index 2: Correct option (verbatim text)
  Index 3: English explanation of why the correct option is the right word/phrase for the blank (max 30 words)
  SOURCE (answers): the blanked term and all four options are terms or phrases taken from the
  theory — any of its sections (vocab, phrases, scenario, reading, dialogue, listening, wrapup).
  The correct option is the theory's exact term. STEM: a fresh professional sentence grounded in
  the lesson context, never a verbatim copy of the theory's examples.

TYPE 2: "multi_select" — {num_per_type} inner arrays, each with 4 elements:
  Index 0: Professional scenario/stem with a selection instruction (max 30 words)
  Index 1: "OptionA|OptionB|OptionC|OptionD|OptionE" (pipe-separated, EXACTLY 4-5 options)
  Index 2: Correct option indices as "0|2|4" (zero-based, pipe-separated, EXACTLY 2-3 correct options)
  Index 3: English explanation of why the selected options are the correct professional responses and why the unselected ones are less appropriate (max 40 words)
  SOURCE (answers): correct options are professional responses or terms taken from the theory
  (e.g. dialogue key phrases, scenario decision resolutions, listening key facts, reading recommendations);
  distractors are theory-based but clearly less appropriate. STEM: any lesson context (a decision point, a dialogue moment, a reading or listening situation), varied
  across questions; vary the instruction form (select the professional responses / which responses
  are NOT appropriate / what to do next).

TYPE 3: "ordering" — {num_per_type} inner arrays, each with 4 elements:
  Index 0: Sequencing challenge instruction (max 15 words)
  Index 1: "ShuffledStep1|ShuffledStep2|ShuffledStep3|ShuffledStep4" (randomized)
  Index 2: Correct zero-based indices as "1|0|2|3"
  Index 3: English explanation of why this is the correct sequence for the workflow (max 35 words)
  SOURCE (answers): a multi-step sequence from the theory — any ordered list in the theory
  (e.g. steps in the scenario, reading, dialogue, listening, or wrapup). Shuffle the items; the correct order is exactly the order given in the theory.
  STEM: a sequencing instruction naming the workflow.

RULES:
1. Grounding: every question is grounded ONLY in the Reference Theory Content. A learner who studied the theory can answer every question without outside knowledge.
2. Out of scope: never import vocabulary, facts, names, or procedures that do not appear in the Reference Theory Content.
3. No repeats: each theory term / phrase / decision point / pair / step is used at most once across the whole quiz where feasible, and no two questions share the same stem sentence. Reword fill_blank contexts — never copy theory examples verbatim.
4. Distinctness: all 30 stems must be unique strings across the quiz.
5. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.
6. All 3 types must have EXACTLY {num_per_type} questions each.
7. Difficulty calibration: question difficulty MUST match the lesson tier — basic: everyday workplace vocabulary and straightforward choices; intermediate: standard technical interactions; advanced: complex/high-stakes terminology and nuanced options. An Advanced lesson's quiz must be noticeably harder than a Basic one.
"""


## Reading Comment Prompts
PROMPT_D1_TEMPLATE = """
You are an expert IT English communication coach. Your task is to evaluate a learner's answer to a workplace scenario or comprehension question.

Here is the context:
Reading Content: "{reading_content}"
Question / Task Prompt: "{question}"
Reference / Suggested Answer: "{reference_answer}"

Here is the Learner's Answer:
"{user_answer}"

Analyze the learner's answer against the reference answer. Provide constructive, encouraging feedback focusing on:
1. Content & Meaning: Did they convey the core message and include necessary technical details?
2. Grammar & Vocabulary: Are there any grammatical errors? Did they use appropriate IT vocabulary?

Output your evaluation STRICTLY as a JSON object with the following schema, and no other text:
{{
    "feedback_summary": "<A short, encouraging 2-3 sentence summary of how they did, including feedback on grammar, vocabulary, tone and professionalism>"
}}
"""
## Dialogue Comment Prompts
PROMPT_D2_TEMPLATE = """
You are an expert IT English communication coach. Your task is to evaluate a learner's answer to a workplace scenario or comprehension question.

Here is the context:
Question / Task Prompt: "{question}"
Reference / Suggested Answer: "{reference_answer}"

Here is the Learner's Answer:
"{user_answer}"

Analyze the learner's answer against the reference answer. Provide constructive, encouraging feedback focusing on:
1. Content & Meaning: Did they convey the core message and include necessary technical details?
2. Grammar & Vocabulary: Are there any grammatical errors? Did they use appropriate IT vocabulary?

Output your evaluation STRICTLY as a JSON object with the following schema, and no other text:
{{
    "feedback_summary": "<A short, encouraging 2-3 sentence summary of how they did, including feedback on grammar, vocabulary, tone and professionalism>"
}}
"""

## Listening Comment Prompts
PROMPT_D3_TEMPLATE = """
You are an expert IT English communication coach. Your task is to evaluate a learner's answer to a workplace scenario or comprehension question.

Here is the context:
Listening Content: "{listening_content}"
Question / Task Prompt: "{question}"
Reference / Suggested Answer: "{reference_answer}"

Here is the Learner's Answer:
"{user_answer}"

Analyze the learner's answer against the reference answer. Provide constructive, encouraging feedback focusing on:
1. Content & Meaning: Did they convey the core message and include necessary technical details?
2. Grammar & Vocabulary: Are there any grammatical errors? Did they use appropriate IT vocabulary?

Output your evaluation STRICTLY as a JSON object with the following schema, and no other text:
{{
    "feedback_summary": "<A short, encouraging 2-3 sentence summary of how they did, including feedback on grammar, vocabulary, tone and professionalism>"
}}
"""

## Profile Page AI Coach Prompts 
PROMPT_E1_TEMPLATE ="""
You're a IT english teacher, user is a student, who want to improve their english skills .

Write a motivation and short comment (around 30 - 40 words) for user to encourage and inspire them to continue to learning based on some infomation of user:

1. Day Streak: {day_streak}

2. Lessons Learned: {lesson_learner} / {total_lesson_in_track} 

3. Accuracy : {accuracy} / 100

4. Daily Study Per Day : {daily_study_per_day}

Output your evaluation STRICTLY as a JSON object with the following schema, and no other text:
{{
    "feedback_summary": "<you response>"
}}
""" 