"""Multi-provider LLM client pool for admin content generation.

All providers are called through their OpenAI-compatible chat-completions
endpoints (Google Gemini exposes one at /v1beta/openai). Providers are rotated
round-robin on 429/quota/5xx/network errors with exponential backoff and a
short per-provider cooldown so an exhausted key is not hammered repeatedly.

- response_format={"type": "json_object"} everywhere
- request timeout
- simple global rate limit (~250 RPM, spec §7.2)
- kill-switch guard: raises when `ai_generation_enabled=false`
"""

import asyncio
import json
import os
import random
import ssl
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.config import app_config
from app.models.system_setting import SystemSetting

AI_GENERATION_ENABLED_KEY = "ai_generation_enabled"

# spec §7.2: Gemini Flash ~360 RPM, we use a ~70% safe threshold
RATE_LIMIT_RPM = 250
MIN_INTERVAL_SECONDS = 60.0 / RATE_LIMIT_RPM

REQUEST_TIMEOUT_SECONDS = 90.0

# Backoff config for 429/quota errors
QUOTA_BACKOFF_MIN = 1.0
QUOTA_BACKOFF_MAX = 10.0
PROVIDER_COOLDOWN_SECONDS = 20.0

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
    """Build the provider registry from configured API keys.

    Order = preference order (primary first). Only keys that are present and
    were verified during testing are included. Google's OpenAI-compatible
    endpoint is used for Gemini so a single client code path works everywhere.
    """
    candidates = [
        (
            "google",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            app_config.GEMINI_API_KEY,
            app_config.GEMINI_FLASH_MODEL,
        ),
        (
            "groq",
            "https://api.groq.com/openai/v1",
            app_config.Groq,
            "llama-3.3-70b-versatile",
        ),
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            app_config.OpenRouter,
            "meta-llama/llama-3.3-70b-instruct",
        ),
        (
            "mistral",
            "https://api.mistral.ai/v1",
            app_config.Mistral,
            "mistral-large-latest",
        ),
        (
            "nvidia",
            "https://integrate.api.nvidia.com/v1",
            app_config.Nvidia,
            "meta/llama-3.1-8b-instruct",
        ),
        (
            "huggingface",
            "https://router.huggingface.co/v1",
            app_config.HuggingFace,
            "meta-llama/Llama-3.1-8B-Instruct",
        ),
    ]
    providers = []
    for name, base_url, api_key, model in candidates:
        if api_key:
            providers.append(ProviderConfig(name, base_url, api_key, model))
    return providers


class GeminiClientPool:
    """Round-robin multi-provider OpenAI-compatible pool with rotation on errors."""

    def __init__(self):
        self._providers = _load_providers()
        if not self._providers:
            raise GenerationError("No LLM API keys configured (see .env)")
        self._provider_index = 0
        self._cooldowns: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._last_call_at = 0.0
        verify_target = _default_ssl_context() if app_config.SSL_VERIFY else False
        self._http = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, verify=verify_target
        )

    async def close(self) -> None:
        await self._http.aclose()

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
                "resource_exhausted",
                "insufficient_quota",
                "quota",
                "rate limit",
                "too many requests",
                "requests_per_minute",
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
    ) -> LLMResponse:
        payload = {
            "model": model_override or provider.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            raise GenerationError(f"{provider.name}: request timed out")
        except httpx.HTTPError as exc:
            raise GenerationError(f"{provider.name}: network error: {exc}")

        if response.status_code == 200:
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise GenerationError(f"{provider.name}: unexpected response shape")
            if not content or not content.strip():
                raise GenerationError(f"{provider.name}: empty response")
            # We do NOT parse the JSON here using json.loads(content).
            # The caller (e.g., generation.py) has robust parsing logic that strips Markdown 
            # and sends validation feedback to the LLM on JSONDecodeError. 
            # If we raise here, it breaks the retry loop.
            usage = body.get("usage") or {}
            return LLMResponse(
                text=content,
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                provider=provider.name,
                model=provider.model,
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
        temperature: float = 0.3,
        top_p: float = 0.8,
        max_output_tokens: int = 2048,
        model: str | None = None,
    ) -> LLMResponse:
        """
        Try each provider in round-robin until one succeeds.

        `model` (optional) overrides the model on the **google** provider only
        (used by Generators C-1/C-2 to route to GEMINI_PRO_MODEL). The other
        providers keep their own configured model as a last-resort fallback, so
        rotation is preserved.

        Quota errors put the provider on cooldown and rotate to the next one
        with a short backoff. After all providers are exhausted, raises
        GenerationError with the last failure.
        """
        now = time.monotonic()
        ordered = [p for p in self._providers if self._cooldowns.get(p.name, 0) <= now]
        if not ordered:
            # Every provider is cooling down: force the round-robin rotation
            # and let the next call naturally try the least-recently used one.
            ordered = list(self._providers)

        last_error: GenerationError | None = None

        async with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < MIN_INTERVAL_SECONDS:
                await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)

            for provider in ordered:
                try:
                    result = await self._call_provider(
                        provider,
                        prompt,
                        temperature,
                        top_p,
                        max_output_tokens,
                        model_override=model if provider.name == "google" else None,
                    )
                    return result
                except GenerationError as exc:
                    last_error = exc
                    if self._is_quota_error(exc):
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
