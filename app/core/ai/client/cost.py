"""Token -> USD cost estimation from Gemini API usageMetadata (spec §7.3).

Rates are aligned to gemini-2.5-flash text pricing (model is configured via
GEMINI_FLASH_MODEL) and gemini-2.5-pro pricing (GEMINI_PRO_MODEL, Generators
C-1/C-2). `estimate_cost_usd(..., model=...)` picks the rate set: any model
that differs from the configured Flash model is billed at the Pro rate.
Adjust the LLM_*_RATE_PER_1K settings in .env if real billing differs.
"""

from app.core.infra.config import app_config

# Per-1K-token USD rates (Gemini 2.5 Flash, text)
FLASH_INPUT_RATE_PER_1K = app_config.LLM_FLASH_INPUT_RATE_PER_1K  # default ~$0.30 / 1M input tokens
FLASH_OUTPUT_RATE_PER_1K = app_config.LLM_FLASH_OUTPUT_RATE_PER_1K  # default ~$2.50 / 1M output tokens

# Per-1K-token USD rates (Gemini 2.5 Pro, text — Generators C-1/C-2)
PRO_INPUT_RATE_PER_1K = app_config.LLM_PRO_INPUT_RATE_PER_1K  # default ~$1.25 / 1M input tokens
PRO_OUTPUT_RATE_PER_1K = app_config.LLM_PRO_OUTPUT_RATE_PER_1K  # default ~$10.00 / 1M output tokens


def estimate_cost_usd(
    prompt_tokens: int, completion_tokens: int, model: str | None = None
) -> float:
    """Compute estimated USD cost from token counts.

    `model` selects the rate set: the configured Flash model (or None) uses
    Flash rates; anything else uses Pro rates.
    """
    pro = model is not None and model != app_config.GEMINI_FLASH_MODEL
    input_rate = PRO_INPUT_RATE_PER_1K if pro else FLASH_INPUT_RATE_PER_1K
    output_rate = PRO_OUTPUT_RATE_PER_1K if pro else FLASH_OUTPUT_RATE_PER_1K
    return (
        prompt_tokens / 1000.0 * input_rate + completion_tokens / 1000.0 * output_rate
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
