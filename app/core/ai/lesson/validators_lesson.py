"""Validators for Generator C — Lesson Content output.

Validates theory content (C-1) with trilingual field checks, practice task
validation, and quiz content (C-2) including fill-blank, multi-select, ordering.
"""

import re
from typing import Any

from app.core.ai.lesson.furigana_validator import is_japanese_script, repair_theory_furigana, validate_theory_furigana
from app.core.ai.lesson.c1_enrichment import render_task_suggested_answer
from app.core.infra.config import app_config

C1_SECTION_ORDER = [
    "scenario",
    "vocab",
    "phrases",
    "reading",
    "dialogue",
    "listening",
    "wrapup",
]
NUM_VOCAB = app_config.NUM_VOCAB
NUM_PATTERNS = app_config.NUM_PATTERNS
VALID_PHRASE_IDS = tuple(f"p{i}" for i in range(1, NUM_PATTERNS + 1))
MIN_DIALOGUE_KEY_PHRASES = 1

STOCK_BANNED_PHRASES: list[str] = [
    "What technical implications arise if {{completion}}?",
    "Establishing clear failover thresholds prevents {{completion}}.",
    "Prioritizing throughput over latency necessitates {{completion}}.",
    "Under what criteria should the team {{completion}}?",
    "How does the revised protocol accommodate {{completion}}?",
    "Any unmitigated regression in query speed risks {{completion}}.",
    "Could you clarify how {{completion}}?",
    "Decoupling worker processes helps isolate {{completion}}.",
    "Adopting an asynchronous circuit breaker mitigates {{completion}}.",
    "Formal validation by security leads confirms {{completion}}.",
    "To what extent will the pipeline tolerate {{completion}}?",
    "Which trade-off takes priority if {{completion}}?",
    "From a reliability standpoint, how do we validate {{completion}}?",
    "Would it be feasible to explore {{completion}}?",
    "Under what criteria should the team evaluate {{completion}}?",
]

STOCK_BANNED_PREFIXES: list[str] = [
    "what technical implications arise",
    "establishing clear failover thresholds",
    "prioritizing throughput over latency",
    "under what criteria should",
    "how does the revised protocol",
    "any unmitigated regression in",
    "could you clarify how",
    "decoupling worker processes helps",
    "adopting an asynchronous circuit",
    "formal validation by security",
    "to what extent will the pipeline",
    "would it be feasible to explore",
    "which trade-off takes priority",
    "from a reliability standpoint how",
]


def repair_stem_templates(content: dict) -> None:
    """Normalize phrase stem templates so minor LLM token variations
    (e.g., {completion}, <completion>, [completion], ..., …) are auto-corrected
    to canonical '{{completion}}' before validation instead of failing generation."""
    if not isinstance(content, dict):
        return
    phrases = content.get("phrases")
    if not isinstance(phrases, dict):
        return
    items = phrases.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        stem = str(item.get("stem_template") or "").strip()
        if not stem:
            stem = str(item.get("phrase") or "").strip()
        if not stem:
            continue

        # 1. Normalize token variations to {{completion}}
        if "{completion}" in stem and "{{completion}}" not in stem:
            stem = stem.replace("{completion}", "{{completion}}")
        elif "<completion>" in stem:
            stem = stem.replace("<completion>", "{{completion}}")
        elif "[completion]" in stem:
            stem = stem.replace("[completion]", "{{completion}}")
        elif "{{{completion}}}" in stem or "{{{{completion}}}}" in stem:
            stem = re.sub(r"\{{3,}completion\}{3,}", "{{completion}}", stem)
        elif ("..." in stem or "…" in stem) and "{{completion}}" not in stem:
            stem = stem.replace("...", "{{completion}}").replace("…", "{{completion}}")

        # 2. If {{completion}} is still missing:
        if "{{completion}}" not in stem:
            if stem.endswith("?"):
                stem = stem[:-1].rstrip() + " {{completion}}?"
            elif stem.endswith("."):
                stem = stem[:-1].rstrip() + " {{completion}}."
            else:
                stem = stem + " {{completion}}"

        # 3. Speech act punctuation auto-repair
        act = str(item.get("speech_act") or "")
        if act in ("inquiry", "clarification") and not stem.endswith("?"):
            if stem.endswith("."):
                stem = stem[:-1] + "?"
            else:
                stem = stem + "?"
        elif act in ("proposal", "recommendation", "risk_mitigation", "confirmation") and stem.endswith("?"):
            stem = stem[:-1] + "."

        item["stem_template"] = stem


def repair_practice_tasks(content: dict) -> None:
    """If model duplicates example_completion into suggested_completion for a practice task,
    or repeats the stem prefix, auto-repair and differentiate it so the 15,000-token generation
    does not get rejected."""
    if not isinstance(content, dict):
        return
    phrases = content.get("phrases")
    dialogue = content.get("dialogue")
    if not isinstance(phrases, dict) or not isinstance(dialogue, dict):
        return
    p_items = phrases.get("items", [])
    if not isinstance(p_items, list):
        return
    phrase_dict = {item.get("id"): item for item in p_items if isinstance(item, dict) and item.get("id")}
    tasks = dialogue.get("practice_tasks", [])
    if not isinstance(tasks, list):
        return

    for t_idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        pid = task.get("phrase_id")
        if not pid or pid not in phrase_dict:
            continue
        p_item = phrase_dict[pid]
        stem = str(p_item.get("stem_template") or "").strip()
        ex_comp_raw = p_item.get("example_completion")
        s_comp_val = task.get("suggested_completion")

        ex_en = str(ex_comp_raw.get("en") if isinstance(ex_comp_raw, dict) else ex_comp_raw or "").strip()
        s_en = str(s_comp_val.get("en") if isinstance(s_comp_val, dict) else s_comp_val or "").strip()

        # Auto-strip stem prefix if LLM repeated the whole sentence
        prefix = stem.partition("{{completion}}")[0].strip()
        if prefix and s_en.lower().startswith(prefix.lower()):
            stripped = s_en[len(prefix):].strip()
            if stripped:
                s_en = stripped
                if isinstance(s_comp_val, dict):
                    s_comp_val["en"] = s_en
                else:
                    task["suggested_completion"] = s_en

        rendered_ans = render_task_suggested_answer(stem, s_en).strip()
        rendered_ex = render_task_suggested_answer(stem, ex_en).strip()

        # Differentiate if identical
        if (ex_en and s_en and ex_en.lower() == s_en.lower()) or (rendered_ex and rendered_ans and rendered_ex.lower() == rendered_ans.lower()):
            diff_en = f"{s_en} as an immediate mitigation"
            if isinstance(s_comp_val, dict):
                s_comp_val["en"] = diff_en
                if "vi" in s_comp_val and s_comp_val["vi"]:
                    s_comp_val["vi"] = f"{s_comp_val['vi']} như một biện pháp giảm thiểu ngay lập tức"
                if "ja" in s_comp_val and s_comp_val["ja"]:
                    s_comp_val["ja"] = f"[緊急|きんきゅう]の[緩和策|かんわさく]として{s_comp_val['ja']}"
            else:
                task["suggested_completion"] = diff_en
            s_en = diff_en

        # Fix punctuation for ask vs reply
        t_type = str(task.get("type") or "").lower()
        if t_type == "ask":
            if stem.endswith("?"):
                if s_en.endswith("?") or s_en.endswith("."):
                    s_en = s_en[:-1].rstrip()
            else:
                if not s_en.endswith("?"):
                    s_en = s_en.rstrip(".") + "?"
            if isinstance(s_comp_val, dict):
                s_comp_val["en"] = s_en
            else:
                task["suggested_completion"] = s_en
        elif t_type == "reply" and s_en.endswith("?"):
            s_en = s_en[:-1] + "."
            if isinstance(s_comp_val, dict):
                s_comp_val["en"] = s_en
            else:
                task["suggested_completion"] = s_en


def validate_theory_content(
    content: Any,
    banned_terms: list[str] | str | None = None,
    banned_phrases: list[str] | str | None = None,
    sibling_banned_phrases: list[str] | str | None = None,
) -> dict:
    """
    Validate the Prompt C-1 output (7-section theory content).
    Supports both structured JSON object (new standard) and canonical
    7-section rows / legacy 8-section rows (backward compatibility).

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    banned_terms_list: list[str] = []
    if banned_terms:
        if isinstance(banned_terms, str):
            raw_splits = re.split(r"[,;]", banned_terms)
            banned_terms_list = [
                b.strip().strip('"\'')
                for b in raw_splits
                if b.strip() and b.strip().strip('"\'').lower() != "none"
            ]
        elif isinstance(banned_terms, list):
            banned_terms_list = [
                b.strip().strip('"\'')
                for b in banned_terms
                if b and b.strip() and b.strip().strip('"\'').lower() != "none"
            ]

    banned_phrases_list: list[str] = []
    if banned_phrases:
        if isinstance(banned_phrases, str):
            banned_phrases_list = [
                b.strip().strip('"\'')
                for b in banned_phrases.split(";")
                if b.strip() and b.strip().lower() != "none"
            ]
        elif isinstance(banned_phrases, list):
            banned_phrases_list = [
                b.strip().strip('"\'')
                for b in banned_phrases
                if b and b.strip() and b.strip().lower() != "none"
            ]

    sibling_banned_list: list[str] = []
    if sibling_banned_phrases:
        if isinstance(sibling_banned_phrases, str):
            sibling_banned_list = [
                b.strip().strip('"\'')
                for b in sibling_banned_phrases.split(";")
                if b.strip() and b.strip().lower() != "none"
            ]
        elif isinstance(sibling_banned_phrases, list):
            sibling_banned_list = [
                b.strip().strip('"\'')
                for b in sibling_banned_phrases
                if b and b.strip() and b.strip().lower() != "none"
            ]

    if isinstance(content, dict):
        repair_stem_templates(content)
        repair_theory_furigana(content)
        repair_practice_tasks(content)
        for expected in C1_SECTION_ORDER:
            if expected not in content:
                errors.append(f"Missing top-level section key: '{expected}'")

        if errors:
            return {"ok": False, "errors": errors, "warnings": warnings}

        # Validate schema_version if present
        sv = content.get("schema_version", 2)
        if "schema_version" in content:
            if sv not in (2, 3, 4):
                errors.append(f"schema_version: expected 2, 3, or 4, got {sv}")

        # Validate scenario
        sc = content.get("scenario")
        if not isinstance(sc, dict):
            errors.append("Section 'scenario' must be an object")
        else:
            if sv >= 4:
                if not sc.get("en") and not sc.get("english_text"):
                    errors.append("scenario: 'en' is required in trilingual schema")
                if not sc.get("vi") and not sc.get("vietnamese_text"):
                    errors.append("scenario: 'vi' is required in trilingual schema")
                if not sc.get("ja") and not sc.get("japanese_text"):
                    errors.append("scenario: 'ja' is required in trilingual schema")
                elif not is_japanese_script(str(sc.get("ja") or sc.get("japanese_text") or "")):
                    errors.append("scenario: 'ja' must contain Japanese characters")
            else:
                if not sc.get("english_text") and not sc.get("en"):
                    errors.append("scenario: 'english_text' is required")
            decisions = sc.get("decisions")
            if not isinstance(decisions, list) or len(decisions) != 3:
                warnings.append(f"scenario: expected 3 decisions, got {len(decisions) if isinstance(decisions, list) else 0}")

        # Validate vocab
        vb = content.get("vocab")
        if not isinstance(vb, dict):
            errors.append("Section 'vocab' must be an object")
        else:
            v_items = vb.get("items")
            if not isinstance(v_items, list) or len(v_items) == 0:
                errors.append("vocab: 'items' must be a non-empty array")
            elif len(v_items) != NUM_VOCAB:
                warnings.append(f"vocab: expected {NUM_VOCAB} items, got {len(v_items)}")
            seen_vocab_terms: set[str] = set()
            for v_idx, v_it in enumerate(v_items):
                if not isinstance(v_it, dict):
                    errors.append(f"vocab.items[{v_idx}]: must be an object")
                    continue
                term_val = v_it.get("term")
                term_en = ""
                if isinstance(term_val, dict):
                    if sv >= 4:
                        if not term_val.get("en") or not term_val.get("vi") or not term_val.get("ja"):
                            errors.append(f"vocab.items[{v_idx}].term: must contain non-empty 'en', 'vi', and 'ja'")
                        elif not is_japanese_script(term_val.get("ja", "")):
                            errors.append(f"vocab.items[{v_idx}].term.ja: must contain Japanese characters")
                    term_en = str(term_val.get("en") or "").strip()
                elif term_val:
                    term_en = str(term_val).strip()
                else:
                    errors.append(f"vocab.items[{v_idx}]: 'term' is required")
                    continue

                if sv >= 4 and not v_it.get("reading"):
                    errors.append(f"vocab.items[{v_idx}]: 'reading' (Hiragana) is required")

                if term_en:
                    term_norm = term_en.lower()
                    if term_norm in seen_vocab_terms:
                        errors.append(f"vocab.items[{v_idx}]: duplicate term '{term_en}' within the same lesson")
                    seen_vocab_terms.add(term_norm)

                    if banned_terms_list:
                        clean_term = re.sub(r"[^\w\s-]", "", term_norm).strip()
                        for b in banned_terms_list:
                            clean_b = re.sub(r"[^\w\s-]", "", b.lower()).strip()
                            if not clean_term or not clean_b:
                                continue
                            is_dup = False
                            if clean_term == clean_b:
                                is_dup = True
                            elif len(clean_term) >= 4 and len(clean_b) >= 4 and clean_term.rstrip("s") == clean_b.rstrip("s"):
                                is_dup = True
                            elif len(clean_term) >= 5 and len(clean_b) >= 5 and clean_term.rstrip("ing") == clean_b.rstrip("ing"):
                                is_dup = True

                            if is_dup:
                                warnings.append(
                                    f"vocab.items[{v_idx}].term ('{term_en}'): duplicates or closely mimics vocabulary from a prior lesson: '{b}'."
                                )
                                break

        # Validate phrases
        ph = content.get("phrases")
        phrase_dict: dict[str, dict] = {}
        if not isinstance(ph, dict):
            errors.append("Section 'phrases' must be an object")
        else:
            p_items = ph.get("items")
            if not isinstance(p_items, list) or len(p_items) == 0:
                errors.append("phrases: 'items' must be a non-empty array")
            elif len(p_items) != NUM_PATTERNS:
                errors.append(f"phrases: expected exactly {NUM_PATTERNS} items, got {len(p_items)}")
            else:
                seen_ids: set[str] = set()
                seen_stems: set[str] = set()
                for idx, item in enumerate(p_items):
                    if not isinstance(item, dict):
                        errors.append(f"phrases.items[{idx}]: must be an object")
                        continue
                    pid = item.get("id")
                    if not pid or pid not in VALID_PHRASE_IDS:
                        errors.append(f"phrases.items[{idx}]: invalid or missing 'id' ('{pid}'). Must be one of 'p1'..'p{NUM_PATTERNS}'")
                    elif pid in seen_ids:
                        errors.append(f"phrases.items[{idx}]: duplicate id '{pid}'")
                    else:
                        seen_ids.add(pid)
                        phrase_dict[pid] = item

                    stem = str(item.get("stem_template") or "").strip()
                    if not stem:
                        errors.append(f"phrases.items[{idx}]: 'stem_template' is required and cannot be empty")
                    else:
                        if "..." in stem or "…" in stem:
                            errors.append(f"phrases.items[{idx}] ('{stem}'): canonical template cannot contain '...'; must use token '{{{{completion}}}}'")
                        token_count = stem.count("{{completion}}")
                        if token_count == 0:
                            errors.append(f"phrases.items[{idx}] ('{stem}'): template must contain exactly one '{{{{completion}}}}' token (found 0)")
                        elif token_count > 1:
                            errors.append(f"phrases.items[{idx}] ('{stem}'): template contains multiple '{{{{completion}}}}' tokens (found {token_count})")
                        else:
                            prefix, suffix = stem.split("{{completion}}")
                            if not prefix.strip() and not suffix.strip():
                                errors.append(f"phrases.items[{idx}] ('{stem}'): template cannot be just '{{{{completion}}}}'")

                        stem_norm = stem.lower()
                        if stem_norm in seen_stems:
                            errors.append(f"phrases.items[{idx}]: duplicate stem_template '{stem}'")
                        seen_stems.add(stem_norm)

                        clean_stem = re.sub(r"[^\w\s]", "", stem.replace("{{completion}}", "").replace("...", "")).strip().lower()
                        stem_words = clean_stem.split()

                        # 1. Hard error: Stock boilerplate phrases and stock prefixes
                        is_stock = False
                        for sp in STOCK_BANNED_PHRASES:
                            clean_sp = re.sub(r"[^\w\s]", "", sp.replace("{{completion}}", "").replace("...", "")).strip().lower()
                            if clean_stem == clean_sp or (len(clean_sp) >= 15 and (clean_stem.startswith(clean_sp) or clean_sp.startswith(clean_stem))):
                                is_stock = True
                                break
                        if not is_stock:
                            for pfx in STOCK_BANNED_PREFIXES:
                                if clean_stem.startswith(pfx):
                                    is_stock = True
                                    break
                        if is_stock:
                            errors.append(
                                f"phrases.items[{idx}] ('{stem}'): uses blacklisted generic stock template. Every phrase must be fresh, unique, and tailored to the specific lesson topic."
                            )

                        # 2. Hard error: Duplicate phrase from an earlier sibling lesson in the same topic
                        if sibling_banned_list:
                            for b in sibling_banned_list:
                                clean_b = re.sub(r"[^\w\s]", "", b.replace("{{completion}}", "").replace("...", "")).strip().lower()
                                b_words = clean_b.split()
                                is_dup = False
                                if clean_stem and clean_b:
                                    if clean_stem == clean_b:
                                        is_dup = True
                                    elif len(clean_b) >= 12 and (clean_stem.startswith(clean_b) or clean_b.startswith(clean_stem)):
                                        is_dup = True
                                    elif len(stem_words) >= 4 and len(b_words) >= 4 and stem_words[:4] == b_words[:4]:
                                        is_dup = True
                                if is_dup:
                                    errors.append(
                                        f"phrases.items[{idx}] ('{stem}'): duplicate phrase from an earlier lesson in this topic: '{b}'. Each lesson in this topic must teach completely distinct phrase structures."
                                    )
                                    break

                        # 3. Soft warning: Cross-topic historical phrase overlap
                        if banned_phrases_list:
                            for b in banned_phrases_list:
                                clean_b = re.sub(r"[^\w\s]", "", b.replace("{{completion}}", "").replace("...", "")).strip().lower()
                                b_words = clean_b.split()
                                is_dup = False
                                if clean_stem and clean_b:
                                    if clean_stem == clean_b:
                                        is_dup = True
                                    elif len(clean_b) >= 12 and (clean_stem.startswith(clean_b) or clean_b.startswith(clean_stem)):
                                        is_dup = True
                                    elif len(stem_words) >= 4 and len(b_words) >= 4 and stem_words[:4] == b_words[:4]:
                                        is_dup = True
                                if is_dup:
                                    warnings.append(
                                        f"phrases.items[{idx}] ('{stem}'): duplicates or closely mimics a phrase from a prior lesson: '{b}'."
                                    )
                                    break

                        act = item.get("speech_act", "")
                        if act in ("inquiry", "clarification"):
                            if not stem.endswith("?"):
                                errors.append(f"phrases.items[{idx}]: speech_act='{act}' requires stem_template to end with '?'")
                        elif act in ("proposal", "recommendation", "risk_mitigation", "confirmation"):
                            if stem.endswith("?"):
                                errors.append(f"phrases.items[{idx}]: speech_act='{act}' is a statement and must NOT end with '?'")
                            stem_l = stem.lower()
                            if any(stem_l.startswith(ps) for ps in ("i ", "we ", "let's ", "you ")):
                                warnings.append(
                                    f"phrases.items[{idx}]: statement template ('{stem}') starts with a personal pronoun ('I', 'We', 'Let's', 'You'). Executive/professional framing preferred."
                                )
                        else:
                            errors.append(f"phrases.items[{idx}]: invalid speech_act='{act}'")

                        ex_comp_val = item.get("example_completion")
                        if isinstance(ex_comp_val, dict):
                            ex_comp = str(ex_comp_val.get("en") or "").strip()
                        else:
                            ex_comp = str(ex_comp_val or "").strip()

                        if not ex_comp:
                            errors.append(f"phrases.items[{idx}]: 'example_completion' is required and cannot be empty")
                        elif "{{completion}}" in ex_comp:
                            errors.append(f"phrases.items[{idx}]: 'example_completion' contains unexpanded '{{{{completion}}}}' token")

            p_mini = ph.get("mini_scenarios")
            if not isinstance(p_mini, list) or len(p_mini) != 3:
                errors.append(f"phrases: expected exactly 3 mini_scenarios, got {len(p_mini) if isinstance(p_mini, list) else 0}")
            else:
                for m_idx, sc in enumerate(p_mini):
                    if not isinstance(sc, dict):
                        errors.append(f"phrases.mini_scenarios[{m_idx}]: must be an object")
                        continue
                    pid = sc.get("phrase_id")
                    if not pid or pid not in phrase_dict:
                        errors.append(f"phrases.mini_scenarios[{m_idx}]: invalid phrase_id '{pid}', not found in phrases.items")

        # Validate reading
        rd = content.get("reading")
        if not isinstance(rd, dict):
            errors.append("Section 'reading' must be an object")
        else:
            doc = rd.get("document")
            if not doc:
                errors.append("reading: 'document' is required")
            elif not isinstance(doc, dict):
                errors.append("reading.document: must be a structured JSON object containing 'sections' (not a raw string)")
            else:
                doc_type = doc.get("doc_type")
                if not doc_type or not str(doc_type).strip():
                    errors.append("reading.document: 'doc_type' is required and cannot be empty")
                title = doc.get("title")
                if not title or not str(title).strip():
                    errors.append("reading.document: 'title' is required and cannot be empty")

                metadata = doc.get("metadata")
                if metadata is not None:
                    if not isinstance(metadata, list):
                        errors.append("reading.document: 'metadata' must be a list of {key, value} objects")
                    else:
                        for m_idx, meta in enumerate(metadata):
                            if not isinstance(meta, dict):
                                errors.append(f"reading.document.metadata[{m_idx}]: must be an object with 'key' and 'value'")
                                continue
                            if not str(meta.get("key", "")).strip():
                                errors.append(f"reading.document.metadata[{m_idx}]: 'key' cannot be empty")
                            val = meta.get("value")
                            if isinstance(val, dict):
                                if sv >= 4 and (not val.get("en") or not val.get("vi") or not val.get("ja")):
                                    errors.append(f"reading.document.metadata[{m_idx}].value: must contain non-empty 'en', 'vi', and 'ja'")
                            elif not str(val or "").strip():
                                errors.append(f"reading.document.metadata[{m_idx}]: 'value' cannot be empty")

                sections = doc.get("sections")
                if not isinstance(sections, list) or len(sections) == 0:
                    errors.append("reading.document: 'sections' must be a non-empty list of section objects")
                else:
                    for s_idx, sec in enumerate(sections):
                        if not isinstance(sec, dict):
                            errors.append(f"reading.document.sections[{s_idx}]: must be an object")
                            continue
                        heading_val = sec.get("heading")
                        if isinstance(heading_val, dict):
                            if sv >= 4 and (not heading_val.get("en") or not heading_val.get("vi") or not heading_val.get("ja")):
                                errors.append(f"reading.document.sections[{s_idx}].heading: must contain non-empty 'en', 'vi', and 'ja'")
                            heading_str = str(heading_val.get("en") or "").strip()
                        else:
                            heading_str = str(heading_val or "").strip()
                        if not heading_str:
                            errors.append(f"reading.document.sections[{s_idx}]: 'heading' is required and cannot be empty")

                        sec_type = sec.get("type")
                        if sec_type not in ("paragraph", "bullet", "numbered", "chat"):
                            errors.append(
                                f"reading.document.sections[{s_idx}]: invalid type '{sec_type}'. "
                                f"Must be one of: 'paragraph', 'bullet', 'numbered', 'chat'"
                            )
                            continue

                        # Strict Discriminated Union Rules
                        if sec_type == "paragraph":
                            content_val = sec.get("content")
                            if isinstance(content_val, dict):
                                if sv >= 4 and (not content_val.get("en") or not content_val.get("vi") or not content_val.get("ja")):
                                    errors.append(f"reading.document.sections[{s_idx}].content: must contain non-empty 'en', 'vi', and 'ja'")
                                content_str = str(content_val.get("en") or "").strip()
                            elif isinstance(content_val, str):
                                content_str = content_val.strip()
                            else:
                                content_str = ""

                            if not content_str or len(content_str) < 20:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='paragraph' requires non-empty content (min 20 characters)"
                                )
                            if "items" in sec and sec["items"] is not None:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='paragraph' forbids 'items'"
                                )
                            # Anti-placeholder check
                            if content_str and "workplace document content" in content_str.lower():
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: synthetic placeholder content ('Workplace document content') is forbidden"
                                )

                        elif sec_type in ("bullet", "numbered"):
                            items = sec.get("items")
                            if not isinstance(items, list) or len(items) == 0:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='{sec_type}' requires non-empty items (min 1 item)"
                                )
                            else:
                                for i_idx, item in enumerate(items):
                                    if isinstance(item, dict):
                                        if sv >= 4 and (not item.get("en") or not item.get("vi") or not item.get("ja")):
                                            errors.append(f"reading.document.sections[{s_idx}].items[{i_idx}]: must contain non-empty 'en', 'vi', and 'ja'")
                                        item_str = str(item.get("en") or "").strip()
                                    elif isinstance(item, str):
                                        item_str = item.strip()
                                    else:
                                        item_str = ""
                                    if not item_str:
                                        errors.append(
                                            f"reading.document.sections[{s_idx}].items[{i_idx}]: must be a non-empty string or trilingual object"
                                        )
                            if "content" in sec and sec["content"] is not None:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='{sec_type}' forbids 'content'"
                                )

                        elif sec_type == "chat":
                            items = sec.get("items")
                            if not isinstance(items, list) or len(items) == 0:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='chat' requires non-empty items (min 1 item)"
                                )
                            else:
                                for i_idx, item in enumerate(items):
                                    if not isinstance(item, dict):
                                        errors.append(
                                            f"reading.document.sections[{s_idx}].items[{i_idx}]: must be an object with sender and text"
                                        )
                                    else:
                                        sender = item.get("sender")
                                        text_val = item.get("text")
                                        if not sender or not str(sender).strip():
                                            errors.append(
                                                f"reading.document.sections[{s_idx}].items[{i_idx}]: 'sender' must be a non-empty string"
                                            )
                                        if isinstance(text_val, dict):
                                            if sv >= 4 and (not text_val.get("en") or not text_val.get("vi") or not text_val.get("ja")):
                                                errors.append(f"reading.document.sections[{s_idx}].items[{i_idx}].text: must contain non-empty 'en', 'vi', and 'ja'")
                                            text_str = str(text_val.get("en") or "").strip()
                                        elif isinstance(text_val, str):
                                            text_str = text_val.strip()
                                        else:
                                            text_str = ""
                                        if not text_str:
                                            errors.append(
                                                f"reading.document.sections[{s_idx}].items[{i_idx}]: 'text' must be a non-empty string"
                                            )
                            if "content" in sec and sec["content"] is not None:
                                errors.append(
                                    f"reading.document.sections[{s_idx}]: type='chat' forbids 'content'"
                                )

                # Validate Reading Q&A
                r_qa = rd.get("qa")
                if not isinstance(r_qa, list) or len(r_qa) != 6:
                    errors.append(f"reading: expected exactly 6 Q&A objects, got {len(r_qa) if isinstance(r_qa, list) else 0}")
                else:
                    for q_idx, qa in enumerate(r_qa):
                        if not isinstance(qa, dict):
                            errors.append(f"reading.qa[{q_idx}]: must be an object with 'question' and 'answer'")
                            continue
                        q_raw = qa.get("question")
                        a_raw = qa.get("answer")
                        if isinstance(q_raw, dict):
                            if sv >= 4 and (not q_raw.get("en") or not q_raw.get("vi") or not q_raw.get("ja")):
                                errors.append(f"reading.qa[{q_idx}].question: must contain non-empty 'en', 'vi', and 'ja'")
                            q_str = str(q_raw.get("en") or "").strip()
                        else:
                            q_str = str(q_raw or "").strip()

                        if isinstance(a_raw, dict):
                            if sv >= 4 and (not a_raw.get("en") or not a_raw.get("vi") or not a_raw.get("ja")):
                                errors.append(f"reading.qa[{q_idx}].answer: must contain non-empty 'en', 'vi', and 'ja'")
                            a_str = str(a_raw.get("en") or "").strip()
                        else:
                            a_str = str(a_raw or "").strip()

                        if len(q_str) < 8:
                            errors.append(f"reading.qa[{q_idx}]: 'question' is too short or empty ('{q_str}')")
                        if len(a_str) < 3:
                            errors.append(f"reading.qa[{q_idx}]: 'answer' is too short or empty ('{a_str}')")
                        if "the technical parameters specified in the text" in a_str.lower():
                            errors.append(f"reading.qa[{q_idx}]: contains generic fallback answer placeholder")

        # Validate dialogue
        dl = content.get("dialogue")
        if not isinstance(dl, dict):
            errors.append("Section 'dialogue' must be an object")
        else:
            turns = dl.get("turns")
            if not isinstance(turns, list) or len(turns) == 0:
                errors.append("dialogue: 'turns' must be a non-empty array")
            else:
                for t_idx, turn in enumerate(turns):
                    if not isinstance(turn, dict):
                        errors.append(f"dialogue.turns[{t_idx}]: must be an object")
                        continue
                    line_val = turn.get("line")
                    if isinstance(line_val, dict):
                        if sv >= 4:
                            if not line_val.get("en") or not line_val.get("vi") or not line_val.get("ja"):
                                errors.append(f"dialogue.turns[{t_idx}].line: must contain non-empty 'en', 'vi', and 'ja'")
                            elif not is_japanese_script(line_val.get("ja", "")):
                                errors.append(f"dialogue.turns[{t_idx}].line.ja: must contain Japanese characters")
                        line = str(line_val.get("en") or "").strip()
                    else:
                        line = str(line_val or "").strip()

                    if "..." in line or "…" in line or "{{completion}}" in line:
                        errors.append(f"dialogue.turns[{t_idx}]: spoken line contains forbidden ellipsis or unexpanded slot: '{line}'")
            kp = dl.get("key_phrases")
            if not isinstance(kp, list) or len(kp) != 4:
                errors.append(f"dialogue: expected exactly 4 key_phrases, got {len(kp) if isinstance(kp, list) else 0}")
            else:
                kp_pids = []
                for k_idx, item in enumerate(kp):
                    if not isinstance(item, dict):
                        errors.append(f"dialogue.key_phrases[{k_idx}]: must be an object")
                        continue
                    pid = item.get("phrase_id")
                    if not pid or pid not in phrase_dict:
                        errors.append(f"dialogue.key_phrases[{k_idx}]: invalid phrase_id '{pid}', not found in phrases.items")
                    kp_pids.append(pid)
                if len(kp_pids) == 4 and len(set(kp_pids)) < 4:
                    errors.append("dialogue: key_phrases cannot contain duplicate phrase_id references")

            tasks = dl.get("practice_tasks")
            if not isinstance(tasks, list) or len(tasks) != 4:
                errors.append(f"dialogue: expected exactly 4 practice_tasks, got {len(tasks) if isinstance(tasks, list) else 0}")
            else:
                task_types = [t.get("type", "").lower() for t in tasks if isinstance(t, dict)]
                if task_types != ["ask", "ask", "reply", "reply"]:
                    errors.append(f"dialogue: practice_tasks types must be ['ask', 'ask', 'reply', 'reply'], got {task_types}")

                rendered_answers: list[str] = []
                for t_idx, task in enumerate(tasks):
                    if not isinstance(task, dict):
                        errors.append(f"dialogue.practice_tasks[{t_idx}]: must be an object")
                        continue
                    pid = task.get("phrase_id")
                    if not pid or pid not in phrase_dict:
                        errors.append(f"dialogue.practice_tasks[{t_idx}]: invalid phrase_id '{pid}', not found in phrases.items")
                        continue
                    s_comp_val = task.get("suggested_completion")
                    if isinstance(s_comp_val, dict):
                        s_comp = str(s_comp_val.get("en") or "").strip()
                    else:
                        s_comp = str(s_comp_val or "").strip()

                    if not s_comp:
                        errors.append(f"dialogue.practice_tasks[{t_idx}]: 'suggested_completion' is required and cannot be empty")
                        continue
                    if "{{completion}}" in s_comp:
                        errors.append(f"dialogue.practice_tasks[{t_idx}]: 'suggested_completion' contains unexpanded '{{{{completion}}}}' token")

                    p_item = phrase_dict[pid]
                    ex_comp_raw = p_item.get("example_completion")
                    if isinstance(ex_comp_raw, dict):
                        ex_comp = str(ex_comp_raw.get("en") or "").strip()
                    else:
                        ex_comp = str(ex_comp_raw or "").strip()
                    stem = str(p_item.get("stem_template") or "").strip()

                    # Rule: Workplace Example completion != Suggested completion for same phrase
                    if ex_comp and s_comp and ex_comp.lower() == s_comp.lower():
                        s_comp = f"{s_comp} as an immediate mitigation"
                        if isinstance(s_comp_val, dict):
                            s_comp_val["en"] = s_comp
                        else:
                            task["suggested_completion"] = s_comp

                    # Rule: suggested_completion must not repeat the stem prefix
                    prefix = stem.partition("{{completion}}")[0].strip()
                    if prefix and s_comp.lower().startswith(prefix.lower()):
                        stripped = s_comp[len(prefix):].strip()
                        if stripped:
                            s_comp = stripped
                            if isinstance(s_comp_val, dict):
                                s_comp_val["en"] = s_comp
                            else:
                                task["suggested_completion"] = s_comp

                    rendered_ans = render_task_suggested_answer(stem, s_comp).strip()
                    rendered_ex = render_task_suggested_answer(stem, ex_comp).strip()

                    # Rule: Rendered example != Rendered suggested answer
                    if rendered_ex and rendered_ans and rendered_ex.lower() == rendered_ans.lower():
                        s_comp = f"{s_comp} in production"
                        if isinstance(s_comp_val, dict):
                            s_comp_val["en"] = s_comp
                        else:
                            task["suggested_completion"] = s_comp
                        rendered_ans = render_task_suggested_answer(stem, s_comp).strip()

                    t_type = str(task.get("type") or "").lower()
                    if t_type == "ask" and not rendered_ans.endswith("?"):
                        if not stem.endswith("?"):
                            if isinstance(s_comp_val, dict):
                                s_comp_val["en"] = s_comp.rstrip(".") + "?"
                            else:
                                task["suggested_completion"] = s_comp.rstrip(".") + "?"
                            rendered_ans = render_task_suggested_answer(stem, task.get("suggested_completion", "")).strip()
                        if not rendered_ans.endswith("?"):
                            warnings.append(f"dialogue.practice_tasks[{t_idx}]: task is 'ask' but rendered suggested_answer ('{rendered_ans}') does not end with '?'")
                    elif t_type == "reply" and rendered_ans.endswith("?"):
                        if isinstance(s_comp_val, dict):
                            s_comp_val["en"] = s_comp.rstrip("?") + "."
                        else:
                            task["suggested_completion"] = s_comp.rstrip("?") + "."
                        rendered_ans = render_task_suggested_answer(stem, task.get("suggested_completion", "")).strip()
                        if rendered_ans.endswith("?"):
                            warnings.append(f"dialogue.practice_tasks[{t_idx}]: task is 'reply' but rendered suggested_answer ('{rendered_ans}') ends with '?' (expected statement)")

                    rendered_answers.append(rendered_ans.lower())

                if len(rendered_answers) == 4 and len(set(rendered_answers)) < 4:
                    warnings.append("dialogue: practice_tasks contains duplicate suggested_answer values")

        # Validate listening
        ls = content.get("listening")
        if not isinstance(ls, dict):
            errors.append("Section 'listening' must be an object")
        else:
            script_val = ls.get("script")
            if not script_val:
                errors.append("listening: 'script' is required")
            elif sv >= 4 and isinstance(script_val, dict):
                if not script_val.get("en") or not script_val.get("vi") or not script_val.get("ja"):
                    errors.append("listening.script: must contain non-empty 'en', 'vi', and 'ja'")
                elif not is_japanese_script(script_val.get("ja", "")):
                    errors.append("listening.script.ja: must contain Japanese characters")
            l_qa = ls.get("qa")
            if not isinstance(l_qa, list) or len(l_qa) != 4:
                warnings.append(f"listening: expected 4 Q&A objects, got {len(l_qa) if isinstance(l_qa, list) else 0}")

        # Validate wrapup
        wp = content.get("wrapup")
        if not isinstance(wp, dict):
            errors.append("Section 'wrapup' must be an object")
        else:
            takeaways = wp.get("takeaways")
            if not isinstance(takeaways, list) or len(takeaways) != 4:
                warnings.append(f"wrapup: expected 4 takeaways, got {len(takeaways) if isinstance(takeaways, list) else 0}")

        # Furigana validation for schema_version >= 4 or when Japanese text exists
        f_errs, f_discrepancies = validate_theory_furigana(content)
        errors.extend(f_errs)
        for disc in f_discrepancies:
            warnings.append(
                f"Furigana reading discrepancy for '{disc['kanji']}': model gave '{disc['model_reading']}', dictionary suggests '{disc['dict_reading']}'"
            )

        return {"ok": not errors, "errors": errors, "warnings": warnings, "discrepancies": f_discrepancies}

    errors.append(f"Theory content must be a structured JSON object with 7 sections (got {type(content).__name__})")
    return {"ok": False, "errors": errors, "warnings": warnings, "discrepancies": []}


# ─── Generator C-2: Combined Quiz (30 questions) ──────────────────────────────

NUM_PER_TYPE = app_config.NUM_QUIZ_QUESTIONS_PER_TYPE
C2_TYPES = ["fill_blank", "multi_select", "ordering"]


def validate_quiz_content(obj: Any) -> dict:
    """
    Validate the Prompt C-2 output (30-question lesson quiz).

    Structural hard errors: exactly 3 keys, exactly `num_per_type` arrays per
    key, 4 elements per array, no empty strings, and per-type option/answer
    constraints (fill_blank: correct answer in options on stripped + case-folded
    text; multi_select: 4-5 options with 1-4 non-duplicate in-range indices;
    ordering: 3-6 options with a non-duplicate in-range index sequence of
    length >= 2). Duplicate stems are a warning, not an error (deviation #22).

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(obj, dict):
        errors.append(f"Response is not a JSON object (got {type(obj).__name__})")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if set(obj.keys()) != set(C2_TYPES):
        errors.append(
            f"Quiz must have exactly 3 keys {sorted(C2_TYPES)}, got {sorted(obj.keys())}"
        )

    all_stems: list[str] = []

    for qtype in C2_TYPES:
        items = obj.get(qtype)
        if not isinstance(items, list):
            errors.append(f"'{qtype}' must be a list")
            continue
        if len(items) != NUM_PER_TYPE:
            errors.append(
                f"'{qtype}' has {len(items)} questions, expected {NUM_PER_TYPE}"
            )

        for i, item in enumerate(items):
            if not isinstance(item, list) or len(item) != 4:
                errors.append(f"'{qtype}'[{i}] must have exactly 4 elements")
                continue

            stem, options_str, answer, explanation = item

            if not isinstance(stem, str) or not stem.strip():
                errors.append(f"'{qtype}'[{i}]: stem (Index 0) is empty")
            else:
                all_stems.append(stem.strip())

            if not isinstance(explanation, str) or not explanation.strip():
                errors.append(f"'{qtype}'[{i}]: explanation (Index 3) is empty")

            if qtype == "fill_blank":
                if not isinstance(options_str, str) or options_str.count("|") != 3:
                    errors.append(
                        f"fill_blank[{i}]: options must be exactly 4 (3 pipes)"
                    )
                    continue
                options = [o.strip() for o in options_str.split("|") if o.strip()]
                if not isinstance(answer, str) or not answer.strip():
                    errors.append(f"fill_blank[{i}]: correct answer is empty")
                elif answer.strip().casefold() not in {o.casefold() for o in options}:
                    errors.append(
                        f"fill_blank[{i}]: correct answer must appear in the options "
                        "(compared on stripped, case-folded text)"
                    )
            elif qtype == "multi_select":
                if not isinstance(options_str, str) or not (
                    3 <= options_str.count("|") <= 4
                ):
                    errors.append(f"multi_select[{i}]: options must be 4-5 (3-4 pipes)")
                    continue
                num_options = options_str.count("|") + 1
                _check_index_list(
                    errors,
                    qtype,
                    i,
                    answer,
                    min_count=1,
                    max_count=4,
                    max_index=num_options - 1,
                )
            else:  # ordering
                if not isinstance(options_str, str) or not (
                    2 <= options_str.count("|") <= 5
                ):
                    errors.append(f"ordering[{i}]: options must be 3-6 (2-5 pipes)")
                    continue
                num_options = options_str.count("|") + 1
                _check_index_list(
                    errors,
                    qtype,
                    i,
                    answer,
                    min_count=2,
                    max_count=num_options,
                    max_index=num_options - 1,
                )

    # All 30 stems should be unique strings across the quiz (spec §9 C-2);
    # duplicates are a warning, not a hard error (deviation #22).
    if len(all_stems) != len(set(all_stems)):
        warnings.append(
            f"C-2: {len(all_stems) - len(set(all_stems))} duplicate stem(s) — "
            "all 30 stems (Index 0) should be unique strings across the quiz"
        )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _check_index_list(
    errors: list[str],
    qtype: str,
    i: int,
    answer: Any,
    *,
    min_count: int,
    max_count: int,
    max_index: int,
) -> None:
    """Validate a pipe-separated zero-based index list (multi_select / ordering)."""
    if not isinstance(answer, str):
        errors.append(f"{qtype}[{i}]: answer indices must be a string")
        return
    try:
        indices = [int(x) for x in answer.split("|") if x != ""]
    except ValueError:
        errors.append(f"{qtype}[{i}]: answer indices must be zero-based integers")
        return
    if not (min_count <= len(indices) <= max_count):
        errors.append(
            f"{qtype}[{i}]: expected {min_count}-{max_count} indices, got {len(indices)}"
        )
    if len(set(indices)) != len(indices):
        errors.append(f"{qtype}[{i}]: duplicate indices")
    for idx in indices:
        if not (0 <= idx <= max_index):
            errors.append(f"{qtype}[{i}]: index {idx} out of range (0-{max_index})")
