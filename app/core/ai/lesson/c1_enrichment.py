"""C-1 Theory Content enrichment and normalization.

Post-processing logic for C-1 AI output: text-to-structured-reading parser,
trilingual suggested answer rendering, and canonical object enrichment.

Extracted from prompts.py — these are not prompts but data-processing functions.
"""

import json
import re

def parse_text_to_structured_reading(text: str, default_doc_type: str = "Workplace Technical Document") -> dict:
    """
    Auto-repair: converts raw markdown or plain-text reading content into a
    fully structured JSON document object with doc_type, title, metadata, and sections.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    metadata: list[dict[str, str]] = []
    title = ""
    sections: list[dict] = []
    curr_sec: dict | None = None

    # Detect doc_type if generic
    full_text_lower = text.lower()
    if default_doc_type == "Workplace Technical Document":
        if any(k in full_text_lower for k in ("user story", "acceptance criteria", "jira", "story points")):
            default_doc_type = "Jira User Story & Acceptance Criteria"
        elif any(k in full_text_lower for k in ("incident", "post-mortem", "rca", "root cause")):
            default_doc_type = "Incident Post-Mortem (RCA)"
        elif any(k in full_text_lower for k in ("adr", "decision record", "architecture decision")):
            default_doc_type = "Architecture Decision Record (ADR)"
        elif any(k in full_text_lower for k in ("slack", "teams", "channel:", "#")):
            default_doc_type = "Slack / Teams Discussion Thread"
        elif any(k in full_text_lower for k in ("meeting minutes", "action items", "meeting summary")):
            default_doc_type = "Meeting Minutes & Action Items"
        elif any(k in full_text_lower for k in ("change request", "scope change", "cr-")):
            default_doc_type = "Scope Change Request (CR)"
        elif any(k in full_text_lower for k in ("executive status", "status report")):
            default_doc_type = "Executive Status Report"
        elif any(re.search(r"^(?:from|to|subject):", l, re.I) for l in lines):
            default_doc_type = "Formal Workplace Email"

    meta_re = re.compile(r"^\*{0,2}([A-Za-z0-9_.\-\s/]+):\*{0,2}\s+(.+)$")
    sec_hd_names = (
        "Incident Summary|Root Cause|Corrective Actions|Preventive Measures|"
        "Context & Problem|Context|Decision|Consequences & Trade-offs|Consequences|Trade-offs|"
        "User Story|Acceptance Criteria|Discussion Points|Key Decisions|Action Items|"
        "Live Discussion|Thread Context|Next Steps|Executive Summary|Summary|Background|Notes|"
        "Proposed Change|Business Justification|Impact Analysis|Key Milestones|Risks & Mitigations"
    )
    sec_hd_re = re.compile(rf"^\*{{0,2}}({sec_hd_names}):?\*{{0,2}}(?:\s+(.*))?$", re.I)

    for line in lines:
        if line in ("---", "===") or re.match(r"^Owner\s*&\s*Status:?$", line, re.I):
            continue

        sec_m = sec_hd_re.match(line)
        if sec_m or (line.startswith("##") and not line.startswith("###")):
            heading = sec_m.group(1).strip() if sec_m else line.replace("##", "").strip()
            inline_content = sec_m.group(2).strip() if (sec_m and sec_m.group(2)) else ""
            sec_type = (
                "numbered"
                if "root cause" in heading.lower() or "steps" in heading.lower()
                else "bullet"
                if any(k in heading.lower() for k in ("action", "measure", "decision", "criteria", "consequence", "notes"))
                else "paragraph"
            )
            curr_sec = {
                "heading": heading,
                "type": sec_type,
                "items" if sec_type != "paragraph" else "content": [] if sec_type != "paragraph" else inline_content,
            }
            if inline_content and sec_type != "paragraph":
                curr_sec["items"].append(re.sub(r"^[-*•]\s*", "", inline_content))
            sections.append(curr_sec)
            continue

        if curr_sec is not None:
            clean_l = re.sub(r"^[-*•]\s*", "", line)
            m_footer = meta_re.match(clean_l)
            if m_footer and re.search(
                r"^(owner|status|next\s*review|incident\s*owner|signed[- ]off)",
                m_footer.group(1),
                re.I,
            ):
                metadata.append({"key": m_footer.group(1).strip(), "value": m_footer.group(2).strip()})
                continue

            if curr_sec["type"] == "paragraph":
                curr_sec["content"] = (curr_sec["content"] + " " + line).strip()
            else:
                clean_item = re.sub(r"^(?:[-*•]|\d+[\.\)])\s*", "", line).strip()
                curr_sec["items"].append(clean_item)
            continue

        meta_m = meta_re.match(line)
        if meta_m:
            k, v = meta_m.group(1).strip(), meta_m.group(2).strip()
            if re.search(r"^(incident|ticket|jira\s*ticket|issue|subject)$", k, re.I) and not title:
                title = v
            else:
                metadata.append({"key": k, "value": v})
        elif not title and line.startswith("#"):
            title = line.replace("#", "").strip()

    if not sections and lines:
        sections.append({
            "heading": "Message Body" if default_doc_type == "Formal Workplace Email" else "Document Content",
            "type": "paragraph",
            "content": " ".join(lines),
        })

    return {
        "doc_type": default_doc_type,
        "title": title or ("Workplace Email" if default_doc_type == "Formal Workplace Email" else "Workplace Technical Document"),
        "metadata": metadata,
        "sections": sections,
    }


def render_task_suggested_answer(stem: str, completion: str) -> str:
    """Safely render suggested_answer by expanding {{completion}} in stem_template.
    Defensively strips repeated stem prefix or suffix if LLM generated the full sentence."""
    if not stem:
        return completion.strip()
    norm_stem = stem
    if "{completion}" in norm_stem and "{{completion}}" not in norm_stem:
        norm_stem = norm_stem.replace("{completion}", "{{completion}}")
    elif "<completion>" in norm_stem:
        norm_stem = norm_stem.replace("<completion>", "{{completion}}")
    elif "[completion]" in norm_stem:
        norm_stem = norm_stem.replace("[completion]", "{{completion}}")
    elif ("..." in norm_stem or "…" in norm_stem) and "{{completion}}" not in norm_stem:
        norm_stem = norm_stem.replace("...", "{{completion}}").replace("…", "{{completion}}")

    if "{{completion}}" not in norm_stem:
        clean_c = completion.strip()
        if norm_stem.endswith("?"):
            return f"{norm_stem[:-1].rstrip()} {clean_c}?".strip()
        elif norm_stem.endswith("."):
            return f"{norm_stem[:-1].rstrip()} {clean_c}.".strip()
        return f"{norm_stem} {clean_c}".strip()

    clean_comp = completion.strip()
    prefix, _, suffix = norm_stem.partition("{{completion}}")
    norm_prefix = prefix.strip()
    norm_suffix = suffix.strip()

    # If completion begins with the stem prefix (e.g. LLM generated the whole sentence), strip it
    if norm_prefix and clean_comp.lower().startswith(norm_prefix.lower()):
        clean_comp = clean_comp[len(norm_prefix):].strip()

    # If completion ends with the stem suffix (e.g. '?' or '.'), strip it
    if norm_suffix and clean_comp.lower().endswith(norm_suffix.lower()):
        clean_comp = clean_comp[:-len(norm_suffix)].strip()

    # Clean double punctuation
    if norm_suffix and clean_comp.endswith(norm_suffix):
        clean_comp = clean_comp[:-len(norm_suffix)].strip()

    return f"{prefix}{clean_comp}{suffix}".strip()


def render_task_suggested_answer_trilingual(
    phrase_item: dict,
    suggested_completion: dict | str | None,
    existing_ans: dict | str | None = None,
) -> dict[str, str]:
    """Safely render trilingual suggested_answer {en, vi, ja} for a dialogue practice task."""
    ans_en = ""
    ans_vi = ""
    ans_ja = ""

    if isinstance(existing_ans, dict):
        ans_en = str(existing_ans.get("en") or "").strip()
        ans_vi = str(existing_ans.get("vi") or "").strip()
        ans_ja = str(existing_ans.get("ja") or "").strip()
    elif isinstance(existing_ans, str) and existing_ans.strip():
        ans_en = existing_ans.strip()

    s_comp_en = ""
    s_comp_vi = ""
    s_comp_ja = ""
    if isinstance(suggested_completion, dict):
        s_comp_en = str(suggested_completion.get("en") or "").strip()
        s_comp_vi = str(suggested_completion.get("vi") or "").strip()
        s_comp_ja = str(suggested_completion.get("ja") or "").strip()
    elif isinstance(suggested_completion, str):
        s_comp_en = suggested_completion.strip()

    if not ans_en:
        t_stem = str(phrase_item.get("stem_template") or "")
        ans_en = render_task_suggested_answer(t_stem, s_comp_en)

    if not ans_vi:
        p_meaning_vi = ""
        meaning = phrase_item.get("meaning")
        if isinstance(meaning, dict):
            p_meaning_vi = str(meaning.get("vi") or "").strip()
        elif phrase_item.get("vn_meaning"):
            p_meaning_vi = str(phrase_item.get("vn_meaning") or "").strip()

        if p_meaning_vi and s_comp_vi:
            if "..." in p_meaning_vi:
                ans_vi = p_meaning_vi.replace("...", s_comp_vi)
            elif "…" in p_meaning_vi:
                ans_vi = p_meaning_vi.replace("…", s_comp_vi)
            elif p_meaning_vi.endswith("?"):
                ans_vi = f"{p_meaning_vi[:-1].strip()} {s_comp_vi}?"
            else:
                ans_vi = f"{p_meaning_vi} {s_comp_vi}"
        elif s_comp_vi:
            ans_vi = s_comp_vi

    if not ans_ja:
        p_meaning_ja = ""
        meaning = phrase_item.get("meaning")
        if isinstance(meaning, dict):
            p_meaning_ja = str(meaning.get("ja") or "").strip()
        elif phrase_item.get("ja_meaning"):
            p_meaning_ja = str(phrase_item.get("ja_meaning") or "").strip()

        if p_meaning_ja and s_comp_ja:
            if "…" in p_meaning_ja:
                ans_ja = p_meaning_ja.replace("…", s_comp_ja)
            elif "..." in p_meaning_ja:
                ans_ja = p_meaning_ja.replace("...", s_comp_ja)
            else:
                ans_ja = f"{s_comp_ja}{p_meaning_ja}"
        elif s_comp_ja:
            ans_ja = s_comp_ja

    return {
        "en": ans_en,
        "vi": ans_vi or ans_en,
        "ja": ans_ja or ans_en,
    }


KNOWN_TEACHER_NOTES = {
    "Focus on balancing engineering sustainability with stakeholder timeline pressures. The PM must not choose a side blindly but facilitate a trade-off discussion backed by empirical metrics.": {
        "vi": "Tập trung vào việc cân bằng giữa tính bền vững kỹ thuật và áp lực tiến độ từ các bên liên quan. Quản lý dự án không được thiên vị một bên một cách mù quáng mà cần điều phối buổi thảo luận về sự đánh đổi dựa trên số liệu thực tế.",
        "ja": "エンジニアリングの[持続可能性|じぞくかのうせい]とステークホルダーのスケジュール[圧力|あつりょく]のバランスに[焦点|しょうてん]を[当|あ]てます。PMは[盲目的|もうもくてき]にどちらかの[側|がわ]に[味方|みかた]するのではなく、[客観的|きゃっかんてき]な[測定指標|そくていしひょう]に[基|づ]づいてトレードオフの[議論|ぎろん]を[促進|そくしん]する[必要|ひつよう]があります。",
    },
    "Ensure learners can distinguish between noun phrases (technical debt, bottleneck) and active technical verbs (refactor, mitigate) in spoken project management discussions.": {
        "vi": "Đảm bảo học viên phân biệt được giữa các cụm danh từ (nợ kỹ thuật, nút thắt cổ chai) và các động từ kỹ thuật chủ động (tái cấu trúc, giảm thiểu) trong các cuộc thảo luận quản lý dự án.",
        "ja": "プロジェクトマネジメントの[会話|かいわ]において、[学習者|がくしゅうしゃ]が[名詞句|めいしく]（[技術的負債|ぎじゅつてきふさい]、ボトルネック）と能動的な[技術動詞|ぎじゅつどうし]（リファクタリングする、[軽減|けいげん]する）を[明確|めいかく]に[区別|くべつ]できることを[確認|かくにん]してください。",
    },
    "Verify that learners use the exact stem templates and ensure phrases p3, p4, and p5 strictly avoid starting with banned pronouns.": {
        "vi": "Kiểm tra để đảm bảo học viên sử dụng chính xác các mẫu câu khung và đảm bảo các cụm từ p3, p4, p5 tuyệt đối không bắt đầu bằng các đại từ bị cấm.",
        "ja": "[学習者|がくしゅうしゃ]が[正確|せいかく]なフレーズのステムテンプレートを[使用|しよう]しているかを[確認|かくにん]し、フレーズp3、p4、p5において[不要|ふよう]な[主語代名詞|しゅごだいめいし]で[始|はじ]まらないよう[徹底|てってい]してください。",
    },
    "Ensure students understand how executive memos balance technical reality with business requirements. The QA exercises test both literal comprehension and strategic inference.": {
        "vi": "Đảm bảo học viên hiểu cách các bản ghi nhớ điều hành cân bằng giữa thực tế kỹ thuật và yêu cầu kinh doanh. Các bài tập hỏi đáp kiểm tra cả khả năng hiểu nghĩa đen lẫn suy luận chiến lược.",
        "ja": "エグゼクティブメモがどのように[技術的|ぎじゅつてき]な[現実|げんじつ]とビジネス[要件|ようけん]のバランスを[取|と]っているかを[生徒|せいと]が[理解|りかい]していることを[確認|かくにん]してください。QA[演習|えんしゅう]では、[文字通|もじどお]りの[読解力|どっかいりょく]と[戦略的|せんりゃくてき]な[推論力|すいろんりょく]の[双方|そうほう]をテストします。",
    },
    "Ensure learners practice tone modulation when shifting from inquiry (p1, p2) to strategic proposal (p3, p4). Check that suggested completions are distinct from phrase items.": {
        "vi": "Đảm bảo học viên thực hành điều chỉnh ngữ điệu khi chuyển từ câu hỏi thăm dò (p1, p2) sang đề xuất chiến lược (p3, p4). Kiểm tra để phần hoàn thành gợi ý khác biệt với các mục cụm từ.",
        "ja": "[質問|しつもん]（p1、p2）から[戦略的|せんりゃくてき]な[提案|ていあん]（p3、p4）へと[移行|いこう]する[際|さい]のトーンの[切|き]り[替|か]えを[学習者|がくしゅうしゃ]に[練習|れんしゅう]させてください。[提案|ていあん]された[補完|ほかん]テキストがフレーズ[項目|こうもく]と[重複|じゅうふく]していないことを[確認|かくにん]します。",
    },
    "Focus listening practice on extracting metrics (20% traffic increase) and strategic solutions from senior leadership monologues.": {
        "vi": "Tập trung phần luyện nghe vào việc trích xuất các số liệu cụ thể (lưu lượng truy cập tăng 20%) và các giải pháp chiến lược từ bài phát biểu của lãnh đạo cấp cao.",
        "ja": "シニアリーダーシップのモノローグから、[具体的|ぐたいてき]な[指標|しひょう]（トラフィック20%[増加|ぞうか]）と[戦略的|せんりゃくてき][解決策|かいけつさく]を[正確|せいかく]に[聞|き]き[取|と]ることに[集中|しゅうちゅう]させます。",
    },
    "Ensure learners complete the action task by applying professional tone, clear trade-off framing, and specific lesson vocabulary in their written communication.": {
        "vi": "Đảm bảo học viên hoàn thành nhiệm vụ thực hành bằng cách áp dụng giọng văn chuyên nghiệp, định hình sự đánh đổi rõ ràng và sử dụng từ vựng cụ thể của bài học trong văn bản giao tiếp.",
        "ja": "[学習者|がくしゅうしゃ]が[専門的|せんもんてき]なトーン、[明確|めいかく]なトレードオフの[提示|ていじ]、およびレッスンで[学|まな]んだ[具体的|ぐたいてき]な[語彙|ごい]を[書面|しょめん]コミュニケーションに[適用|てきよう]して、アクションタスクを[完了|かんりょう]することを[確認|かくにん]してください。",
    },
}


def enrich_c1_object(c1_obj: dict) -> dict:
    """
    Enrich canonical C-1 JSON object with derived display fields for frontend:
    - phrases.items[i].phrase = stem_template.replace("{{completion}}", "...")
    - phrases.items[i].example = stem_template.replace("{{completion}}", example_completion.strip())
    - phrases.mini_scenarios[i].best_phrase = phrases_by_id[phrase_id].stem_template.replace("{{completion}}", "...")
    - dialogue.key_phrases[i].phrase = phrases_by_id[phrase_id].stem_template.replace("{{completion}}", "...")
    - dialogue.practice_tasks[i].suggested_answer = render_task_suggested_answer(stem, suggested_completion)
    """
    if not isinstance(c1_obj, dict):
        return c1_obj

    # Schema v4 trilingual normalizations
    sc = c1_obj.get("scenario")
    if isinstance(sc, dict):
        if "en" in sc and "english_text" not in sc:
            sc["english_text"] = sc.get("en", "")
        if "vi" in sc and "vietnamese_text" not in sc:
            sc["vietnamese_text"] = sc.get("vi", "")
        if "ja" in sc and "japanese_text" not in sc:
            sc["japanese_text"] = sc.get("ja", "")

    vb = c1_obj.get("vocab")
    if isinstance(vb, dict):
        v_items = vb.get("items", [])
        if isinstance(v_items, list):
            for item in v_items:
                if isinstance(item, dict):
                    t_val = item.get("term")
                    if isinstance(t_val, dict):
                        item["term_display"] = t_val.get("en", "")
                        item["vn_meaning"] = item.get("vn_meaning") or t_val.get("vi", "")
                        item["ja_meaning"] = item.get("ja_meaning") or t_val.get("ja", "")
                    elif isinstance(t_val, str):
                        item["term_display"] = t_val

    phrases = c1_obj.get("phrases")
    phrases_by_id: dict[str, dict] = {}
    if isinstance(phrases, dict):
        items = phrases.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    pid = item.get("id")
                    stem = str(item.get("stem_template") or "")
                    ex_comp = item.get("example_completion")
                    if isinstance(ex_comp, dict):
                        ex_comp_str = str(ex_comp.get("en") or "").strip()
                    else:
                        ex_comp_str = str(ex_comp or "").strip()

                    m_val = item.get("meaning")
                    if isinstance(m_val, dict):
                        for lang_k in ("vi", "ja"):
                            val_str = str(m_val.get(lang_k) or "").strip()
                            if "{completion}" in val_str or "{{completion}}" in val_str:
                                val_str = val_str.replace("{{completion}}", "...").replace("{completion}", "...")
                            elif lang_k == "vi":
                                # Convert common Vietnamese filler phrases into clean slot '...'
                                val_str = re.sub(r"\s*(phải thực hiện hành động gì|thực hiện hành động gì|điều gì|hành động gì)\b", " ...", val_str)
                                val_str = val_str.replace("giải quyết vấn đề như thế nào", "... như thế nào")
                            if val_str and "..." not in val_str and "…" not in val_str:
                                # Ensure slot '...' is present just like English!
                                if val_str.endswith("?"):
                                    val_str = f"{val_str[:-1].rstrip()} ...?"
                                elif val_str.endswith("。"):
                                    val_str = f"{val_str[:-1].rstrip()} ...。"
                                else:
                                    val_str = f"{val_str.rstrip('.')} ... ."
                            # Clean multiple spaces or stray dots
                            val_str = re.sub(r"\s+", " ", val_str).strip()
                            m_val[lang_k] = val_str
                        item["vn_meaning"] = m_val.get("vi", "")
                        item["ja_meaning"] = m_val.get("ja", "")

                    if pid:
                        phrases_by_id[pid] = item

                    norm_stem = stem
                    if "{completion}" in norm_stem and "{{completion}}" not in norm_stem:
                        norm_stem = norm_stem.replace("{completion}", "{{completion}}")
                    elif ("..." in norm_stem or "…" in norm_stem) and "{{completion}}" not in norm_stem:
                        norm_stem = norm_stem.replace("...", "{{completion}}").replace("…", "{{completion}}")
                    if "{{completion}}" not in norm_stem:
                        if norm_stem.endswith("?"):
                            norm_stem = norm_stem[:-1].rstrip() + " {{completion}}?"
                        else:
                            norm_stem = norm_stem.rstrip(".") + " {{completion}}."
                    item["stem_template"] = norm_stem
                    item["phrase"] = norm_stem.replace("{{completion}}", "...")
                    item["example"] = norm_stem.replace("{{completion}}", ex_comp_str)

                    # Enrich localized workplace examples
                    if isinstance(ex_comp, dict) and isinstance(m_val, dict):
                        for lang_code in ("vi", "ja"):
                            m_text = str(m_val.get(lang_code) or "").strip()
                            c_text = str(ex_comp.get(lang_code) or "").strip()
                            if m_text and c_text:
                                if "{{completion}}" in m_text:
                                    merged = m_text.replace("{{completion}}", c_text)
                                elif "{completion}" in m_text:
                                    merged = m_text.replace("{completion}", c_text)
                                elif "..." in m_text:
                                    merged = m_text.replace("...", c_text)
                                elif "…" in m_text:
                                    merged = m_text.replace("…", c_text)
                                else:
                                    # Fallback without parentheses
                                    clean_m = m_text.rstrip("?").rstrip(".").rstrip("。").strip()
                                    if lang_code == "vi":
                                        clean_m = re.sub(
                                            r"\s*(phải thực hiện hành động gì|thực hiện hành động gì|điều gì|hành động gì)\s*$",
                                            "",
                                            clean_m,
                                        )
                                        if "giải quyết vấn đề như thế nào" in clean_m:
                                            clean_m = clean_m.replace("giải quyết vấn đề như thế nào", f"{c_text} như thế nào")
                                            c_text = ""
                                    if m_text.endswith("?"):
                                        merged = f"{clean_m} {c_text}?".strip() if c_text else f"{clean_m}?"
                                    elif m_text.endswith("。"):
                                        merged = f"{clean_m} {c_text}。".strip() if c_text else f"{clean_m}。"
                                    else:
                                        merged = f"{clean_m} {c_text}.".strip() if c_text else f"{clean_m}."
                                # Ensure parentheses `(...)` are never present in the final sentence
                                merged = re.sub(r"\s*\((.*?)\)", r" \1", merged)
                                merged = re.sub(r"\s+", " ", merged).strip()
                                merged = re.sub(r"\s+([.,?!。])", r"\1", merged)
                                if lang_code == "vi":
                                    merged = re.sub(r"\b(việc|để|về|rằng|phải)\s+\1\b", r"\1", merged, flags=re.IGNORECASE)
                                    merged = re.sub(r"\bphải\s+việc\b", "phải", merged, flags=re.IGNORECASE)
                                item[f"example_{lang_code}"] = merged

        # Enrich mini_scenarios best_phrase
        mini = phrases.get("mini_scenarios", [])
        if isinstance(mini, list):
            for sc_item in mini:
                if isinstance(sc_item, dict):
                    pid = sc_item.get("phrase_id")
                    if pid in phrases_by_id:
                        sc_stem = str(phrases_by_id[pid].get("stem_template") or "")
                        sc_item["best_phrase"] = sc_stem.replace("{{completion}}", "...")

    dialogue = c1_obj.get("dialogue")
    if isinstance(dialogue, dict):
        # Defensively clean any stray '...' or '...?' in dialogue turns
        turns = dialogue.get("turns", [])
        if isinstance(turns, list):
            for t in turns:
                if isinstance(t, dict):
                    line_val = t.get("line")
                    if isinstance(line_val, dict):
                        t["line_en"] = line_val.get("en", "")
                        t["line_vi"] = line_val.get("vi", "")
                        t["line_ja"] = line_val.get("ja", "")
                        line_str = str(line_val.get("en") or "")
                    else:
                        line_str = str(line_val or "")

                    if "..." in line_str or "…" in line_str:
                        line_str = re.sub(r"\s*\.\.\.\s*\?", "?", line_str)
                        line_str = re.sub(r"\s*…\s*\?", "?", line_str)
                        line_str = re.sub(r"\s*\.\.\.\s*$", ".", line_str)
                        line_str = re.sub(r"\s*…\s*$", ".", line_str)
                        line_str = re.sub(r"\s*\.\.\.\s*", " ", line_str)
                        line_str = re.sub(r"\s*…\s*", " ", line_str)
                        if isinstance(line_val, dict):
                            line_val["en"] = line_str.strip()
                        else:
                            t["line"] = line_str.strip()

        # Enrich key_phrases phrase
        kp_list = dialogue.get("key_phrases", [])
        if isinstance(kp_list, list):
            for kp in kp_list:
                if isinstance(kp, dict):
                    pid = kp.get("phrase_id")
                    if pid in phrases_by_id:
                        kp_stem = str(phrases_by_id[pid].get("stem_template") or "")
                        kp["phrase"] = kp_stem.replace("{{completion}}", "...")

        # Enrich practice_tasks suggested_answer
        tasks = dialogue.get("practice_tasks", [])
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    pid = task.get("phrase_id")
                    s_comp = task.get("suggested_completion")
                    existing_ans = task.get("suggested_answer")
                    p_item = phrases_by_id.get(pid, {})
                    trilingual_ans = render_task_suggested_answer_trilingual(p_item, s_comp, existing_ans)
                    task["suggested_answer"] = trilingual_ans
                    task["suggested_answer_en"] = trilingual_ans["en"]
                    task["suggested_answer_vi"] = trilingual_ans["vi"]
                    task["suggested_answer_ja"] = trilingual_ans["ja"]

    # Safe reading document & metadata normalization
    reading = c1_obj.get("reading")
    if isinstance(reading, dict):
        doc = reading.get("document")
        if isinstance(doc, str):
            doc_str = doc.strip()
            if doc_str.startswith("{") and doc_str.endswith("}"):
                try:
                    parsed_doc = json.loads(doc_str)
                    if isinstance(parsed_doc, dict) and "sections" in parsed_doc:
                        reading["document"] = parsed_doc
                        doc = parsed_doc
                except Exception:
                    pass
        if isinstance(doc, dict):
            if not isinstance(doc.get("metadata"), list):
                doc["metadata"] = []
            sections = doc.get("sections")
            if isinstance(sections, list):
                for sec in sections:
                    if isinstance(sec, dict):
                        if sec.get("items") and not sec.get("content") and sec.get("type") == "paragraph":
                            sec["type"] = "bullet"
                        elif sec.get("content") and not sec.get("items") and sec.get("type") in ("bullet", "numbered"):
                            sec["type"] = "paragraph"

    # Normalize teacher_note across all sections to guarantee trilingual support
    for sec_name in ("scenario", "vocab", "phrases", "reading", "dialogue", "listening", "wrapup"):
        sec_data = c1_obj.get(sec_name)
        if isinstance(sec_data, dict):
            tn = sec_data.get("teacher_note")
            if isinstance(tn, dict):
                en_tn = str(tn.get("en") or "").strip()
                if en_tn and (not tn.get("vi") or not tn.get("ja")):
                    dict_match = KNOWN_TEACHER_NOTES.get(en_tn)
                    if dict_match:
                        if not tn.get("vi"):
                            tn["vi"] = dict_match["vi"]
                        if not tn.get("ja"):
                            tn["ja"] = dict_match["ja"]
            elif isinstance(tn, str) and tn.strip():
                en_tn = tn.strip()
                dict_match = KNOWN_TEACHER_NOTES.get(en_tn)
                if dict_match:
                    sec_data["teacher_note"] = {
                        "en": en_tn,
                        "vi": dict_match["vi"],
                        "ja": dict_match["ja"],
                    }
                else:
                    sec_data["teacher_note"] = {
                        "en": en_tn,
                        "vi": en_tn,
                        "ja": en_tn,
                    }

    return c1_obj

# Backward compatibility alias
enrich_c1_v3_object = enrich_c1_object


def normalize_c1_object(c1_obj: dict) -> dict:
    """Canonical normalizer & enricher for C-1 structured object."""
    return enrich_c1_object(c1_obj)
