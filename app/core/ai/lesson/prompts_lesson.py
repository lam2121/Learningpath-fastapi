"""Prompt C — Lesson Content generation (C-1 Theory + C-2 Quiz).

Extracted from prompts.py to keep each generator's prompts in a focused module.
"""

from app.core.ai.dispatch.prompts_common import (
    SKILLS,
    SKILL_TITLES,
    render_skill_definitions_block,
)
from app.core.infra.config import app_config
from app.models.job_role import get_job_description_text

# ─── Generator C-1: Theory Content (7 sections - Trilingual EN/VI/JA) ────────

NUM_VOCAB = app_config.NUM_VOCAB
NUM_PATTERNS = app_config.NUM_PATTERNS

# Communicative function of each phrase pattern, in id order. The prompt lists
# the first `num_patterns` of these. Inserted as a format value, so braces here
# are literal (not doubled like in PROMPT_C1_TEMPLATE).
C1_PATTERN_FUNCTIONS = (
    """  * p1 (speech_act="clarification" or "inquiry", completion_kind="technical_solution" or "metric_or_constraint"): Diplomatic inquiry probing system constraints, underlying assumptions, or decision criteria. Ends with '?' with "{{completion}}" immediately preceding it. (e.g., "What alternative approaches can the team explore to {{completion}}?", "Under what criteria should the system trigger {{completion}}?")""",
    """  * p2 (speech_act="inquiry", completion_kind="open_proposal" or "trade_off_option"): Collaborative exploratory question opening negotiation, inviting stakeholder alternatives, or probing risk tolerance. Ends with '?' with "{{completion}}" immediately preceding it. (e.g., "How does the revised design address the risk of {{completion}}?", "What trade-offs should we prioritize when evaluating {{completion}}?")""",
    """  * p3 (speech_act="risk_mitigation" or "technical_solution", completion_kind="operational_action" or "root_cause_factor"): Authoritative statement establishing governance thresholds, architectural safeguards, or failover requirements. Statement ending with '.'; HARD BAN on starting with "I ", "We ", "Let's ", or "You ". (e.g., "Implementing an asynchronous queue directly prevents {{completion}}.", "Setting up real-time telemetry helps detect {{completion}}.")""",
    """  * p4 (speech_act="proposal" or "recommendation", completion_kind="trade_off_option" or "technical_solution"): Decisive statement framing comparative trade-offs, operational consequences, or prioritized resource allocation. Statement ending with '.'; HARD BAN on starting with "I ", "We ", "Let's ", or "You ". (e.g., "Prioritizing throughput over low latency necessitates {{completion}}.", "Decoupling the ingest pipeline significantly mitigates {{completion}}.")""",
    """  * p5 (speech_act="confirmation", completion_kind="operational_action" or "metric_or_constraint"): Executive statement confirming sign-off criteria, consensus verification, or action commitments. Statement ending with '.'; HARD BAN on starting with "I ", "We ", "Let's ", or "You ". (e.g., "Proceeding with this rollout remains contingent upon {{completion}}.", "Securing stakeholder sign-off requires {{completion}}.")""",
)

PROMPT_C1_TEMPLATE = """[SYSTEM INSTRUCTION]
You are a World-Class IT English Professor and Principal Technical Communication Coach at a top global technology firm.
Your mission is to generate an in-depth, immersive, pedagogically elite Trilingual (EN / VI / JA) workplace English lesson for the target role: {role}.
Do NOT cut corners, abbreviate, or produce superficial content. Provide extensive, linguistically rich, and authentic professional material designed to transform mid-to-senior IT engineers, tech leads, and product managers into fluent, persuasive international communicators.

[OUTPUT CONTRACT]
Return one raw, valid JSON object only—no markdown, fences, comments, or surrounding text. Start with {{ and end with }}. Use valid JSON and prefer single quotes inside text values. Include "schema_version": 4 and exactly these lesson sections: scenario, vocab, phrases, reading, dialogue, listening, wrapup. Follow the supplied JSON Schema exactly; do not add, rename, merge, or omit fields.

[TRILINGUAL GENERATION & LINGUISTIC STANDARDS]
1. Absolute Meaning Fidelity:
   - Every Vietnamese ('vi') and Japanese ('ja') field MUST represent the EXACT SAME underlying technical concept, dilemma, dialogue turn, or metric as its English ('en') counterpart.
   - Do NOT invent divergent storylines, contradictory facts, or unrelated examples across languages.
2. Authentic High-Impact Workplace English Register:
   - Target Audience: Professional software engineers, architects, tech leads, and PMs who need to negotiate, clarify, and lead technical initiatives in global English environments.
   - Employ advanced professional collocations (e.g., "reconcile competing priorities", "mitigate single points of failure", "incur technical debt", "substantiate assertions with telemetry", "broker a consensus", "ring-fence critical deliverables", "establish fault tolerance", "negotiate scope trade-offs").
   - Integrate diplomatic hedging and authoritative framing ("From an architectural standpoint...", "While I recognize the aggressive timeline, we must weigh...", "Preliminary telemetry indicates...", "Our fallback posture hinges upon...").
   - Avoid simplistic ESL textbook phrasing. Sentences should sound like articulate senior engineers at Google, AWS, or Stripe.
3. Natural Workplace Vietnamese ('vi'):
   - Use polished, modern IT workplace Vietnamese as spoken by senior engineers and IT directors in international tech hubs (chuẩn mực, tự nhiên, chuyên nghiệp; không dịch thô máy móc, giữ thuật ngữ chuyên ngành chuẩn).
4. Business IT Japanese ('ja') with JLPT N2–N1 Professional Polish:
   - Context-sensitive keigo and register:
     * Formal documents/monologues/reports (scenario, reading docs, listening, wrapup): Use polite business Japanese (丁寧語 / 謙譲語 / 尊敬語 trang nhã, chuyên nghiệp).
     * Collaborative discussions and chats (dialogue turns, Slack threads): Use clean, collaborative tech workplace style (standard です・ます gọn gàng, tự nhiên, mang tính đồng đội).
   - Standard IT Katakana loanwords (e.g., デプロイ, リファクタリング, ボトルネック, レイテンシー, コンセンサス) paired with precise Kanji terms (冗長化, 負荷分散, 障害復旧, 疎結合).
5. Strict Bracketed Furigana in Japanese:
   - Every Kanji compound in running Japanese text MUST be bracketed with its Hiragana reading: [Kanji|hiragana] (e.g., [設計|せっけい], [進捗|しんちょく], [脆弱性|ぜいじゃくせい]).
   - The reading after '|' MUST be pure Hiragana ONLY! NEVER repeat Kanji as the reading.
   - Kana-only words, Latin acronyms (API, PR, SLA, DB), numbers, and punctuation must NOT have brackets.
   - In vocab.items, provide the term in en, vi, ja and provide the "reading" field with the pure Hiragana reading of the Japanese term.

{skill_definitions_block}

[LESSON METADATA & CONTEXTUAL SCOPE]
Target Role: "{role}" | Job Profile: "{job_description}"
Topic Domain: "{parent_topic}" | Target Skill: "{primary_skill}" | Level Tier: "{difficulty_tier}"
Current Lesson: "{lesson_title}" | Specific Focus: "{current_lesson_focus}"
Roadmap Sequence: "{lesson_sequence}" ({current_lesson_position}) | Topic Objective: "{topic_learning_goal}"
Prior Concepts (Do NOT repeat): "{previous_lesson_key_concepts}"
Upcoming Concepts (Do NOT preempt): "{next_lesson_key_concepts}"
Banned Vocabulary from Prior Lessons (STRICT DEDUPLICATION - DO NOT REUSE): [{banned_terms_block}]
Banned Phrase Stems from Prior Lessons (STRICT DEDUPLICATION - DO NOT REUSE OR ADAPT): [{banned_phrases_block}]
Designated Reading Document Type: "{reading_doc_type}"

[CRITICAL ANTI-DUPLICATION & ZERO-CLONING MANDATE ACROSS ALL SECTIONS]
1. ZERO VOCABULARY REPETITION:
   - Every single term in vocab.items MUST be 100% novel, specifically chosen for "{lesson_title}" and "{current_lesson_focus}".
   - Under NO circumstances may you reuse any word or phrase from [Banned Vocabulary from Prior Lessons].
   - No morphological variations or derivations (e.g., if "mocking" is banned, "mock", "mocks", "mocked", "mocking", or "mock server" are also forbidden).
   - BAN ON GENERIC BUZZWORDS: Avoid repeating generic engineering buzzwords across lessons ("scalability", "latency", "throughput", "deployment"). Instead, introduce concrete components, specific mechanisms, algorithmic techniques, architectural patterns, error conditions, and industry-standard protocols directly tied to this lesson.
2. ZERO PHRASE TEMPLATE REPETITION & BAN ON STOCK BOILERPLATE:
   - Every stem_template in phrases.items (p1-p{num_patterns}) MUST be fresh, unique, and tailored to "{lesson_title}".
   - ABSOLUTE BAN on repetitive formulaic starters and stock boilerplate phrases:
     * "Under what criteria should the team {{{{completion}}}}?"
     * "What technical implications arise if {{{{completion}}}}?"
     * "How does the revised protocol accommodate {{{{completion}}}}?"
     * "To what extent will the pipeline tolerate {{{{completion}}}}?"
     * "Which trade-off takes priority if {{{{completion}}}}?"
     * "From a reliability standpoint, how do we validate {{{{completion}}}}?"
     * "Prioritizing throughput over latency necessitates {{{{completion}}}}."
     * "Any unmitigated regression in query speed risks {{{{completion}}}}."
     * "Decoupling worker processes helps isolate {{{{completion}}}}."
     * "Establishing clear failover thresholds prevents {{{{completion}}}}."
     * "Adopting an asynchronous circuit breaker mitigates {{{{completion}}}}."
     * "Formal validation by security leads confirms {{{{completion}}}}."
     * "Could you clarify how {{{{completion}}}}?"
     * "Would it be feasible to explore {{{{completion}}}}?"
   - Never repeat the first 4 words of any stem from [Banned Phrase Stems from Prior Lessons].
3. ZERO NARRATIVE & SCENARIO CLONING:
   - Do NOT reuse plot lines, project names, service names, or incident archetypes across lessons.
   - Every lesson must feature a unique workplace challenge, unique system names, and unique stakeholder dynamics matching "{lesson_title}".
   - In dialogue, use fresh, realistic personas with diverse names (e.g., Sarah Chen, Marcus Vance, Elena Rostova, Kenji Sato, Priya Patel).

[SECTION-BY-SECTION DETAILED SPECIFICATIONS]

1. SCENARIO (Workplace Technical & Strategic Dilemma):
- Length & Substance: Rich, immersive narrative of 120-150 words in EN (and matching equivalents in VI and JA).
- Content Requirements: Ground the story in a high-stakes engineering situation directly derived from "{lesson_title}" ({parent_topic}). Detail specific project deliverables, system constraints, measurable SLAs/KPIs, and conflicting stakeholder pressures (e.g., rapid feature launch vs. architectural resilience; client scope demands vs. sprint capacity).
- Decisions: Exactly 3 distinct strategic decisions (each with en, vi, ja), 20-30 words each:
  * Decision 1 (Immediate Tactical Trade-off): High velocity / short-term relief that incurs manageable technical debt.
  * Decision 2 (Architectural & Sustainability Path): High upfront investment / deferred timeline ensuring future scalability and zero regression.
  * Decision 3 (Fallback & Phased Mitigation): Balanced compromise with ring-fenced scope, canary testing, and clear rollback criteria.
- Teacher Note: High-value pedagogical coaching ({{en, vi, ja}}) explaining how to articulate high-stakes technical trade-offs diplomatically in English executive meetings.

2. VOCABULARY (Specialized Lexicon & Collocations):
- Exactly {num_vocab} specialized terms directly anchored to "{lesson_title}".
- Mix of technical precision terms (mechanisms, patterns, components) and high-utility workplace communicative vocabulary (negotiation verbs, governance nouns, evaluative adjectives).
- Each item must contain:
  * term: ({{en, vi, ja}}).
  * reading: Pure Hiragana reading of the Japanese term.
  * ipa: Accurate International Phonetic Alphabet transcription with primary stress marks (e.g., /ˌaɪ.dəmˈpoʊ.tənt/).
  * pos: Part of speech ("noun", "verb", "adjective", "adverb", or "phrase").
  * explanation: In-depth technical and functional definition (25-35 words in EN, and matching VI/JA) detailing its mechanism, operational context, and significance.
  * example: Authentic workplace sentence (25-40 words in EN, and matching VI/JA) as uttered by a staff engineer or tech lead, demonstrating natural collocations.
  * pronunciation_guide: Syllable breakdown, primary stress indicator, and practical phonetic guidance for non-native speakers (e.g., "Syllables: i-dem-po-tent. Primary stress on second syllable 'dem'. Rhymes with 'potent'.").
- Section pronunciation_guide: A dedicated coach's overview of common phonological challenges, rhythm, or connected speech patterns relevant to this lesson's terms.
- Drills: Exactly 3 interactive language drills ({{en, vi, ja}}) testing contextual usage, collocations, or differentiation between easily confused terms.
- Teacher Note: Linguistic insights ({{en, vi, ja}}) highlighting common ESL misuses or nuances.

3. PHRASES (Strategic Workplace Discourse Patterns):
- Exactly {num_patterns} original, highly authentic templates labeled p1 through p{num_patterns}.
- Every stem_template MUST contain exactly one literal "{{{{completion}}}}" token.
- MANDATORY PHRASE LENGTH & CONCISENESS (CRITICAL):
  * Stems must be concise, punchy sentence frames: strictly 6 to 10 words (maximum 12 words). DO NOT write long run-on sentences, heavy multi-clause preambles, or bloated paragraphs!
  * example_completion must be short, sharp, and high-impact: strictly 3 to 7 words (maximum 8 words; NEVER 10-25 words!). It only provides the missing technical condition or action.
  * The total completed sentence must be crisp, professional, and around 10 to 16 words total—easy for an engineer to remember and adapt in real discussions.
- MANDATORY TRANSLATION & SLOT FIDELITY (SEAMLESS REPLACEMENT WITH '...'):
  * In both meaning.vi and meaning.ja, you MUST include exactly one literal '...' indicating the placeholder slot corresponding to "{{{{completion}}}}" in English.
  * SLOT POSITION & SEAMLESS REPLACEMENT: Place '...' naturally in the Vietnamese and Japanese word order so that directly replacing '...' with example_completion.vi / example_completion.ja forms a 100% natural, grammatically correct sentence.
  * ABSOLUTE BAN ON PARENTHESES '()': NEVER wrap completions or explanations in parentheses (e.g., NEVER output '... nào? (khám phá trước khi ...)'). The sentence MUST read smoothly as a single unified sentence.
  * Example of Perfect Concise Alignment:
    - stem_template: "What alternative approaches can the team explore to {{{{completion}}}}?" (9 words)
    - example_completion: {{"en": "mitigate configuration drift", "vi": "giảm thiểu sự sai lệch cấu hình", "ja": "[構成|こうせい]のドリフトを[軽減|けいげん]する"}}
    - meaning: {{"vi": "Đội ngũ có thể tìm hiểu những phương án nào để ...?", "ja": "...ためにチームはどのような[代替|だいたい]アプローチを[検討|けんとう]できますか？"}}
    - Direct substitution of '...' yields a seamless, natural sentence without parentheses:
      * VI: "Đội ngũ có thể tìm hiểu những phương án nào để giảm thiểu sự sai lệch cấu hình?"
      * JA: "[構成|こうせい]のドリフトを[軽減|けいげん]するためにチームはどのような[代替|だいたい]アプローチを[検討|けんとう]できますか？"
- Strict Communicative Function Breakdown:
{pattern_functions_block}
- Every phrase item contains:
  * meaning: ({{vi, ja}} - MUST contain '...' at the slot insertion point).
  * when_to_use: (15-25 words in EN, VI, JA) explaining the pragmatic social context and diplomatic objective.
  * example_completion: (3-7 words in EN, VI, JA - short, punchy technical phrase that grammatically expands "{{{{completion}}}}" or '...').
- Mini Scenarios: Exactly 3 mini_scenarios (context with {{en, vi, ja}}, referencing p1, p2, p3): realistic workplace mini-dilemmas showing why that phrase is the optimal communicative choice.
- Teacher Note: Pragmatic coaching ({{en, vi, ja}}) on vocal inflection, executive presence, and assertiveness balance.

4. READING (Authentic Workplace Technical Documentation):
- Genre Integrity: doc_type MUST be copied verbatim from "{reading_doc_type}" (or selected from the approved genres below).
- Document Structure:
  * title: ({{en, vi, ja}}).
  * metadata: Exactly 3 realistic key-value pairs (e.g., "Document ID", "Author / Role", "Target SLA / Status").
  * sections: Exactly 3 substantive sections using realistic document types ("paragraph", "bullet", "numbered", or "chat").
  * Depth & Word Count: Each section must be substantial (80-120 words for paragraphs, 4-6 rich items for bullets/numbered, or 4-6 realistic messages for chat), loaded with authentic metrics, error codes, service dependencies, architectural rationales, and business impacts.
- Approved Genres:
  * "Jira User Story & Acceptance Criteria Spec"
  * "Slack / Teams Multi-speaker Discussion Thread"
  * "Architecture Decision Record (ADR) or Technical Design Spec"
  * "Meeting Minutes & Action Items Log"
  * "Scope Change Request (CR) & Impact Analysis"
  * "Incident Post-Mortem (RCA) & Root Cause Analysis"
  * "Formal Workplace Email or Client Memo"
  * "Executive Status Report or Client Sign-off Memo"
- Reading Comprehension Q&A: Exactly 6 Q&A pairs (question and answer with {{en, vi, ja}}) strictly testing these 6 cognitive dimensions:
  1. Detail: Specific technical fact, SLA metric, or system configuration mentioned in the text.
  2. Purpose: Strategic or communicative purpose of a specific clause, proposal, or section.
  3. Inference: Unstated technical implication, risk, or prerequisite deduced from context.
  4. Tone/Strategy: Diplomatic framing, risk hedging, or persuasion strategy used by the author.
  5. Vocab in Context: How a specific technical or professional term functions in the document.
  6. Next Action: Concrete operational next step, assigned owner, or milestone trigger.
- Teacher Note: Reading comprehension strategy note ({{en, vi, ja}}) for skimming and analyzing executive documentation.

5. DIALOGUE (Professional Meeting & Technical Negotiation):
- Context: Setting up the meeting agenda, stakeholder dynamics, and business stakes ({{en, vi, ja}}).
- Negotiation Turns: Exactly 8-10 substantial turns (25-45 words each in EN, and matching VI/JA) between 2-3 named workplace personas with distinct roles (e.g., Sarah Chen - Staff Architect; Marcus Vance - Engineering Manager; Elena Rostova - Lead SRE).
- Authentic Spoken Cadence: Must depict an authentic negotiation with realistic pushback, competing goals, and diplomatic concessions. Use natural conversational markers ("With all due respect...", "That's a valid concern, however...", "If we benchmark this against our baseline...", "From an operational maintenance perspective...").
- Natural Phrase Integration: Naturally weave the target phrases from phrases.items into the dialogue in fully completed form (WITHOUT "{{{{completion}}}}" or ellipses).
- Key Phrases: Exactly 4 key_phrases referencing phrase_id, with why_it_works (20-30 words in EN, VI, JA) explaining the communicative persuasion technique and professional impact.
- Practice Tasks: Exactly 4 practice_tasks ordered ask, ask, reply, reply.
  * CRITICAL DEDUPLICATION RULE: In dialogue.practice_tasks, each suggested_completion ({{en, vi, ja}}) MUST be a completely different workplace completion from the example_completion of that phrase in phrases.items! NEVER copy or repeat example_completion in suggested_completion!
- Teacher Note: Communication coach's note ({{en, vi, ja}}) on active listening, de-escalating friction, and steering meetings toward actionable consensus.

6. LISTENING (Executive Monologue & Auditory Comprehension):
- Speaker: Senior executive or technical authority (e.g., VP of Engineering, Principal Systems Architect, Head of Product).
- Script: Monologue of 160-220 words in EN (and matching equivalents in VI and JA).
  * Spoken Discourse Style: Natural presentation delivery featuring oral signposting ("First, let me clarify where we stand...", "The crux of our current dilemma is...", "To put this into perspective...", "Here is what we must achieve in this sprint...").
  * Dense Information: Rich in quantitative metrics, architecture trade-offs, business milestones, and decisive technical directives.
- Comprehension Q&A: Exactly 4 Q&A pairs ({{en, vi, ja}}):
  * Q1: Primary architectural or strategic objective announced.
  * Q2: Concrete numerical metric, SLA threshold, or timeline stated.
  * Q3: Critical business risk or constraint emphasized.
  * Q4: Immediate operational directive given to the engineering team.
- Teacher Note: Auditory strategy note ({{en, vi, ja}}) explaining how to track verbal emphasis, identify transition signals, and filter critical directives from background context.

7. WRAPUP (Synthesis & Workplace Simulation Challenge):
- Takeaways: Exactly 4 executive takeaways ({{en, vi, ja}}) synthesizing key technical concepts, linguistic patterns, and negotiation strategies taught in the lesson.
- Action Task: Realistic workplace simulation challenge ({{en, vi, ja}}) specifying:
  * Persona / Role: (e.g., Senior Backend Engineer).
  * Target Audience: (e.g., CTO and Cross-Functional Product Lead).
  * Workplace Challenge: Realistic dilemma requiring diplomatic technical communication.
  * Deliverable: Specific communication output (e.g., a 3-paragraph executive memo or architectural justification).
  * Linguistic Goal: Mandatory application of specific target phrase patterns and lesson vocabulary.
- Teacher Note: Final pedagogical summary ({{en, vi, ja}}) on practical career application.

[SILENT FINAL QUALITY CHECK]
Before returning the JSON, verify:
1. schema_version is 4, all required fields have en, vi, ja.
2. NO vocabulary term duplicates or overlaps with any term in Banned Vocabulary from Prior Lessons.
3. NO phrase stem duplicates or closely mimics any stem in Banned Phrase Stems from Prior Lessons.
4. NO stock boilerplate phrases used anywhere.
5. All phrases (p1-p{num_patterns}) have concise stems (6-10 words, max 12) and concise example_completions (3-7 words, max 8).
6. Every phrase meaning.vi and meaning.ja contains exactly one '...' placeholder slot.
7. Directly substituting example_completion into meaning at '...' creates a fluent, natural sentence without any parentheses '()'.
8. All {num_vocab} vocab items have accurate IPA, part of speech, and pure Hiragana reading.
9. Reading document matches designated genre with exactly 3 sections and 6 cognitive Q&A items.
10. Dialogue has 8-10 turns, exactly 4 key phrases, and 4 practice tasks (ask, ask, reply, reply).
11. Practice task suggested completions are completely distinct from phrase example completions.
12. Every Kanji compound in Japanese has valid bracketed furigana [Kanji|reading].
13. Valid JSON syntax, single quotes preferred inside text, output only JSON."""

# Backward-compatibility alias
PROMPT_C1_V4_TEMPLATE = PROMPT_C1_TEMPLATE


def build_numbered_skeleton(n: int, label: str) -> str:
    return " # ".join(f"{label} {i}: [complete item {i}]" for i in range(1, n + 1))


def build_prompt_c1(
    *,
    role: str,
    job_description: str,
    parent_topic: str,
    lesson_title: str,
    primary_skill: str,
    difficulty_tier: str,
    skill_definitions: dict[str, dict[str, str | list[str]]],
    topic_learning_goal: str | None = None,
    lesson_sequence: str | None = None,
    current_lesson_position: str | None = None,
    previous_lesson_key_concepts: str | None = None,
    current_lesson_focus: str | None = None,
    next_lesson_key_concepts: str | None = None,
    banned_terms: list[str] | str | None = None,
    banned_phrases: list[str] | str | None = None,
    reading_doc_type: str | None = None,
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
    schema_version: int = 4,
) -> str:
    """Build the Prompt C-1 payload (7-section theory content for one lesson)."""
    if isinstance(banned_terms, list):
        banned_terms_block = (
            ", ".join(f'"{t.strip().strip(chr(34))}"' for t in banned_terms if t and t.strip())
            if banned_terms
            else "None (No prior terms recorded)"
        )
    else:
        banned_terms_block = banned_terms or "None (No prior terms recorded)"

    if isinstance(banned_phrases, list):
        banned_phrases_block = "; ".join(banned_phrases) if banned_phrases else "None (No prior phrases recorded)"
    else:
        banned_phrases_block = banned_phrases or "None (No prior phrases recorded)"

    resolved_reading_doc = (
        reading_doc_type
        or "Slack Channel Discussion Thread or Technical Specification"
    )

    # Focus skill definitions on the lesson's target primary_skill to save tokens
    target_skill_item = (skill_definitions or {}).get(primary_skill) or {}
    target_desc = str(target_skill_item.get("description", "")).strip()
    skill_title = SKILL_TITLES.get(primary_skill, primary_skill)
    skill_definitions_block = (
        f"[PRIMARY SKILL: {primary_skill} ({skill_title})]\n{target_desc}"
        if target_desc
        else ""
    )

    template = PROMPT_C1_TEMPLATE

    return template.format(
        role=role,
        job_description=get_job_description_text(job_description, "en"),
        parent_topic=parent_topic,
        lesson_title=lesson_title,
        primary_skill=primary_skill,
        difficulty_tier=difficulty_tier,
        skill_definitions_block=skill_definitions_block,
        topic_learning_goal=topic_learning_goal
        or f"Master practical workplace communication for '{parent_topic}' ({primary_skill}) in {role} contexts.",
        lesson_sequence=lesson_sequence or f"[1] {lesson_title}",
        current_lesson_position=current_lesson_position or "Lesson 1 of 1",
        previous_lesson_key_concepts=previous_lesson_key_concepts
        or "None (Initial foundational lesson of this topic)",
        current_lesson_focus=current_lesson_focus
        or f"Focus on '{lesson_title}' at {difficulty_tier} tier: practical workplace communication, terminology, and interaction patterns for {role}.",
        next_lesson_key_concepts=next_lesson_key_concepts
        or "None (Capstone / standalone lesson in this topic)",
        banned_terms_block=banned_terms_block,
        banned_phrases_block=banned_phrases_block,
        reading_doc_type=resolved_reading_doc,
        num_vocab=num_vocab,
        num_patterns=num_patterns,
        pattern_functions_block="\n".join(C1_PATTERN_FUNCTIONS[:num_patterns]),
    )


def retry_prompt_c1(original_prompt: str, parse_error: str) -> str:
    """Re-send the C-1 prompt with the parser error message (spec 8.1)."""
    return (
        original_prompt
        + "\n\n[VALIDATION FEEDBACK]\nYour previous response failed validation:\n"
        + parse_error
        + "\nPlease fix the issues and output ONLY the corrected JSON object. "
        "Remember: single quotes inside strings, never unescaped double quotes."
    )

