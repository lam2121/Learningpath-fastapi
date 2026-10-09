"""Shared utilities for AI content generation pipelines.

Contains JSON parsing, logging, and concurrency helpers used by all generators.
Extracted from generation.py to reduce coupling between generator pipelines.
"""

import ast
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.ai.client.cost import estimate_cost_usd
from app.core.ai.client.gemini import GeminiClientPool, LLMResponse
from app.core.infra.config import app_config
from app.models.ai_usage_log import AiUsageLog
from app.models.rejected_content import RejectedContent

logger = logging.getLogger(__name__)

MODEL = app_config.GEMINI_FLASH_MODEL
MAX_ATTEMPTS = app_config.LLM_MAX_ATTEMPTS  # original + retries (spec §8.1)
LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}

# Generator A (Placement) output budget.
MAX_PLACEMENT_OUTPUT_TOKENS = app_config.LLM_PLACEMENT_MAX_OUTPUT_TOKENS

class KeyedMutex:
    """Async mutex keyed by ID with automatic cleanup when idle (prevents memory leaks)."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._counts: dict[int, int] = {}
        self._global_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: int):
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
                self._counts[key] = 0
            self._counts[key] += 1
            lock = self._locks[key]

        async with lock:
            try:
                yield
            finally:
                async with self._global_lock:
                    self._counts[key] -= 1
                    if self._counts[key] <= 0:
                        self._locks.pop(key, None)
                        self._counts.pop(key, None)


# Serializes background generation per role so concurrent clicks can never
# interleave deletes/inserts and multiply the question pool.
_role_locks = KeyedMutex()


def _find_first_list(node, depth: int = 0):
    """First list found in a (possibly nested) dict, bounded to shallow depth."""
    if isinstance(node, list):
        return node
    if isinstance(node, dict) and depth < 3:
        for value in node.values():
            found = _find_first_list(value, depth + 1)
            if found is not None:
                return found
    return None


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences (``` or ```json)."""
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_start(text: str) -> str:
    """Locate the first `[` or `{` and return everything from there.

    Some models prepend preamble text (e.g. "Here is the JSON:") before the
    actual payload despite explicit instructions.  This strips that prefix so
    ``json.loads`` does not choke on it.
    """
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            trimmed = text[i:]
            # Also strip trailing non-JSON text: find the last ] or } and
            # drop anything after it (e.g. "```\\nEnd text").
            for j in range(len(trimmed) - 1, -1, -1):
                if trimmed[j] in ("]", "}"):
                    return trimmed[: j + 1]
            return trimmed
    return text


def _try_literal_eval(text: str):
    """Fallback parser using ast.literal_eval for single-quoted Python literals.

    Some models output single-quoted strings (valid Python, invalid JSON).
    This safely parses that format as a last resort before giving up.
    """
    return ast.literal_eval(text)


def _unescape_json_string(text: str) -> str:
    """Recover arrays wrapped as an escaped JSON string.

    Several OpenAI-compatible free models (groq gpt-oss, qwen, compound) return
    the requested array as a literal JSON *string* that double-encodes the inner
    quotes, e.g. ``[[\\"D_doc\\",\\"Easy\\",...]]`` instead of plain
    ``[["D_doc","Easy",...]]``. ``json.loads`` of that literal fails with
    "Expecting value" because of the stray backslashes. Stripping the
    backslash-quote pairs yields clean, valid JSON.
    """
    if '\\"' not in text:
        return text
    return text.replace('\\"', '"')


def _parse_json(text: str):
    """Parse the raw model output as JSON, tolerating code fences.

    Some providers run in json_object mode, which forces a top-level object
    even when an array is requested (e.g. `{"questions": [...]}`). Unwrap the
    first list value found (also one level deeper, for nested wrappers like
    `{"lesson": {"sections": [...]}}`) so the validator sees the array.

    Free OpenAI-compatible models (groq gpt-oss etc.) also double-encode the
    array as an escaped JSON string, so the quotes are backslash-prefixed.
    ``_unescape_json_string`` recovers that form (deviation: parser-robustness
    fix so the fast primary provider's valid output is accepted instead of
    timing out and rotating to a slow fallback).
    """
    cleaned = text.strip()
    cleaned = _strip_code_fences(cleaned)
    cleaned = _extract_json_start(cleaned)

    # Candidate parse strategies, most-likely first. `ast.literal_eval` (used by
    # `_try_literal_eval`) can raise SyntaxError as well as ValueError, so each
    # attempt is guarded individually; one recovery path failing must never
    # prevent a later (or the direct) strategy from succeeding.
    parse_attempts = [
        json.loads,
        lambda s: json.loads(_unescape_json_string(s)),
        _try_literal_eval,
        lambda s: json.loads(_unescape_json_string(s.strip())),
    ]
    parsed = None
    for strategy in parse_attempts:
        try:
            parsed = strategy(cleaned)
            break
        except (ValueError, SyntaxError, TypeError):
            continue
    if parsed is None:
        raise ValueError(
            f"Expected a JSON array, could not parse output "
            f"({cleaned[:200]!r})"
        )

    if isinstance(parsed, str):
        # Double-encoded: the model returned a JSON *string* holding an array.
        inner = parsed.strip()
        if inner.startswith(("[[", "[")):
            try:
                parsed = json.loads(_unescape_json_string(inner))
            except (ValueError, SyntaxError, TypeError):
                pass
    if isinstance(parsed, list):
        # Unwrap superfluous outer array if model returned [[ [...], ... ]]
        while (
            len(parsed) == 1
            and isinstance(parsed[0], list)
            and (len(parsed[0]) == 0 or isinstance(parsed[0][0], list))
        ):
            parsed = parsed[0]
        return parsed
    if isinstance(parsed, dict):
        preferred = ("questions", "rows", "data", "items", "results", "placement_test")
        for key in preferred:
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        unwrapped = _find_first_list(parsed)
        if unwrapped is not None:
            return unwrapped
    raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")


def _log_usage(
    db: Session,
    generator: str,
    role_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    status: str,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    db.add(
        AiUsageLog(
            generator=generator,
            model=f"{provider}/{model}" if provider and model else (model or MODEL),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost_usd(prompt_tokens, completion_tokens, model=model),
            status=status,
            role_id=role_id,
        )
    )


def _record_rejected(
    db: Session,
    generator: str,
    role_id: int,
    input_preview: str,
    error: str,
    raw_response: str | None,
    validator_checks: dict | None,
) -> None:
    db.add(
        RejectedContent(
            generator=generator,
            role_id=role_id,
            input_preview=input_preview[:500],
            error=error[:500],
            raw_response=raw_response,
            validator_checks=validator_checks,
            status="pending",
        )
    )
