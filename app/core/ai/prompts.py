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
- Start directly with [[ and end directly with ]].

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Target Skill: "{target_skill}"  (one of "D_doc" | "C_comm" | "T_trouble" | "G_custom")
- Target Skill Description: "{target_skill_description}"
- Seed Tier 1 Data (Basic): "{seed_tier_1}"
- Seed Tier 2 Data (Advanced): "{seed_tier_2}"
- Questions: {num_questions} per call (distribute as 3 questions per difficulty band)

[REQUIREMENTS]
1. Each inner array has EXACTLY 5 elements:
   Index 0: Target skill code (must be "{target_skill}")
   Index 1: Difficulty level (must be one of four: Easy, Medium, Hard, Expert)
   Index 2: Question text (max 25 words, authentic IT scenario)
   Index 3: "OptionA|OptionB|OptionC|OptionD" (pipe-separated)
   Index 4: Correct answer letter ("A", "B", "C", or "D")

2. Distribute the 12 questions across **4 difficulty bands** (3 questions per band):
   Band 1 = Easy (Tier 1 vocabulary), Band 2 = Medium,
   Band 3 = Hard (Tier 2 vocabulary), Band 4 = Expert.

3. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.

[EXAMPLE]
[
  ["{target_skill}", "Easy", "What does SRS stand for?", "Software Requirement Specification|System Resource Summary|Software Rate Standard|System Renewal Section", "A"],
  ["{target_skill}", "Hard", "Which phrase diplomatically rejects scope creep?", "No we cannot|That impacts our timeline, let us review|Stop asking|I will add it now", "B"]
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

PROMPT_B1_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT Curriculum Architect.
Design a course outline of EXACTLY {num_topics} topics for the "{role}" role.

{skill_definitions_block}

[REQUIRED EXACT DISTRIBUTION]
You must generate EXACTLY {num_topics} topics total. To ensure perfect counting, generate them sequentially in these exact groups:
1. First, EXACTLY {d_count} topics for "D_doc"
2. Second, EXACTLY {c_count} topics for "C_comm"
3. Third, EXACTLY {t_count} topics for "T_trouble"
4. Fourth, EXACTLY {g_count} topics for "G_custom"
STOP immediately after the final G_custom topic. The total must be exactly {num_topics}.

[REQUIREMENTS]
1. Output format: A single JSON array containing exactly {num_topics} inner arrays.
2. Each inner array has EXACTLY 3 elements:
   Index 0: Topic name (max 7 words). Use single quotes (') inside strings, never unescaped double quotes.
   Index 1: Primary skill ("D_doc" | "C_comm" | "T_trouble" | "G_custom")
   Index 2: Seed tier ("tier_1" | "tier_2"). Mix tier_1 and tier_2 within each skill group to achieve a ~50/50 balance.
3. Content: Must address real IT communication scenarios for "{role}" using the job description. 

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Seed Tier 1 Data: "{seed_tier_1}"
- Seed Tier 2 Data: "{seed_tier_2}"

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array of arrays.
- NO markdown formatting (no ```json or ```).
- NO conversational text.
- Start directly with [[ and end directly with ]].

[EXAMPLE EXPECTED STRUCTURE]
[
  ["Drafting initial project requirements", "D_doc", "tier_1"],
  ["Writing a complex BRD", "D_doc", "tier_2"],
  ["Facilitating daily standups", "C_comm", "tier_1"],
  ... (continue until exactly {num_topics} items are reached) ...
  ["Negotiating contract extensions", "G_custom", "tier_2"]
]
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

PROMPT_B2_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT English Curriculum Designer.
Break down the topic "{topic_name}" into EXACTLY {num_lessons} lesson titles for a "{role}" professional.

{skill_definitions_block}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array of arrays.
- NO markdown, NO backticks, NO conversational text.
- Start directly with [[ and end directly with ]].

[INPUT DATA]
- Role: "{role}"
- Topic: "{topic_name}"
- Topic Primary Skill: "{topic_skill}"
- Lesson Count: {num_lessons}
- Distribution: {num_basic} basic, {num_inter} intermediate, {num_adv} advanced

[REQUIREMENTS]
1. Each inner array has EXACTLY 3 elements:
   Index 0: Lesson title (max 7 words)
   Index 1: Primary skill ("D_doc" | "C_comm" | "T_trouble" | "G_custom")
   Index 2: Difficulty tier ("basic" | "intermediate" | "advanced")

2. Order lessons from basic → intermediate → advanced.
3. Primary skill should align with the topic's focus but can vary per lesson.
4. **ADVANCED LESSON CONSTRAINT (CRITICAL):** The topic's **two** Advanced lessons (the 5th and 6th, the final lessons) MUST BOTH be tagged with the topic's own primary skill `"{topic_skill}"`. This makes the roadmap's lesson floors computable — Advanced-track users take exactly 2 lessons per topic, so a single topic fully satisfies their 2-lesson skill floor.
5. Each lesson must be a distinct, actionable communication skill.
6. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.

[EXAMPLE]
[
  ["Understanding Agile Principles", "D_doc", "basic"],
  ["Refining Requirement Details", "D_doc", "basic"],
  ["Leading Sprint Reviews", "C_comm", "intermediate"],
  ["Reporting Blockers in Standups", "C_comm", "intermediate"],
  ["Defending Architecture Decisions", "T_trouble", "advanced"],
  ["Defusing Scope Disputes", "T_trouble", "advanced"]
]
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
Write the complete teaching content (Theory) for ONE lesson. Output a raw, valid JSON array.

{skill_definitions_block}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array containing EXACTLY 8 inner arrays.
- NO markdown, NO backticks, NO object keys, NO conversational text.
- Start directly with [[ and end directly with ]].
- Every string must stay on ONE line (no line breaks inside a string).
- CRITICAL: use single quotes (') inside strings, never unescaped double quotes.

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Parent Topic: "{parent_topic}"
- Lesson Title: "{lesson_title}"
- Primary Skill: "{primary_skill}"
- Difficulty Tier: "{difficulty_tier}"

[FORMAT]
Each inner array has EXACTLY 4 elements:
  Index 0: section name (scenario | vocab | phrases | reading | dialogue | process | dos_donts | wrapup)
  Index 1: primary content (the teaching material — see specs below)
  Index 2: supporting content (exact format per section below)
  Index 3: teacher note (one short sentence on how the learner should study this section)

[SECTION SPECS]

1. scenario — Index 1: a realistic role-specific workplace situation tied to the job description, in ENGLISH followed by a VIETNAMESE translation, format "English | Tiếng Việt". At least 60 English words. Index 2: exactly 3 numbered decision points the learner must resolve, format "1. ... | 2. ... | 3. ...".

2. vocab — Index 1: EXACTLY {num_vocab} role-specific IT English terms, format "term|/ipa/|pos|VN meaning|example # term2|/ipa/|pos|VN meaning|example". All terms must be usable in the lesson's communication scenario.

3. phrases — Index 1: EXACTLY {num_patterns} professional sentence frames, format "frame with ___ | usage | example # frame2 | usage | example". Each frame contains exactly ONE blank "___".

4. reading — Index 1: an authentic 200-300 word workplace document (status email, bug report, post-mortem, API doc excerpt) tied to the lesson. Index 2: 3-4 comprehension questions with answers, format "Q1. ... ? || A1. ... | Q2. ... ? || A2. ...".

5. dialogue — Index 1: a 150-250 word TEXT-ONLY workplace exchange with speaker labels, format strictly as: "Dev: ... | PM: ... | Dev: ...". Index 2: at least 3 key phrases used and why they are effective, format stricly as: "phrase - why it works | phrase2 - why it works".

6. process — Index 1: EXACTLY 6 step-by-step workflow actions for a real role procedure (deployment, incident response, scope negotiation, PR review...). Format strictly as: "1. [Action] | 2. [Action] | 3. [Action] | 4. [Action] | 5. [Action] | 6. [Action]". Index 2: EXACTLY 6 specific, engaging, and real-world pitfalls corresponding 1-to-1 with each step in Index 1. Format strictly as: "Pitfalls: [Engaging mistake 1] | Pitfalls: [Engaging mistake 2] | Pitfalls: [Engaging mistake 3] | Pitfalls: [Engaging mistake 4] | Pitfalls: [Engaging mistake 5] | Pitfalls: [Engaging mistake 6]". STRICT REQUIREMENTS FOR INDEX 2: 1) NO NUMBERS ALLOWED. Do NOT include "1.", "2.", etc. Every single item MUST start exactly with the prefix "Pitfalls: " followed immediately by the text. 2) CRITICAL ANTI-LAZY RULE: DO NOT simply negate the step (e.g., if a step is "Develop a communication plan", you CANNOT write "Not developing a communication plan" or "Failing to develop a plan"). 3) MAKE IT ENGAGING & INSIGHTFUL: Describe a specific, contextual root cause, a "hidden trap", or a realistic negative consequence that happens IN PRACTICE. Use varied, professional vocabulary to offer practical "insider advice". 4) LENGTH LIMIT: Keep EVERY single pitfall strictly concise (1-2 sentences max), practical, and easy to understand for learners. Example: Instead of "Not reviewing the scope", write "Pitfalls: Skimming the requirements and missing hidden edge cases, leading to massive scope creep mid-project".

7. dos_donts — Index 1: EXACTLY 5 "Do | Don't" response pairs for the lesson's scenario. Format strictly as: "Do: [English action] | Don't: [English action] # Do: [English action] | Don't: [English action] # Do: [English action] | Don't: [English action] # Do: [English action] | Don't: [English action] # Do: [English action] | Don't: [English action]" (5 pairs separated by "#"). Index 2: Vietnamese translations corresponding 1-to-1 with each of the 5 pairs in Index 1. Format strictly as:"Nên: [Vietnamese translation of the Do action] | Không nên: [Vietnamese translation of the Don't action] # [...] | [...] # [...] | [...] # [...] | [...] # [...] | [...]" (EXACTLY 5 parts separated by "#", matching the exact order of Index 1. STRICT REQUIREMENT: DO NOT include prefixes like "Do:", "Don't:", "Làm:", or "Không nên:" anywhere. CRITICAL: For the Vietnamese translation of the "Don't" action, DO NOT start the sentence with negative imperative words like "Không nên", "Đừng", or "Không". Translate ONLY the base action. Example: If Index 1 is "Don't: Assume things", Index 2 MUST be "... | Giả định mọi thứ", NOT "... | Không nên giả định mọi thứ". TRANSLATION GUIDELINES: Provide contextual, natural, and professional Vietnamese translations rather than strict literal word-for-word renderings. Retain standard technical terms, domain jargon, or professional concepts in English whenever translating them into Vietnamese feels forced, awkward, or loses precision (e.g., keep terms like "technical debt", "scope change", "stakeholder", "sprint" in English if a Vietnamese translation sounds unnatural)).

8. wrapup — Index 1: 3-4 core takeaways from the lesson. Index 2: one practical next-step task the learner can do right away (e.g. rewrite the reading document for their own project, or deliver the dialogue aloud). Index 3: how to review before moving on.

ANTI-DECAY: Every section must be generated with maximum depth. Do NOT shorten the later sections — reading and dialogue must hit their word counts.
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
    """Build the Prompt C-1 payload (8-section theory content for one lesson)."""
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
  theory — any of its sections (vocab, phrases, scenario, reading, dialogue, process, dos_donts).
  The correct option is the theory's exact term. STEM: a fresh professional sentence grounded in
  the lesson context, never a verbatim copy of the theory's examples.

TYPE 2: "multi_select" — {num_per_type} inner arrays, each with 4 elements:
  Index 0: Professional scenario/stem with a selection instruction (max 30 words)
  Index 1: "OptionA|OptionB|OptionC|OptionD|OptionE" (pipe-separated, EXACTLY 4-5 options)
  Index 2: Correct option indices as "0|2|4" (zero-based, pipe-separated, EXACTLY 2-3 correct options)
  Index 3: English explanation of why the selected options are the correct professional responses and why the unselected ones are less appropriate (max 40 words)
  SOURCE (answers): correct options are professional responses or terms taken from the theory
  (e.g. the dos_donts Do list, dialogue key phrases, scenario decision resolutions, process steps,
  reading recommendations); distractors are theory-based but clearly less appropriate. STEM: any
  lesson context (a decision point, a dialogue moment, a reading or process situation), varied
  across questions; vary the instruction form (select the professional responses / which responses
  are NOT appropriate / what to do next).

TYPE 3: "ordering" — {num_per_type} inner arrays, each with 4 elements:
  Index 0: Sequencing challenge instruction (max 15 words)
  Index 1: "ShuffledStep1|ShuffledStep2|ShuffledStep3|ShuffledStep4" (randomized)
  Index 2: Correct zero-based indices as "1|0|2|3"
  Index 3: English explanation of why this is the correct sequence for the workflow (max 35 words)
  SOURCE (answers): a multi-step sequence from the theory — the 'process' workflow when present,
  otherwise any ordered list in the theory (e.g. steps in the scenario, reading, dialogue, or
  dos_donts). Shuffle the items; the correct order is exactly the order given in the theory.
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
