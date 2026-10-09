"""Shared constants and helpers for AI prompts across all generators.

Extracted to break circular imports between dispatch.prompts and subpackages.
"""

from app.core.infra.config import app_config

NUM_PLACEMENT_QUESTIONS_PER_SKILL = app_config.NUM_PLACEMENT_QUESTIONS_PER_SKILL
SKILLS = ["D_doc", "C_comm", "T_trouble", "G_custom"]
SKILL_TITLES = {
    "D_doc": "Document",
    "C_comm": "Communication",
    "T_trouble": "Trouble",
    "G_custom": "Custom",
}

NUM_VOCAB = app_config.NUM_VOCAB
NUM_PATTERNS = app_config.NUM_PATTERNS


def render_skill_definitions_block(
    skill_definitions: dict[str, dict[str, str | dict[str, str] | list[str]]],
) -> str:
    lines = ["[SKILL DEFINITIONS]"]
    for skill in SKILLS:
        item = skill_definitions.get(skill) or {}
        raw_desc = item.get("description", "")
        if isinstance(raw_desc, dict):
            description = str(raw_desc.get("en", "")).strip()
        else:
            description = str(raw_desc).strip()
        lines.append(f"- {skill} ({SKILL_TITLES[skill]}): {description}")
    return "\n".join(lines)


def get_skill_description(
    skill_definitions: dict[str, dict[str, str | dict[str, str] | list[str]]], skill: str
) -> str:
    item = skill_definitions.get(skill) or {}
    raw_desc = item.get("description", "")
    if isinstance(raw_desc, dict):
        return str(raw_desc.get("en", "")).strip()
    return str(raw_desc).strip()
