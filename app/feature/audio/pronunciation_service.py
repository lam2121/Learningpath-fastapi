"""Phoneme-level pronunciation assessment (OpenPronounce) + LLM coaching feedback.

The engine scores the recording; prompts F1/F2 turn that assessment into warm,
specific coaching prose, or F4/F5 when the target is a single vocabulary term.
The engine score is always the ground truth - the LLM only narrates it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import anyio
import httpx

from app.core.infra.config import app_config
from app.feature.audio.audio_schema import (
    PronunciationPhone,
    PronunciationResponse,
    PronunciationWordError,
    VocabWordContext,
)

logger = logging.getLogger(__name__)

# ── HuggingFace SSL shim ─────────────────────────────────────────────────────
# Must run BEFORE transformers/huggingface_hub is imported, and `import
# openpronounce` pulls both in transitively - hence the placement above that
# import rather than in a function. Same corporate-proxy workaround the existing
# audio services apply via DISABLE_SSL_VERIFY.
if app_config.DISABLE_SSL_VERIFY:
    try:
        from huggingface_hub.utils._http import (
            hf_request_event_hook,
            set_client_factory,
        )

        set_client_factory(
            lambda: httpx.Client(
                verify=False,
                event_hooks={"request": [hf_request_event_hook]},
                follow_redirects=True,
                timeout=None,
            )
        )
    except ImportError:  # pragma: no cover - private module, may move upstream
        logger.warning(
            "Could not install the HuggingFace SSL shim; model downloads may fail "
            "behind an intercepting proxy."
        )

# Keep the reference-audio cache beside the app instead of /tmp, which
# tmpreaper/systemd PrivateTmp can wipe out from under us. Matches how
# tts_service.py keeps its MP3 cache under static/.
os.environ.setdefault(
    "OPENPRONOUNCE_CACHE_DIR",
    str((app_config.RESOLVED_STATIC_DIR / app_config.PRONUNCIATION_CACHE_DIR).resolve()),
)

import edge_tts

try:
    import numpy as np
    import librosa
    import openpronounce.tts as op_tts
    from openpronounce import compare_audio_with_text, load_audio, compare_transcriptions
    PRONUNCIATION_AVAILABLE = True
except (ImportError, Exception):
    np = None
    librosa = None
    op_tts = None
    compare_audio_with_text = None
    load_audio = None
    compare_transcriptions = None
    PRONUNCIATION_AVAILABLE = False

from app.feature.audio.tts_service import _init_edge_tts_ssl


# ── OpenPronounce TTS Backend Adaptation (Edge-TTS) ─────────────────────────
# By default, openpronounce uses gTTS (Google Translate TTS) to generate
# reference pronunciation audio. However, Google Translate actively resets or
# blocks unauthenticated automated HTTP connections (ConnectionResetError: 104)
# in corporate/proxy environments. Here, we patch openpronounce's TTS backends
# to use our project's configured edge-tts engine (which respects DISABLE_SSL_VERIFY).
def _synthesize_edge_sync(
    text: str, lang: str, voice: str | None
) -> tuple[Any, int]:
    """Synthesize reference audio for openpronounce using edge-tts."""
    _init_edge_tts_ssl()
    target_voice = voice or app_config.DEFAULT_TTS_VOICE

    async def _generate() -> bytes:
        comm = edge_tts.Communicate(text, target_voice)
        data = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                data.extend(chunk["data"])
        return bytes(data)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            audio_bytes = pool.submit(lambda: asyncio.run(_generate())).result()
    else:
        audio_bytes = asyncio.run(_generate())

    fd, mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="op-ref-")
    os.close(fd)
    try:
        with open(mp3_path, "wb") as f:
            f.write(audio_bytes)
        waveform, sr = librosa.load(mp3_path, sr=None, mono=True)
    finally:
        try:
            os.remove(mp3_path)
        except OSError:
            pass
    return waveform, sr


def _edge_default_voice(lang: str) -> str:
    return app_config.DEFAULT_TTS_VOICE


# Override openpronounce's TTS backends to use edge-tts (if installed)
if PRONUNCIATION_AVAILABLE and op_tts is not None:
    op_tts.BACKENDS["edge_tts"] = (_synthesize_edge_sync, _edge_default_voice)
    op_tts.BACKENDS["gtts"] = (_synthesize_edge_sync, _edge_default_voice)
    op_tts.DEFAULT_BACKEND = "edge_tts"
    os.environ["OPENPRONOUNCE_TTS"] = "edge_tts"

# ── Bounds ───────────────────────────────────────────────────────────────────
_SLOTS = asyncio.Semaphore(max(1, app_config.PRONUNCIATION_MAX_CONCURRENCY))
_MODEL_LOCK = threading.Lock()
_MODELS_READY = False

TARGET_SR = 16000
MAX_ERRORS_IN_PROMPT = 6
SHORT_SUMMARY_MAX_WORDS = 75

_SUFFIX_BY_MIME = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/oga": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}


class PronunciationInputError(Exception):
    """The upload could not be used (undecodable, empty, or too long) -> 422."""


class PronunciationBusyError(Exception):
    """All scoring slots are occupied and the queue wait expired -> 503."""


class PronunciationEngineError(Exception):
    """The scoring engine itself failed -> 500."""


class PronunciationDisabledError(Exception):
    """Pronunciation assessment is disabled because torch/openpronounce are not installed -> 503."""


def _suffix_for(mime_type: str) -> str:
    clean = (mime_type or "").split(";")[0].strip().lower()
    return _SUFFIX_BY_MIME.get(clean, ".webm")


# ── Engine ───────────────────────────────────────────────────────────────────


def _configure_torch_threads() -> None:
    """Cap torch's thread pool.

    torch defaults to every physical core, so two concurrent forward passes each
    try to claim the whole box and thrash. The models themselves are process-wide
    lru_cache singletons, so RAM does not multiply per request - CPU is the only
    scarce resource here.
    """
    try:
        import torch

        torch.set_num_threads(max(1, app_config.PRONUNCIATION_TORCH_THREADS))
    except Exception:  # pragma: no cover
        logger.warning("Could not set torch thread count", exc_info=True)


def warm_up_models() -> None:
    """Populate the Wav2Vec2 caches. Blocking: call from a worker thread.

    Safe to call repeatedly - the underlying models are lru_cache'd, and the lock
    stops two concurrent first-requests from both paying the download.
    """
    global _MODELS_READY
    if not PRONUNCIATION_AVAILABLE:
        logger.warning("Pronunciation model warm-up skipped: torch/openpronounce not installed.")
        return
    with _MODEL_LOCK:
        if _MODELS_READY:
            return
        _configure_torch_threads()
        try:
            import numpy as np

            # Half a second of silence is enough to force both checkpoints to load.
            compare_audio_with_text(
                np.zeros(TARGET_SR // 2, dtype="float32"), "hello world", lang="en"
            )
            _MODELS_READY = True
            logger.info("Pronunciation models ready")
        except Exception:
            # Leave _MODELS_READY False so the next request retries.
            logger.exception("Pronunciation model warm-up failed")


def _probe_duration(file_path: str) -> float | None:
    """Read container duration in seconds using ffprobe without decoding audio samples.

    Returns None if ffprobe is unavailable, times out, or the file lacks duration metadata.
    """
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None
    try:
        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            val = float(res.stdout.strip())
            if val > 0:
                return val
    except Exception:
        pass
    return None


def _safe_load_audio(file_path: str, max_duration_seconds: float) -> np.ndarray:
    """Decode audio into a mono float32 waveform capped at max_duration_seconds.

    Enforces bounds during decoding so decompression-bomb or hour-long uploads
    never decode hundreds of megabytes into memory.
    """
    # 1. Try librosa with duration cap (fast for wav/mp3/flac/ogg)
    try:
        waveform, _ = librosa.load(
            file_path,
            sr=TARGET_SR,
            mono=True,
            duration=max_duration_seconds,
        )
        return waveform
    except Exception:
        pass

    # 2. Fall back to ffmpeg with -t cap (for webm/opus, m4a, etc.)
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg is not installed")

    result = subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-t",
            str(max_duration_seconds),
            "-i",
            file_path,
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-ar",
            str(TARGET_SR),
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.decode("utf-8", "replace").strip()
            or f"ffmpeg failed on {file_path!r}"
        )
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def _score_sync(audio_bytes: bytes, mime_type: str, expected_text: str) -> dict[str, Any]:
    """Decode, score, and clean up. Runs entirely inside one worker thread.

    The temp file never outlives this function, so a client disconnect cannot
    strand it on disk.
    """
    warm_up_models()

    tmp_path = None
    max_duration = float(app_config.PRONUNCIATION_MAX_AUDIO_SECONDS)
    decode_cap = max_duration + 1.0  # Decode at most 31s to catch overflow without memory exhaustion

    try:
        with tempfile.NamedTemporaryFile(
            suffix=_suffix_for(mime_type), delete=False
        ) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # ── Step 1: Pre-decode duration check via ffprobe metadata (Zero RAM) ───
        probed_duration = _probe_duration(tmp_path)
        if probed_duration is not None:
            if probed_duration < 0.3:
                raise PronunciationInputError(
                    "The recording is too short. Please read the whole sentence aloud."
                )
            if probed_duration > max_duration:
                raise PronunciationInputError(
                    f"The recording is {probed_duration:.0f}s long; the limit is "
                    f"{max_duration:.0f}s."
                )

        # ── Step 2: Bounded decoding (Never decodes past decode_cap seconds) ─────
        try:
            waveform = _safe_load_audio(tmp_path, max_duration_seconds=decode_cap)
        except Exception as exc:
            raise PronunciationInputError(
                "Could not decode the audio. Please record again "
                "(ensure ffmpeg is installed on the server)."
            ) from exc

        duration = len(waveform) / TARGET_SR
        if duration < 0.3:
            raise PronunciationInputError(
                "The recording is too short. Please read the whole sentence aloud."
            )
        if duration > max_duration:
            raise PronunciationInputError(
                f"The recording exceeds the limit of {max_duration:.0f}s."
            )

        try:
            result = compare_audio_with_text(waveform, expected_text, lang="en")
        except Exception as exc:
            raise PronunciationEngineError(str(exc)) from exc

        result["_duration_seconds"] = round(duration, 2)
        return result
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── LLM coaching feedback (prompts F1 / F2 / F3) ─────────────────────────────


def _format_errors_detailed(
    errors: list[dict],
    score: float | None = None,
    transcription: str = "",
    expected_text: str = "",
) -> str:
    """Render engine errors as the markdown that fills F2/F5's {errors_section}."""
    if not errors:
        if score is not None and score >= 80:
            return "No mispronunciations detected - the pronunciation was accurate and clear!"
        elif score is not None and score < 60:
            heard_note = f' (speech recognizer heard: "{transcription}")' if transcription else ""
            return (
                f"No fine-grained phoneme alignment isolated, but the overall score is low "
                f"({score:.1f}/100){heard_note}. The audio diverged significantly from "
                f'"{expected_text}" or was unclear. Analyze the sound differences between what was heard and the target.'
            )
        else:
            return "No specific phoneme errors isolated; focus on overall syllable stress and vowel clarity."

    lines: list[str] = []
    for i, err in enumerate(errors, 1):
        word = err.get("word", "?")
        expected = err.get("expected", "?")
        actual = err.get("actual") or "(missing/silent)"
        confidence = err.get("confidence", 0) or 0
        phone_distance = err.get("phone_distance", "?")
        actual_word = err.get("actual_word") or (transcription if len(errors) == 1 and transcription else "")

        lines.append(f'### {i}. "{word}"')
        lines.append(f"- **Expected pronunciation (IPA):** /{expected}/")
        lines.append(f"- **What was heard (IPA):** /{actual}/")
        if actual_word:
            lines.append(f'- **Words heard:** "{actual_word}"')
        lines.append(f"- **Confidence this is an error:** {confidence:.0%}")
        lines.append(f"- **Phone distance:** {phone_distance}")

        phones = err.get("phones") or []
        if phones:
            lines.append("- **Phoneme breakdown:**")
            for p in phones:
                exp = p.get("expected", "?")
                heard = p.get("heard", "") or "∅ (silent)"
                conf = p.get("confidence", 0) or 0
                status = (
                    "correct" if conf < 0.3 else "slightly off" if conf < 0.7 else "wrong"
                )
                lines.append(f"  - Expected /{exp}/ -> Heard /{heard}/ - {status}")
        lines.append("")

    return "\n".join(lines)


def _top_errors(differences: dict[str, Any]) -> list[dict]:
    """Keep the most confident errors only.

    A garbage take can otherwise produce dozens and blow past max_output_tokens.
    """
    errors = differences.get("errors") or []
    return sorted(errors, key=lambda e: e.get("confidence", 0) or 0, reverse=True)[
        :MAX_ERRORS_IN_PROMPT
    ]


def _build_prompt(result: dict[str, Any], expected_text: str) -> str:
    """Assemble F1 (persona) + F2 (data) + F3 (JSON envelope).

    F1 is a system prompt by design, but GeminiClientPool hardcodes its own system
    message, so F1 rides along in the user turn - exactly how D1-D4 and E1 already
    work. F3 carries literal braces and so is concatenated AFTER F2 is formatted,
    never passed through .format().
    """
    from app.core.ai.dispatch.prompts import (
        PROMPT_F1_TEMPLATE,
        PROMPT_F2_TEMPLATE,
        PROMPT_F3_OUTPUT_CONTRACT,
    )

    differences = result.get("differences") or {}
    top_errors = _top_errors(differences)
    score_val = float(result.get("score", 0) or 0)
    transcribe_val = result.get("transcribe", "")

    return (
        PROMPT_F1_TEMPLATE
        + "\n\n"
        + PROMPT_F2_TEMPLATE.format(
            expected_text=expected_text,
            # NOTE: the engine's key is "transcribe", not "transcription".
            transcription=transcribe_val,
            score=f"{score_val:.1f}",
            # F2 formats these with .1%, so they must stay fractions (0.0-1.0).
            wer=float(differences.get("word_error_rate", 0) or 0),
            per=float(differences.get("phoneme_error_rate", 0) or 0),
            errors_section=_format_errors_detailed(
                top_errors,
                score=score_val,
                transcription=transcribe_val,
                expected_text=expected_text,
            ),
        )
        + "\n\n"
        + PROMPT_F3_OUTPUT_CONTRACT
    )


def _build_word_prompt(
    result: dict[str, Any], expected_text: str, ctx: VocabWordContext
) -> str:
    """Assemble F4 (word-level persona) + F5 (card + data) + F3 (JSON envelope).

    Same shape as _build_prompt, for the Section 2 vocabulary cards: the target is a
    single term, so the card's own IPA, meaning and pronunciation guide go into the
    prompt and the coach talks about syllables and phonemes instead of fluency.
    """
    from app.core.ai.dispatch.prompts import (
        PROMPT_F3_OUTPUT_CONTRACT,
        PROMPT_F4_TEMPLATE,
        PROMPT_F5_TEMPLATE,
    )

    differences = result.get("differences") or {}
    target_word = ctx.term.strip() or expected_text
    score_val = float(result.get("score", 0) or 0)
    transcribe_val = result.get("transcribe", "")

    # A generated lesson can leave any card field blank; never show the model a
    # bare empty value it might try to interpret.
    def given(value: str) -> str:
        return value.strip() or "(not provided)"

    return (
        PROMPT_F4_TEMPLATE
        + "\n\n"
        + PROMPT_F5_TEMPLATE.format(
            term=target_word,
            pos=given(ctx.pos),
            ipa=given(ctx.ipa),
            vn_meaning=given(ctx.vn_meaning),
            pronunciation_guide=given(ctx.pronunciation_guide),
            example=given(ctx.example),
            # NOTE: the engine's key is "transcribe", not "transcription".
            transcription=transcribe_val,
            score=f"{score_val:.1f}",
            # F5 formats these with .1%, so they must stay fractions (0.0-1.0).
            wer=float(differences.get("word_error_rate", 0) or 0),
            per=float(differences.get("phoneme_error_rate", 0) or 0),
            errors_section=_format_errors_detailed(
                _top_errors(differences),
                score=score_val,
                transcription=transcribe_val,
                expected_text=target_word,
            ),
        )
        + "\n\n"
        + PROMPT_F3_OUTPUT_CONTRACT
    )


async def _generate_comment(
    result: dict[str, Any],
    expected_text: str,
    word_context: VocabWordContext | None = None,
) -> tuple[str | None, str | None]:
    """Return the LLM's (markdown comment, short summary); None for any missing part.

    Never raises: an expensive, successful score must not be thrown away because a
    free-tier LLM provider hiccuped.
    """
    from app.core.ai.client.gemini import get_gemini_client_pool

    prompt = (
        _build_word_prompt(result, expected_text, word_context)
        if word_context is not None
        else _build_prompt(result, expected_text)
    )

    try:
        client = get_gemini_client_pool()
        response = await client.generate_json(
            prompt,
            preferred_provider="groq",
            max_output_tokens=app_config.PRONUNCIATION_FEEDBACK_MAX_OUTPUT_TOKENS,
        )
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        text = text.removesuffix("```").strip()

        data = json.loads(text)
        summary = (data.get("feedback_summary") or "").strip()
        short = (data.get("short_summary") or "").strip()
        return summary or None, short or None
    except Exception:
        logger.warning("LLM pronunciation feedback unavailable", exc_info=True)
        return None, None


def _cap_words(text: str, limit: int = SHORT_SUMMARY_MAX_WORDS) -> str:
    """Hard word cap: the prompt asks for <= limit words, this guarantees it."""
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(",;:") + "..."


def _fallback_short_summary(
    errors: list[dict],
    score: float | None = None,
    transcription: str = "",
    expected_text: str = "",
) -> str:
    """Build the short summary from engine errors when the LLM gives none."""
    top = sorted(errors, key=lambda e: e.get("confidence", 0) or 0, reverse=True)
    if not top:
        if score is not None and score < 60:
            heard_str = f'heard "{transcription}"' if transcription else "speech was unclear"
            return _cap_words(f'Low score ({score:.0f}/100): {heard_str} instead of "{expected_text}".')
        return "No mispronounced words detected."
    parts = [
        f'"{e.get("word", "?")}": expected /{e.get("expected", "?")}/, '
        f'heard /{e.get("actual") or "silent"}/'
        for e in top
    ]
    return _cap_words("Check " + "; ".join(parts) + ".")


# ── Public entry point ───────────────────────────────────────────────────────


def _build_word_errors(errors: list[dict]) -> list[PronunciationWordError]:
    built: list[PronunciationWordError] = []
    for err in errors:
        built.append(
            PronunciationWordError(
                position=int(err.get("position", 0) or 0),
                word=str(err.get("word", "")),
                expected_ipa=str(err.get("expected", "")),
                heard_ipa=str(err.get("actual") or ""),
                phone_distance=float(err.get("phone_distance", 0) or 0),
                confidence=float(err.get("confidence", 0) or 0),
                phones=[
                    PronunciationPhone(
                        expected=str(p.get("expected", "")),
                        heard=str(p.get("heard") or ""),
                        confidence=float(p.get("confidence", 0) or 0),
                    )
                    for p in (err.get("phones") or [])
                ],
            )
        )
    return built


async def evaluate_pronunciation(
    *,
    audio_bytes: bytes,
    mime_type: str,
    expected_text: str,
    word_context: VocabWordContext | None = None,
) -> PronunciationResponse:
    """Score a recording against `expected_text` and narrate it with the LLM."""
    if not PRONUNCIATION_AVAILABLE:
        raise PronunciationDisabledError(
            "Pronunciation assessment is disabled on this server (torch/openpronounce not installed)."
        )
    expected_text = (expected_text or "").strip()
    if not expected_text:
        raise PronunciationInputError("A target sentence is required.")
    if not audio_bytes:
        raise PronunciationInputError("The recording was empty.")

    # Admission control. Scoring is uninterruptible once torch starts, so we bound
    # the queue here rather than pretending we can time the work out later.
    try:
        await asyncio.wait_for(
            _SLOTS.acquire(),
            timeout=app_config.PRONUNCIATION_QUEUE_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise PronunciationBusyError(
            "The pronunciation coach is busy. Please try again in a moment."
        ) from exc

    try:
        # abandon_on_cancel stays False (the default): cancelling would free the
        # slot while the thread keeps burning cores, which is the exact overload
        # the semaphore exists to prevent.
        result = await anyio.to_thread.run_sync(
            _score_sync, audio_bytes, mime_type, expected_text
        )
    finally:
        _SLOTS.release()

    differences = result.get("differences") or {}
    engine_feedback = (result.get("feedback") or "").strip()
    score_val = round(float(result.get("score", 0) or 0), 2)
    transcription_val = str(result.get("transcribe", "")).strip()

    # If the phone-level engine produced no errors, but the score is low (< 70)
    # or the transcribed text clearly mismatches expected_text, recover word-level
    # errors via text-level comparison so the UI and prompt get accurate error data:
    if not differences.get("errors") and (
        score_val < 70
        or transcription_val.lower() != expected_text.lower().strip()
    ):
        try:
            # compare_transcriptions imported lazily above

            fallback_diff = compare_transcriptions(
                transcription_val,
                expected_text,
                str(result.get("language", "en")),
            )
            fallback_errors = fallback_diff.get("errors") or []
            if fallback_errors:
                synth_conf = max(0.5, round(1.0 - (score_val / 100.0), 2))
                for fe in fallback_errors:
                    if not fe.get("confidence"):
                        fe["confidence"] = synth_conf
                differences["errors"] = fallback_errors
                if not differences.get("words_with_errors"):
                    differences["words_with_errors"] = (
                        fallback_diff.get("words_with_errors") or []
                    )
        except Exception:
            logger.debug("Fallback transcription comparison failed", exc_info=True)

    if differences.get("errors"):
        for fe in differences["errors"]:
            if not fe.get("actual_word") and len(differences["errors"]) == 1 and transcription_val:
                fe["actual_word"] = transcription_val
    result["differences"] = differences

    comment, short_summary = await _generate_comment(result, expected_text, word_context)

    return PronunciationResponse(
        expected_text=expected_text,
        transcript=str(result.get("transcribe", "")),
        score=score_val,
        word_error_rate=float(differences.get("word_error_rate", 0) or 0),
        phoneme_error_rate=float(differences.get("phoneme_error_rate", 0) or 0),
        words_with_errors=[str(w) for w in (differences.get("words_with_errors") or [])],
        errors=_build_word_errors(differences.get("errors") or []),
        duration_seconds=result.get("_duration_seconds"),
        language=str(result.get("language", "en")),
        # The engine score is the ground truth; any score the LLM echoes back is
        # ignored. On LLM failure we fall back to the engine's own terse feedback
        # so the learner still gets their numbers plus a sentence.
        feedback_summary=comment or engine_feedback or "Scores are ready below.",
        llm_feedback_available=comment is not None,
        short_summary=_cap_words(short_summary)
        if short_summary
        else _fallback_short_summary(
            differences.get("errors") or [],
            score=score_val,
            transcription=transcription_val,
            expected_text=expected_text,
        ),
    )
