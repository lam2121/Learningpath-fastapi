"""C-1 Theory Content JSON Schema definitions.

Contains the canonical JSON Schema for validating and constraining
C-1 generated theory content. Extracted from prompts.py because schema
definitions are not prompts.
"""

from app.core.ai.dispatch.prompts_common import NUM_VOCAB, NUM_PATTERNS


def _get_c1_v4_json_schema(
    for_storage: bool = False,
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
) -> dict:
    """Canonical Trilingual (EN / VI / JA) Schema for C-1 Theory Content."""
    trilingual_str = {
        "type": "object",
        "properties": {
            "en": {"type": "string"},
            "vi": {"type": "string"},
            "ja": {"type": "string"},
        },
        "required": ["en", "vi", "ja"],
        "additionalProperties": False,
    }

    teacher_note_str = {
        "anyOf": [
            trilingual_str,
            {"type": "string"},
        ]
    }

    bilingual_vi_ja = {
        "type": "object",
        "properties": {
            "vi": {"type": "string"},
            "ja": {"type": "string"},
        },
        "required": ["vi", "ja"],
        "additionalProperties": False,
    }

    # Reading section types
    paragraph_section = {
        "type": "object",
        "properties": {
            "heading": trilingual_str,
            "type": {"type": "string", "enum": ["paragraph"]},
            "content": trilingual_str,
        },
        "required": ["heading", "type", "content"],
        "additionalProperties": False,
    }
    bullet_section = {
        "type": "object",
        "properties": {
            "heading": trilingual_str,
            "type": {"type": "string", "enum": ["bullet"]},
            "items": {
                "type": "array",
                "items": trilingual_str,
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }
    numbered_section = {
        "type": "object",
        "properties": {
            "heading": trilingual_str,
            "type": {"type": "string", "enum": ["numbered"]},
            "items": {
                "type": "array",
                "items": trilingual_str,
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }
    chat_section = {
        "type": "object",
        "properties": {
            "heading": trilingual_str,
            "type": {"type": "string", "enum": ["chat"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "role": {"type": ["string", "null"]},
                        "time": {"type": ["string", "null"]},
                        "text": trilingual_str,
                    },
                    "required": ["sender", "role", "time", "text"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }

    # Phrases
    phrase_item_props = {
        "id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "stem_template": {"type": "string"},
        "speech_act": {
            "type": "string",
            "enum": [
                "inquiry",
                "clarification",
                "proposal",
                "recommendation",
                "risk_mitigation",
                "confirmation",
            ],
        },
        "completion_kind": {
            "type": "string",
            "enum": [
                "open_proposal",
                "technical_solution",
                "operational_action",
                "metric_or_constraint",
                "trade_off_option",
                "root_cause_factor",
            ],
        },
        "meaning": bilingual_vi_ja,
        "when_to_use": trilingual_str,
        "example_completion": trilingual_str,
    }
    phrase_item_req = [
        "id",
        "stem_template",
        "speech_act",
        "completion_kind",
        "meaning",
        "when_to_use",
        "example_completion",
    ]
    if for_storage:
        phrase_item_props["phrase"] = {"type": "string"}
        phrase_item_props["example"] = {"type": "string"}
        phrase_item_props["example_vi"] = {"type": "string"}
        phrase_item_props["example_ja"] = {"type": "string"}
        phrase_item_props["vn_meaning"] = {"type": "string"}
        phrase_item_props["ja_meaning"] = {"type": "string"}
        phrase_item_req.extend(["phrase", "example"])

    mini_scenario_props = {
        "context": trilingual_str,
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
    }
    mini_scenario_req = ["context", "phrase_id"]
    if for_storage:
        mini_scenario_props["best_phrase"] = {"type": "string"}
        mini_scenario_req.append("best_phrase")

    phrases_def = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": phrase_item_props,
                    "required": phrase_item_req,
                    "additionalProperties": False,
                },
                "minItems": num_patterns,
                "maxItems": num_patterns,
            },
            "mini_scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": mini_scenario_props,
                    "required": mini_scenario_req,
                    "additionalProperties": False,
                },
                "minItems": 3,
                "maxItems": 3,
            },
            "teacher_note": teacher_note_str,
        },
        "required": ["items", "mini_scenarios", "teacher_note"],
        "additionalProperties": False,
    }

    # Dialogue
    key_phrase_props = {
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "why_it_works": trilingual_str,
    }
    key_phrase_req = ["phrase_id", "why_it_works"]
    if for_storage:
        key_phrase_props["phrase"] = {"type": "string"}
        key_phrase_req.append("phrase")

    practice_task_props = {
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "type": {"type": "string", "enum": ["ask", "reply"]},
        "prompt": trilingual_str,
        "suggested_completion": trilingual_str,
    }
    practice_task_req = ["phrase_id", "type", "prompt", "suggested_completion"]
    if for_storage:
        practice_task_props["suggested_answer"] = {
            "oneOf": [
                trilingual_str,
                {"type": "string"},
            ]
        }
        practice_task_props["suggested_answer_en"] = {"type": "string"}
        practice_task_props["suggested_answer_vi"] = {"type": "string"}
        practice_task_props["suggested_answer_ja"] = {"type": "string"}
        practice_task_req.append("suggested_answer")

    turn_props = {
        "speaker": {"type": "string"},
        "line": trilingual_str,
    }
    turn_req = ["speaker", "line"]
    if for_storage:
        turn_props["line_en"] = {"type": "string"}
        turn_props["line_vi"] = {"type": "string"}
        turn_props["line_ja"] = {"type": "string"}

    dialogue_def = {
        "type": "object",
        "properties": {
            "context": trilingual_str,
            "turns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": turn_props,
                    "required": turn_req,
                    "additionalProperties": False,
                },
            },
            "key_phrases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": key_phrase_props,
                    "required": key_phrase_req,
                    "additionalProperties": False,
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "practice_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": practice_task_props,
                    "required": practice_task_req,
                    "additionalProperties": False,
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "teacher_note": teacher_note_str,
        },
        "required": ["context", "turns", "key_phrases", "practice_tasks", "teacher_note"],
        "additionalProperties": False,
    }

    # Scenario properties
    scenario_props = {
        "en": {"type": "string"},
        "vi": {"type": "string"},
        "ja": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": trilingual_str,
            "minItems": 3,
            "maxItems": 3,
        },
        "teacher_note": teacher_note_str,
    }
    scenario_req = ["en", "vi", "ja", "decisions", "teacher_note"]
    if for_storage:
        scenario_props["english_text"] = {"type": "string"}
        scenario_props["vietnamese_text"] = {"type": "string"}
        scenario_props["japanese_text"] = {"type": "string"}

    # Vocab properties
    vocab_item_props = {
        "term": trilingual_str,
        "reading": {"type": "string"},
        "ipa": {"type": "string"},
        "pos": {"type": "string"},
        "explanation": trilingual_str,
        "example": trilingual_str,
        "pronunciation_guide": {"type": "string"},
    }
    vocab_item_req = [
        "term",
        "reading",
        "ipa",
        "pos",
        "explanation",
        "example",
        "pronunciation_guide",
    ]
    if for_storage:
        vocab_item_props["vn_meaning"] = {"type": "string"}
        vocab_item_props["ja_meaning"] = {"type": "string"}
        vocab_item_props["term_display"] = {"type": "string"}

    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "enum": [4]},
            "scenario": {
                "type": "object",
                "properties": scenario_props,
                "required": scenario_req,
                "additionalProperties": False,
            },
            "vocab": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": vocab_item_props,
                            "required": vocab_item_req,
                            "additionalProperties": False,
                        },
                        "minItems": num_vocab,
                        "maxItems": num_vocab,
                    },
                    "pronunciation_guide": {"type": "string"},
                    "drills": {
                        "type": "array",
                        "items": trilingual_str,
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "teacher_note": teacher_note_str,
                },
                "required": ["items", "pronunciation_guide", "drills", "teacher_note"],
                "additionalProperties": False,
            },
            "phrases": phrases_def,
            "reading": {
                "type": "object",
                "properties": {
                    "document": {
                        "type": "object",
                        "properties": {
                            "doc_type": {"type": "string"},
                            "title": trilingual_str,
                            "metadata": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string"},
                                        "value": trilingual_str,
                                    },
                                    "required": ["key", "value"],
                                    "additionalProperties": False,
                                },
                            },
                            "sections": {
                                "type": "array",
                                "items": {
                                    "anyOf": [
                                        paragraph_section,
                                        bullet_section,
                                        numbered_section,
                                        chat_section,
                                    ]
                                },
                                "minItems": 1,
                            },
                        },
                        "required": ["doc_type", "title", "metadata", "sections"],
                        "additionalProperties": False,
                    },
                    "qa": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": trilingual_str,
                                "answer": trilingual_str,
                            },
                            "required": ["question", "answer"],
                            "additionalProperties": False,
                        },
                        "minItems": 6,
                        "maxItems": 6,
                    },
                    "teacher_note": teacher_note_str,
                },
                "required": ["document", "qa", "teacher_note"],
                "additionalProperties": False,
            },
            "dialogue": dialogue_def,
            "listening": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "script": trilingual_str,
                    "qa": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": trilingual_str,
                                "answer": trilingual_str,
                            },
                            "required": ["question", "answer"],
                            "additionalProperties": False,
                        },
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "teacher_note": teacher_note_str,
                },
                "required": ["speaker", "script", "qa", "teacher_note"],
                "additionalProperties": False,
            },
            "wrapup": {
                "type": "object",
                "properties": {
                    "takeaways": {
                        "type": "array",
                        "items": trilingual_str,
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "action_task": trilingual_str,
                    "teacher_note": teacher_note_str,
                },
                "required": ["takeaways", "action_task", "teacher_note"],
                "additionalProperties": False,
            },
        },
        "required": [
            "schema_version",
            "scenario",
            "vocab",
            "phrases",
            "reading",
            "dialogue",
            "listening",
            "wrapup",
        ],
        "additionalProperties": False,
    }


def get_c1_json_schema(
    for_storage: bool = False,
    schema_version: int = 4,
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
) -> dict:
    """Return JSON schema definition for C-1.
    - for_storage=False: Canonical Generation Schema (pure AI fields, strict additionalProperties: False)
    - for_storage=True: Stored/View Schema (canonical fields + derived frontend fields, strict additionalProperties: False)
    """
    if schema_version >= 4:
        return _get_c1_v4_json_schema(
            for_storage=for_storage,
            num_vocab=num_vocab,
            num_patterns=num_patterns,
        )

    paragraph_section = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "type": {"type": "string", "enum": ["paragraph"]},
            "content": {"type": "string"},
        },
        "required": ["heading", "type", "content"],
        "additionalProperties": False,
    }
    bullet_section = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "type": {"type": "string", "enum": ["bullet"]},
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }
    numbered_section = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "type": {"type": "string", "enum": ["numbered"]},
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }
    chat_section = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "type": {"type": "string", "enum": ["chat"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "role": {"type": ["string", "null"]},
                        "time": {"type": ["string", "null"]},
                        "text": {"type": "string"},
                    },
                    "required": ["sender", "role", "time", "text"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
        },
        "required": ["heading", "type", "items"],
        "additionalProperties": False,
    }

    phrase_item_props = {
        "id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "stem_template": {"type": "string"},
        "speech_act": {
            "type": "string",
            "enum": [
                "inquiry",
                "clarification",
                "proposal",
                "recommendation",
                "risk_mitigation",
                "confirmation",
            ],
        },
        "completion_kind": {
            "type": "string",
            "enum": [
                "open_proposal",
                "technical_solution",
                "operational_action",
                "metric_or_constraint",
                "trade_off_option",
                "root_cause_factor",
            ],
        },
        "vn_meaning": {"type": "string"},
        "when_to_use": {"type": "string"},
        "example_completion": {"type": "string"},
    }
    phrase_item_req = [
        "id",
        "stem_template",
        "speech_act",
        "completion_kind",
        "vn_meaning",
        "when_to_use",
        "example_completion",
    ]
    if for_storage:
        phrase_item_props["phrase"] = {"type": "string"}
        phrase_item_props["example"] = {"type": "string"}
        phrase_item_props["example_vi"] = {"type": "string"}
        phrase_item_props["example_ja"] = {"type": "string"}
        phrase_item_props["ja_meaning"] = {"type": "string"}
        phrase_item_req.extend(["phrase", "example"])

    mini_scenario_props = {
        "context": {"type": "string"},
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
    }
    mini_scenario_req = ["context", "phrase_id"]
    if for_storage:
        mini_scenario_props["best_phrase"] = {"type": "string"}
        mini_scenario_req.append("best_phrase")

    phrases_def = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": phrase_item_props,
                    "required": phrase_item_req,
                    "additionalProperties": False,
                },
                "minItems": num_patterns,
                "maxItems": num_patterns,
            },
            "mini_scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": mini_scenario_props,
                    "required": mini_scenario_req,
                    "additionalProperties": False,
                },
                "minItems": 3,
                "maxItems": 3,
            },
            "teacher_note": {"type": "string"},
        },
        "required": ["items", "mini_scenarios", "teacher_note"],
        "additionalProperties": False,
    }

    key_phrase_props = {
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "why_it_works": {"type": "string"},
    }
    key_phrase_req = ["phrase_id", "why_it_works"]
    if for_storage:
        key_phrase_props["phrase"] = {"type": "string"}
        key_phrase_req.append("phrase")

    practice_task_props = {
        "phrase_id": {"type": "string", "enum": [f"p{i}" for i in range(1, num_patterns + 1)]},
        "type": {"type": "string", "enum": ["ask", "reply"]},
        "prompt": {"type": "string"},
        "suggested_completion": {"type": "string"},
    }
    practice_task_req = ["phrase_id", "type", "prompt", "suggested_completion"]
    if for_storage:
        practice_task_props["suggested_answer"] = {"type": "string"}
        practice_task_req.append("suggested_answer")

    dialogue_def = {
        "type": "object",
        "properties": {
            "context": {"type": "string"},
            "turns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "line": {"type": "string"},
                    },
                    "required": ["speaker", "line"],
                    "additionalProperties": False,
                },
            },
            "key_phrases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": key_phrase_props,
                    "required": key_phrase_req,
                    "additionalProperties": False,
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "practice_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": practice_task_props,
                    "required": practice_task_req,
                    "additionalProperties": False,
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "teacher_note": {"type": "string"},
        },
        "required": ["context", "turns", "key_phrases", "practice_tasks", "teacher_note"],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "enum": [schema_version]},
            "scenario": {
                "type": "object",
                "properties": {
                    "english_text": {"type": "string"},
                    "vietnamese_text": {"type": "string"},
                    "decisions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "teacher_note": {"type": "string"},
                },
                "required": ["english_text", "vietnamese_text", "decisions", "teacher_note"],
                "additionalProperties": False,
            },
            "vocab": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "term": {"type": "string"},
                                "ipa": {"type": "string"},
                                "pos": {"type": "string"},
                                "vn_meaning": {"type": "string"},
                                "explanation": {"type": "string"},
                                "example": {"type": "string"},
                                "pronunciation_guide": {"type": "string"},
                            },
                            "required": [
                                "term",
                                "ipa",
                                "pos",
                                "vn_meaning",
                                "explanation",
                                "example",
                                "pronunciation_guide",
                            ],
                            "additionalProperties": False,
                        },
                        "minItems": num_vocab,
                        "maxItems": num_vocab,
                    },
                    "pronunciation_guide": {"type": "string"},
                    "drills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "teacher_note": {"type": "string"},
                },
                "required": ["items", "pronunciation_guide", "drills", "teacher_note"],
                "additionalProperties": False,
            },
            "phrases": phrases_def,
            "reading": {
                "type": "object",
                "properties": {
                    "document": {
                        "type": "object",
                        "properties": {
                            "doc_type": {"type": "string"},
                            "title": {"type": "string"},
                            "metadata": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["key", "value"],
                                    "additionalProperties": False,
                                },
                            },
                            "sections": {
                                "type": "array",
                                "items": {
                                    "anyOf": [
                                        paragraph_section,
                                        bullet_section,
                                        numbered_section,
                                        chat_section,
                                    ]
                                },
                                "minItems": 1,
                            },
                        },
                        "required": ["doc_type", "title", "metadata", "sections"],
                        "additionalProperties": False,
                    },
                    "qa": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "answer": {"type": "string"},
                            },
                            "required": ["question", "answer"],
                            "additionalProperties": False,
                        },
                        "minItems": 6,
                        "maxItems": 6,
                    },
                    "teacher_note": {"type": "string"},
                },
                "required": ["document", "qa", "teacher_note"],
                "additionalProperties": False,
            },
            "dialogue": dialogue_def,
            "listening": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "script": {"type": "string"},
                    "qa": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "answer": {"type": "string"},
                            },
                            "required": ["question", "answer"],
                            "additionalProperties": False,
                        },
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "teacher_note": {"type": "string"},
                },
                "required": ["speaker", "script", "qa", "teacher_note"],
                "additionalProperties": False,
            },
            "wrapup": {
                "type": "object",
                "properties": {
                    "takeaways": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "action_task": {"type": "string"},
                    "teacher_note": {"type": "string"},
                },
                "required": ["takeaways", "action_task", "teacher_note"],
                "additionalProperties": False,
            },
        },
        "required": [
            "schema_version",
            "scenario",
            "vocab",
            "phrases",
            "reading",
            "dialogue",
            "listening",
            "wrapup",
        ],
        "additionalProperties": False,
    }


def get_c1_generation_schema(
    schema_version: int = 4,
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
) -> dict:
    """Return canonical generation schema for AI output (no derived fields)."""
    return get_c1_json_schema(
        for_storage=False,
        schema_version=schema_version,
        num_vocab=num_vocab,
        num_patterns=num_patterns,
    )


def get_c1_stored_schema(
    schema_version: int = 4,
    num_vocab: int = NUM_VOCAB,
    num_patterns: int = NUM_PATTERNS,
) -> dict:
    """Return stored/view schema for persisted objects (includes derived fields)."""
    return get_c1_json_schema(
        for_storage=True,
        schema_version=schema_version,
        num_vocab=num_vocab,
        num_patterns=num_patterns,
    )


