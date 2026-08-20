import base64
import difflib
import logging
import string

import httpx

from app.core.config import app_config
from app.feature.audio.audio_schema import STTResponse, STTWordMatch

logger = logging.getLogger(__name__)


def clean_text_tokens(text: str) -> list[str]:
    """Normalize text and split into clean lowercase word tokens."""
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return [w for w in text.split() if w.strip()]


def calculate_similarity_and_diff(
    target_text: str, transcript: str
) -> tuple[float, list[STTWordMatch], list[str], list[str], str]:
    """
    Compare transcript against target text using word alignment and SequenceMatcher.
    Returns (accuracy_score, word_analysis, missing_words, extra_words, feedback).
    """
    target_words = clean_text_tokens(target_text)
    trans_words = clean_text_tokens(transcript)

    if not target_words:
        return 100.0, [], [], [], "No target text provided for comparison."

    if not trans_words:
        return 0.0, [STTWordMatch(word=w, status="missing") for w in target_words], target_words, [], "No audible speech was recognized. Please speak clearly into the microphone."

    # Use SequenceMatcher to align words
    matcher = difflib.SequenceMatcher(None, target_words, trans_words)
    ratio = matcher.ratio()  # 0.0 to 1.0
    accuracy_score = round(ratio * 100.0, 1)

    word_analysis: list[STTWordMatch] = []
    missing_words: list[str] = []
    extra_words: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for w in target_words[i1:i2]:
                word_analysis.append(STTWordMatch(word=w, status="correct"))
        elif tag == "replace":
            for w in target_words[i1:i2]:
                word_analysis.append(STTWordMatch(word=w, status="mispronounced"))
                missing_words.append(w)
            for w in trans_words[j1:j2]:
                extra_words.append(w)
        elif tag == "delete":
            for w in target_words[i1:i2]:
                word_analysis.append(STTWordMatch(word=w, status="missing"))
                missing_words.append(w)
        elif tag == "insert":
            for w in trans_words[j1:j2]:
                word_analysis.append(STTWordMatch(word=w, status="extra"))
                extra_words.append(w)

    # Generate constructive pedagogical feedback
    if accuracy_score >= 90:
        feedback = "Outstanding pronunciation! Your speech was clear, natural, and highly accurate."
    elif accuracy_score >= 75:
        feedback = "Good job! Most words were pronounced clearly. Practice the highlighted words for higher precision."
    elif accuracy_score >= 50:
        missing_str = ", ".join(f"'{w}'" for w in missing_words[:3])
        feedback = f"Fair attempt. Pay close attention to word clarity and rhythm, especially on {missing_str}."
    else:
        feedback = "Keep practicing! Try listening to the sample audio first at 90% speed, then repeat aloud."

    return accuracy_score, word_analysis, missing_words, extra_words, feedback


async def transcribe_audio_gemini(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """
    Transcribe audio bytes using Google Gemini 2.5 Flash Multimodal Audio.
    """
    api_key = app_config.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in .env")

    # Map mime type to valid audio MIME
    clean_mime = mime_type.split(";")[0].strip().lower()
    if clean_mime in ("audio/webm", "video/webm"):
        clean_mime = "audio/webm"
    elif clean_mime in ("audio/wav", "audio/x-wav"):
        clean_mime = "audio/wav"
    elif clean_mime in ("audio/mp3", "audio/mpeg"):
        clean_mime = "audio/mp3"
    elif clean_mime in ("audio/ogg", "audio/oga"):
        clean_mime = "audio/ogg"
    else:
        clean_mime = "audio/webm"

    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{app_config.GEMINI_FLASH_MODEL}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": clean_mime,
                            "data": b64_audio,
                        }
                    },
                    {
                        "text": (
                            "Please transcribe the English speech in this audio accurately. "
                            "Output ONLY the plain transcribed text with no explanations, notes, or quotation marks."
                        )
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 500,
        },
    }

    async with httpx.AsyncClient(
        timeout=30.0,
        verify=not app_config.DISABLE_SSL_VERIFY,
    ) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            logger.error(f"Gemini STT API error: {res.status_code} {res.text}")
            raise RuntimeError(f"Gemini API returned status {res.status_code}")

        data = res.json()
        try:
            transcript = (
                data["candidates"][0]["content"]["parts"][0]["text"].strip()
            )
            # Remove enclosing quotes if model added any
            if (transcript.startswith('"') and transcript.endswith('"')) or (
                transcript.startswith("'") and transcript.endswith("'")
            ):
                transcript = transcript[1:-1].strip()
            return transcript
        except (KeyError, IndexError) as exc:
            logger.error(f"Unexpected Gemini response structure: {data}")
            raise RuntimeError("Could not parse transcript from Gemini response") from exc


async def process_speech_to_text(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    target_text: str | None = None,
) -> STTResponse:
    """
    Transcribe audio and evaluate pronunciation accuracy against target_text.
    """
    if not audio_bytes:
        return STTResponse(
            transcript="",
            confidence=0.0,
            target_text=target_text,
            accuracy_score=0.0,
            is_match=False,
            feedback="Empty audio received.",
        )

    try:
        transcript = await transcribe_audio_gemini(audio_bytes, mime_type)
    except Exception as e:
        logger.warning(f"Audio transcription failed: {e}")
        # Return fallback response gracefully
        return STTResponse(
            transcript="",
            confidence=0.0,
            target_text=target_text,
            accuracy_score=0.0,
            is_match=False,
            feedback=f"Speech transcription temporarily unavailable: {e!s}",
        )


    if not target_text or not target_text.strip():
        return STTResponse(
            transcript=transcript,
            confidence=0.95,
            target_text=None,
            accuracy_score=100.0,
            is_match=True,
            feedback="Transcription completed successfully.",
        )

    accuracy_score, word_analysis, missing_words, extra_words, feedback = (
        calculate_similarity_and_diff(target_text, transcript)
    )

    return STTResponse(
        transcript=transcript,
        confidence=0.95,
        target_text=target_text,
        accuracy_score=accuracy_score,
        is_match=accuracy_score >= 80.0,
        word_analysis=word_analysis,
        missing_words=missing_words,
        extra_words=extra_words,
        feedback=feedback,
    )
