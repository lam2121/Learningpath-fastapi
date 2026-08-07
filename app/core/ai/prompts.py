"""Prompt templates for AI content generators.

Prompt A is copied verbatim from docs/06-consolidated-v2-spec.md §5.2.
Do not modify the template text unless explicitly requested.
"""

NUM_PLACEMENT_QUESTIONS_PER_SKILL = 12
SKILLS = ["D_doc", "C_comm", "T_trouble", "G_custom"]

PROMPT_A_TEMPLATE = """[SYSTEM INSTRUCTION]
You are an expert IT English Assessment Architect.
Generate EXACTLY {num_questions} multiple-choice questions for the "{role}" role,
testing the "{target_skill}" skill.

[SKILL DEFINITIONS]
- D_doc (Document): Reading/writing technical docs, BRD, SRS, User Stories, Acceptance Criteria, Meeting Minutes.
- C_comm (Communication): English communication, vocabulary, phrasing, presentation, emails, professional interactions.
- T_trouble (Trouble): Problem solving, conflict resolution, scope creep, dealing with changing requirements, workarounds.
- G_custom: {g_skill_description}

[OUTPUT CONSTRAINT]
- Output ONLY a raw, valid JSON array of arrays.
- NO markdown formatting, NO backticks, NO object keys, NO conversational text.
- Start directly with [[ and end directly with ]].

[INPUT DATA]
- Role: "{role}"
- Job Description: "{job_description}"
- Target Skill: "{target_skill}"  (one of "D_doc" | "C_comm" | "T_trouble" | "G_custom")
- G_custom Description: "{g_skill_description}"
- Seed Tier 1 Data (Basic): "{seed_tier_1}"
- Seed Tier 2 Data (Advanced): "{seed_tier_2}"
- Questions: {num_questions} per call (distribute as 3 questions per difficulty band)

[REQUIREMENTS]
1. Each inner array has EXACTLY 5 elements:
   Index 0: Target skill code (must be "{target_skill}")
   Index 1: Difficulty level (integer 1-8)
   Index 2: Question text (max 25 words, authentic IT scenario)
   Index 3: "OptionA|OptionB|OptionC|OptionD" (pipe-separated)
   Index 4: Correct answer letter ("A", "B", "C", or "D")

2. Distribute the 12 questions across **4 difficulty bands** (3 questions per band):
   Band 1 = levels 1-2 (Tier 1 vocabulary), Band 2 = levels 3-4,
   Band 3 = levels 5-6 (Tier 2 vocabulary), Band 4 = levels 7-8.
   Within a band, spread the 3 questions across its 2 levels (e.g., 2 in one level, 1 in the other).

3. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.

[EXAMPLE]
[
  ["{target_skill}", 1, "What does SRS stand for?", "Software Requirement Specification|System Resource Summary|Software Rate Standard|System Renewal Section", "A"],
  ["{target_skill}", 5, "Which phrase diplomatically rejects scope creep?", "No we cannot|That impacts our timeline, let us review|Stop asking|I will add it now", "B"]
]
"""


def build_prompt_a(
    *,
    role: str,
    job_description: str,
    target_skill: str,
    g_skill_description: str,
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
        g_skill_description=g_skill_description,
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
