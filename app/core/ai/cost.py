"""Token -> USD cost estimation from Gemini API usageMetadata (spec §7.3).

Rates are aligned to gemini-2.5-flash text pricing (model is configured via
GEMINI_FLASH_MODEL). Adjust here if real billing differs.
"""

# Per-1K-token USD rates (Gemini 2.5 Flash, text)
FLASH_INPUT_RATE_PER_1K = 0.0003  # ~$0.30 / 1M input tokens
FLASH_OUTPUT_RATE_PER_1K = 0.0025  # ~$2.50 / 1M output tokens


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """Compute estimated USD cost from token counts."""
    return (
        prompt_tokens / 1000.0 * FLASH_INPUT_RATE_PER_1K
        + completion_tokens / 1000.0 * FLASH_OUTPUT_RATE_PER_1K
    )


def extract_usage(response) -> tuple[int, int]:
    """
    Pull (prompt_tokens, completion_tokens) from a generation result.
    Supports the normalized `LLMResponse` (has .prompt_tokens / .completion_tokens)
    as well as raw google-genai responses (usageMetadata).
    Returns (0, 0) when metadata is missing.
    """
    prompt = getattr(response, "prompt_tokens", None)
    completion = getattr(response, "completion_tokens", None)
    if prompt is not None or completion is not None:
        return int(prompt or 0), int(completion or 0)

    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_token_count", 0) or 0
    completion = getattr(usage, "candidates_token_count", 0) or 0
    return int(prompt), int(completion)
