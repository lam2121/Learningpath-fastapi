"""Multi-provider LLM client pool for admin content generation.

All providers are called through their OpenAI-compatible chat-completions
endpoints (Google Gemini exposes one at /v1beta/openai). Providers are rotated
round-robin on 429/quota/5xx/network errors with exponential backoff and a
short per-provider cooldown so an exhausted key is not hammered repeatedly.

- request timeout
- simple global rate limit (~250 RPM, spec §7.2)
- kill-switch guard: raises when `ai_generation_enabled=false`
"""

import asyncio
import json
import logging
import os
import random
import ssl
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

AI_GENERATION_ENABLED_KEY = "ai_generation_enabled"

# spec §7.2: Gemini Flash ~360 RPM, we use a ~70% safe threshold
RATE_LIMIT_RPM = app_config.LLM_RATE_LIMIT_RPM
MIN_INTERVAL_SECONDS = 60.0 / RATE_LIMIT_RPM

REQUEST_TIMEOUT_SECONDS = app_config.LLM_REQUEST_TIMEOUT_SECONDS

# Backoff config for 429/quota errors. Free-tier providers (esp. groq's
# gpt-oss-120b) enforce tokens-per-minute quotas on a ~60s rolling window: a
# single Generator-A block (~2900 output tokens) drains a large share of the
# budget, so a short 20s cooldown lets the NEXT attempt hit the same 429 before
# the window resets and the provider is skipped. Bumping the cooldown to ~65s
# lets the TPM window clear so a retried attempt can actually succeed.
QUOTA_BACKOFF_MIN = app_config.LLM_QUOTA_BACKOFF_MIN_SECONDS
QUOTA_BACKOFF_MAX = app_config.LLM_QUOTA_BACKOFF_MAX_SECONDS
PROVIDER_COOLDOWN_SECONDS = app_config.LLM_PROVIDER_COOLDOWN_SECONDS

SYSTEM_PROMPT = (
    "You are an expert ESL (English for IT) content generator. "
    "Respond with valid JSON only, matching the requested schema exactly."
)

# Common system CA bundle locations. Some networks terminate TLS with a
# corporate/self-signed certificate that certifi's bundled roots do not carry,
# which makes provider calls fail with CERTIFICATE_VERIFY_FAILED even though the
# system trust store has the correct roots. Prefer the system bundle when it
# exists so the pool works on such machines without setting SSL_CERT_FILE.
_SYSTEM_CA_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian / Ubuntu / Alpine
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL / Fedora / CentOS
    "/etc/ssl/ca-bundle.pem",  # OpenSUSE
    "/etc/ssl/cert.pem",  # Alpine
    "/usr/local/etc/openssl/cert.pem",  # macOS (Homebrew)
    "/opt/homebrew/etc/openssl/cert.pem",  # macOS (ARM Homebrew)
    "C:/Program Files/Git/mingw64/etc/ssl/certs/ca-bundle.crt",  # Git for Windows
    "C:/Program Files/Git/mingw64/etc/ssl/cert.pem",  # Git for Windows (alt)
)

_CA_FILE_EXTENSIONS = (".pem", ".crt", ".cer")


def _concat_ca_dir(ca_dir: str | Path) -> Path:
    """Concatenate every CA file in `ca_dir` into a single PEM bundle.

    Windows trust stores / CA folders often hold per-certificate files with
    arbitrary names, whereas OpenSSL's `capath` requires `c_rehash`-style
    `<hash>.N` names. Concatenating to one bundle sidesteps that entirely.
    """
    base = Path(ca_dir)
    bundle = Path(base) / ".ca-bundle.pem"
    lines: list[str] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in _CA_FILE_EXTENSIONS:
            continue
        lines.append(f"# {entry.name}\n")
        lines.append(entry.read_text(encoding="utf-8", errors="replace"))
    bundle.write_text("\n".join(lines), encoding="utf-8")
    return bundle


def _default_ssl_context() -> ssl.SSLContext | bool:
    """Build a verify-enabled SSL context that prefers an explicit CA source.

    Returns False (httpx: disable verification entirely) when
    DISABLE_SSL_VERIFY is set in config for environments with corporate
    SSL interception / self-signed certs.

    Resolution order:
      1. app_config.SSL_CERT_FILE (set in .env)   — single PEM bundle
      2. app_config.SSL_CERT_DIR  (set in .env)   — directory, concatenated
      3. os.environ SSL_CERT_FILE / SSL_CERT_DIR  — classic env-var override
      4. known system CA bundle locations (incl. Windows Git bundle)
      5. certifi defaults (ssl.create_default_context with no args)
    """
    if app_config.DISABLE_SSL_VERIFY:
        return False  # httpx: disable SSL verification entirely
    # (1) + (3) file, explicit config before process env.
    for env in (
        app_config.SSL_CERT_FILE,
        os.environ.get("SSL_CERT_FILE", ""),
    ):
        if env and Path(env).is_file():
            return ssl.create_default_context(cafile=env)
    # (2) + (3) directory — concatenate to a bundle.
    for ca_dir in (
        app_config.SSL_CERT_DIR,
        os.environ.get("SSL_CERT_DIR", ""),
    ):
        if ca_dir and Path(ca_dir).is_dir():
            try:
                bundle = _concat_ca_dir(ca_dir)
            except OSError as exc:  # pragma: no cover - depends on FS state
                raise GenerationError(
                    f"Could not read CA directory {ca_dir!r}: {exc}"
                ) from exc
            return ssl.create_default_context(cafile=bundle)
    # (4) well-known system bundles.
    for path in _SYSTEM_CA_CANDIDATES:
        if Path(path).is_file():
            return ssl.create_default_context(cafile=path)
    # (5) certifi / OS defaults.
    return ssl.create_default_context()


class KillSwitchError(Exception):
    """Raised when AI generation is disabled via the kill switch."""


class GenerationError(Exception):
    """Raised when an LLM provider call fails."""


def _strip_md_fences(text: str) -> str:
    """Strip thought tags (<thought>...</thought>) and Markdown code fences from LLM responses."""
    import re
    text = text.strip()
    # Strip thinking / thought tags emitted by models like Gemma or DeepSeek
    text = re.sub(r"<(thought|think)[^>]*>.*?</\1>", "", text, flags=re.DOTALL).strip()
    # Remove opening fence: ```json or ```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    # Remove closing fence: ```
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _clean_schema_for_provider(schema: dict, provider_name: str) -> dict:
    """Strip keywords not supported by specific providers.

    OpenAI-compatible strict schema endpoints (Google Gemini, Groq, etc.) return HTTP 400
    if schema contains keywords like minItems, maxItems, minLength, maxLength, etc.
    """
    def _strip(d):
        if isinstance(d, dict):
            return {
                k: _strip(v)
                for k, v in d.items()
                if k not in (
                    "minItems",
                    "maxItems",
                    "minLength",
                    "maxLength",
                    "minimum",
                    "maximum",
                    "pattern",
                )
            }
        elif isinstance(d, list):
            return [_strip(v) for v in d]
        return d

    return _strip(schema)


@dataclass
class LLMResponse:
    """Normalized response across all providers."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    provider: str
    model: str


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    supports_strict_schema: bool = False


def generation_enabled(db: Session) -> bool:
    """Read `ai_generation_enabled` from system_setting (default true)."""
    row = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == AI_GENERATION_ENABLED_KEY)
        .first()
    )
    if row is None:
        return True
    return row.value.strip().lower() == "true"


def assert_generation_enabled(db: Session) -> None:
    """Kill-switch guard: raise KillSwitchError when generation is blocked."""
    if not generation_enabled(db):
        raise KillSwitchError(
            "AI generation is disabled (kill switch ON). Enable it in the Admin portal first."
        )


def _load_providers() -> list[ProviderConfig]:
    """
    Build the list of active LLM providers from environment variables.

    Order = preference order (primary first). Only keys that are present and
    verified during testing are included. Google's OpenAI-compatible
    endpoint is used for Gemini so a single client code path works everywhere.

    The pool is shared by all generators:
    - Google (gemini-3.5-flash): high-capacity, reliable generator (supports strict schema)
    - Groq (gpt-oss-120b): ultra-fast generator (supports strict schema)
    - Mistral & OpenRouter: fallbacks (supports strict schema)
    """
    candidates = [
        # Google (gemini-3.5-flash): verified 100% strict JSON schema contract compliant,
        # high capacity, no TPM bottleneck on large prompts.
        (
            "google",
            f"{app_config.GOOGLE_GEMINI_API_BASE_URL.rstrip('/')}/v1beta/openai",
            app_config.GEMINI_API_KEY,
            app_config.GEMINI_FLASH_MODEL,
            True,
        ),
        (
            "groq",
            app_config.GROQ_API_BASE_URL,
            app_config.Groq,
            app_config.GROQ_MODEL or app_config.GROQ_DEFAULT_MODEL,
            True,
        ),
        # Groq: ultra-fast general generator (configurable via GROQ_MODEL, defaults to 120b)
        (
            "mistral",
            app_config.MISTRAL_API_BASE_URL,
            app_config.Mistral,
            app_config.MISTRAL_DEFAULT_MODEL,
            True,
        ),
        (
            "openrouter",
            app_config.OPENROUTER_API_BASE_URL,
            app_config.OpenRouter,
            app_config.OPENROUTER_DEFAULT_MODEL,
            True,
        ),
    ]
    providers = []
    for name, base_url, api_key, model, strict_support in candidates:
        if api_key:
            providers.append(
                ProviderConfig(
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    supports_strict_schema=strict_support,
                )
            )
    return providers


class GeminiClientPool:
    """Multi-provider OpenAI-compatible pool with task routing, cooldowns, and error rotation."""

    _instance: "GeminiClientPool | None" = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._providers = _load_providers()
        if not self._providers:
            raise GenerationError("No LLM API keys configured (see .env)")
        self._provider_index = 0
        self._cooldowns: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._last_call_at = 0.0
        self._http: httpx.AsyncClient | None = None
        self._initialized = True

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            verify_target = _default_ssl_context()
            self._http = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, verify=verify_target
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def _next_provider(self) -> ProviderConfig:
        provider = self._providers[self._provider_index]
        self._provider_index = (self._provider_index + 1) % len(self._providers)
        return provider

    @staticmethod
    def _is_quota_error(error: GenerationError) -> bool:
        message = str(error).lower()
        return any(
            token in message
            for token in (
                "429",
                "413",
                "resource_exhausted",
                "insufficient_quota",
                "quota",
                "rate limit",
                "too many requests",
                "requests_per_minute",
                "tokens per minute",
                "tpm",
                "request too large",
            )
        )

    async def _call_provider(
        self,
        provider: ProviderConfig,
        prompt: str,
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        model_override: str | None = None,
        schema: dict | None = None,
        schema_name: str = "c1_theory_schema",
        strict_raw_response: bool = False,
    ) -> LLMResponse:
        model_name = model_override or provider.model
        tokens = max_output_tokens

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": tokens,
        }
        if schema:
            if provider.supports_strict_schema:
                provider_schema = _clean_schema_for_provider(schema, provider.name)
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": provider_schema,
                    },
                }
            else:
                # Standard JSON mode for providers without native strict schema enforcement (Groq, Mistral, OpenRouter)
                payload["response_format"] = {"type": "json_object"}
        else:
            payload["response_format"] = {"type": "json_object"}
        if provider.name == "groq" and "gpt-oss" in model_name:
            payload["reasoning_effort"] = "low"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self.http.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            raise GenerationError(f"{provider.name}: request timed out")
        except httpx.HTTPError as exc:
            raise GenerationError(f"{provider.name}: network error: {exc}")

        # Auto-fallback for Groq: if 120b encounters 429 (e.g. daily 200k TPD exhausted),
        # automatically fall back to openai/gpt-oss-20b on the same Groq key.
        if (
            response.status_code == 429
            and provider.name == "groq"
            and "120b" in model_name
        ):
            logger.warning(
                "Groq 120b rate/quota limit reached (429). Falling back to openai/gpt-oss-20b..."
            )
            payload["model"] = "openai/gpt-oss-20b"
            model_name = "openai/gpt-oss-20b"
            try:
                response = await self.http.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                raise GenerationError(
                    f"{provider.name} (fallback openai/gpt-oss-20b): network error: {exc}"
                )

        # Auto-fallback for Google: if gemini-3.5-flash-lite encounters 429 or 503,
        # automatically fall back to gemini-3.1-flash-lite on the same Google key.
        if (
            response.status_code in (429, 503)
            and provider.name == "google"
            and "3.5-flash-lite" in model_name
        ):
            logger.warning(
                "Google 3.5-flash-lite limit/unavailable (%s). Falling back to gemini-3.1-flash-lite...",
                response.status_code,
            )
            payload["model"] = "gemini-3.1-flash-lite"
            model_name = "gemini-3.1-flash-lite"
            try:
                response = await self.http.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                raise GenerationError(
                    f"{provider.name} (fallback gemini-3.1-flash-lite): network error: {exc}"
                )

        if response.status_code == 200:
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise GenerationError(f"{provider.name}: unexpected response shape")
            if not content or not content.strip():
                raise GenerationError(f"{provider.name}: empty response")

            if strict_raw_response and provider.supports_strict_schema:
                # Zero-permissive mode for C-1: NO stripping fences, NO unescaping.
                # Must be strictly valid raw JSON object directly.
                raw_text = content.strip()
                if raw_text.startswith("```"):
                    raise GenerationError(
                        f"{provider.name} returned markdown-fenced content in strict mode: {raw_text[:100]}"
                    )
                try:
                    json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    preview = raw_text[:300]
                    raise GenerationError(
                        f"{provider.name} returned invalid JSON in strict mode ({exc}). "
                        f"Raw preview: {preview}"
                    ) from exc

                usage = body.get("usage") or {}
                return LLMResponse(
                    text=raw_text,
                    prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                    provider=provider.name,
                    model=model_name,
                )

            # Detect truncated / malformed JSON early (deviation #8 of docs/07).
            # Gemini can return HTTP 200 with a partial JSON body.  Validating
            # here triggers rotation to the next provider immediately instead of
            # letting the broken payload propagate to generation.py's retry loop.
            stripped = _strip_md_fences(content)
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                # Free OpenAI-compatible models (groq gpt-oss etc.) often
                # double-encode the array as an escaped JSON string, e.g.
                # [[\"D_doc\",...]] — semantically valid, just backslash-quoted.
                # Accept it here so the parser in generation.py can recover it
                # instead of rotating away from an otherwise-good provider.
                try:
                    json.loads(stripped.replace('\\"', '"'))
                except json.JSONDecodeError as exc:
                    preview = stripped[:300]
                    raise GenerationError(
                        f"{provider.name} returned invalid JSON ({exc}). "
                        f"Raw preview: {preview}"
                    ) from exc

            usage = body.get("usage") or {}
            return LLMResponse(
                text=stripped,
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                provider=provider.name,
                model=model_name,
            )

        try:
            error_body = response.json()
            if isinstance(error_body, dict) and isinstance(
                error_body.get("error"), dict
            ):
                detail = error_body["error"].get("message", json.dumps(error_body))
            else:
                detail = json.dumps(error_body)[:500]
        except ValueError:
            detail = response.text[:500]
        raise GenerationError(f"{provider.name}: HTTP {response.status_code} {detail}")

    async def generate_json(
        self,
        prompt: str,
        *,
        allowed_providers: list[str] | None = None,
        preferred_provider: str | None = None,
        schema: dict | None = None,
        schema_name: str = "c1_theory_schema",
        require_strict_schema: bool = False,
        strict_raw_response: bool = False,
        temperature: float = app_config.LLM_DEFAULT_TEMPERATURE,
        top_p: float = app_config.LLM_DEFAULT_TOP_P,
        max_output_tokens: int = app_config.LLM_DEFAULT_MAX_OUTPUT_TOKENS,
        model: str | None = None,
    ) -> LLMResponse:
        """Try eligible providers with cooldown awareness, routing, and error rotation.

        `allowed_providers` (optional): restrict execution to a specific subset of providers (e.g. ["google"]).
        `preferred_provider` (optional): prioritize a provider first (e.g. "groq" for fast real-time feedback).
        `model` (optional): overrides the model on the **google** provider only
        (used by Generators C-1/C-2 to route to GEMINI_PRO_MODEL).
        """
        available = self._providers
        if allowed_providers:
            allowed_set = set(allowed_providers)
            available = [p for p in available if p.name in allowed_set]

        if require_strict_schema:
            available = [p for p in available if p.supports_strict_schema]

        if not available:
            raise GenerationError(
                f"No active LLM providers matching criteria (allowed={allowed_providers}, strict={require_strict_schema})"
            )

        # Narrow lock: rate limit reservation and provider order calculation
        wait_time = 0.0
        async with self._lock:
            now = time.monotonic()
            if self._last_call_at > 0.0:
                elapsed = now - self._last_call_at
                if elapsed < MIN_INTERVAL_SECONDS:
                    wait_time = MIN_INTERVAL_SECONDS - elapsed

            self._last_call_at = now + wait_time

            ready = [p for p in available if self._cooldowns.get(p.name, 0.0) <= now]
            cooling = [p for p in available if self._cooldowns.get(p.name, 0.0) > now]

            if not ready:
                ready = sorted(cooling, key=lambda p: self._cooldowns.get(p.name, 0.0))
                cooling = []

            if preferred_provider and any(p.name == preferred_provider for p in ready):
                ordered_ready = sorted(
                    ready, key=lambda p: 0 if p.name == preferred_provider else 1
                )
            elif len(ready) > 1:
                start_idx = self._provider_index % len(ready)
                ordered_ready = ready[start_idx:] + ready[:start_idx]
                self._provider_index = (self._provider_index + 1) % len(self._providers)
            else:
                ordered_ready = ready

            cooling_sorted = sorted(
                cooling, key=lambda p: self._cooldowns.get(p.name, 0.0)
            )
            ordered = ordered_ready + cooling_sorted

        if wait_time > 0.0:
            await asyncio.sleep(wait_time)

        last_error: GenerationError | None = None
        for provider in ordered:
            try:
                result = await self._call_provider(
                    provider,
                    prompt,
                    temperature,
                    top_p,
                    max_output_tokens,
                    model_override=model if provider.name == "google" else None,
                    schema=schema,
                    schema_name=schema_name,
                    strict_raw_response=strict_raw_response,
                )
                return result
            except GenerationError as exc:
                last_error = exc
                if self._is_quota_error(exc):
                    async with self._lock:
                        self._cooldowns[provider.name] = (
                            time.monotonic() + PROVIDER_COOLDOWN_SECONDS
                        )
                    await asyncio.sleep(
                        random.uniform(QUOTA_BACKOFF_MIN, QUOTA_BACKOFF_MAX)
                    )
                else:
                    await asyncio.sleep(0.25)

        raise GenerationError(
            f"All providers failed. Last error: {last_error}"
        ) from last_error


_client_pool: GeminiClientPool | None = None


def get_gemini_client_pool() -> GeminiClientPool:
    global _client_pool
    if _client_pool is None:
        _client_pool = GeminiClientPool()
    return _client_pool


async def close_gemini_client_pool() -> None:
    global _client_pool
    if _client_pool is not None:
        await _client_pool.close()
        _client_pool = None
