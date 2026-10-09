"""Prompt A — Placement Test question generation.

Extracted from prompts.py to keep each generator's prompts in a focused module.
"""

from app.core.ai.dispatch.prompts_common import (
    NUM_PLACEMENT_QUESTIONS_PER_SKILL,
    SKILL_TITLES,
    render_skill_definitions_block,
    get_skill_description,
)
from app.models.job_role import get_job_description_text

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
- Questions: {num_questions} per call (distribute as {per_band} questions per difficulty band)

[REQUIREMENTS]
1. Each inner array has EXACTLY 6 elements:
   Index 0: Target skill code (must be "{target_skill}")
   Index 1: Difficulty level (must be one of three: Easy, Medium, Hard)
   Index 2: Question text (max 100 words, authentic IT scenario)
   Index 3: "OptionA|OptionB|OptionC|OptionD" (pipe-separated)
   Index 4: Correct answer letter ("A", "B", "C", or "D")
   Index 5: Expanded skill layer ("Context_layer" or "Language_layer")
2. Distribute the {num_questions} questions across **3 difficulty bands** ({per_band} questions per band):
   Band 1 = Easy (Tier 1 vocabulary), Band 2 = Medium,
   Band 3 = Hard (Tier 2 vocabulary).

3. CRITICAL: Use single quotes (') inside strings, never unescaped double quotes.
4. {context_per_band} questions of Each Difficulty are Context layer, others are Language layer    
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
        per_band=num_questions // 3,
        context_per_band=num_questions // 3 // 2,
        role=role,
        job_description=get_job_description_text(job_description, "en"),
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
