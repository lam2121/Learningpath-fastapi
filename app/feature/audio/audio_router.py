import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.feature.audio.audio_schema import (
    STTResponse,
    TTSGenerateRequest,
    TTSGenerateResponse,
    VoiceListResponse,
)
from app.feature.audio.stt_service import process_speech_to_text
from app.feature.audio.tts_service import (
    DEFAULT_VOICE,
    get_voice_list,
    stream_audio_chunks,
    synthesize_to_file,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/voices", response_model=VoiceListResponse, status_code=status.HTTP_200_OK)
def list_voices():
    """
    Get all supported TOEIC English voices (US, UK, AU, CA accents).
    """
    return get_voice_list()


@router.get("/tts/stream", status_code=status.HTTP_200_OK)
async def stream_tts(
    text: str = Query(..., min_length=1, max_length=5000, description="Text to synthesize"),
    voice: str = Query(DEFAULT_VOICE, description="Voice ID, e.g. en-US-JennyNeural"),
    rate: str = Query("+0%", description="Speed adjustment e.g. -10%, +0%, +15%"),
    pitch: str = Query("+0Hz", description="Pitch adjustment e.g. +0Hz"),
):
    """
    Stream MP3 audio directly for instant playback in <audio> tags or web players.
    Cached responses return instantly.
    """
    try:
        return StreamingResponse(
            stream_audio_chunks(text=text, voice=voice, rate=rate, pitch=pitch),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Disposition": 'inline; filename="speech.mp3"',
            },
        )
    except Exception as e:
        logger.exception("Failed to stream TTS audio")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream TTS audio: {e!s}",
        ) from e


@router.post(
    "/tts/generate",
    response_model=TTSGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_tts(request: TTSGenerateRequest):
    """
    Generate and cache an MP3 audio file on the server.
    Returns the static URL for the cached audio.
    """
    try:
        file_path, was_cached = await synthesize_to_file(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            pitch=request.pitch,
        )
        return TTSGenerateResponse(
            audio_url=f"/static/audio_cache/{file_path.name}",
            filename=file_path.name,
            cached=was_cached,
            voice=request.voice,
            rate=request.rate,
            text_length=len(request.text),
        )
    except Exception as e:
        logger.exception("Failed to generate TTS audio")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate TTS audio: {e!s}",
        ) from e


@router.post("/stt", response_model=STTResponse, status_code=status.HTTP_200_OK)
async def speech_to_text(
    audio_file: UploadFile = File(..., description="Audio recording file (.webm, .wav, .mp3, etc.)"),
    target_text: str | None = Form(None, description="Optional target phrase for pronunciation evaluation"),
):
    """
    Transcribe uploaded user speech and calculate pronunciation accuracy against target_text.
    """
    try:
        audio_bytes = await audio_file.read()
        mime_type = audio_file.content_type or "audio/webm"
        return await process_speech_to_text(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            target_text=target_text,
        )
    except Exception as e:
        logger.exception("Failed to process speech to text")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process speech to text: {e!s}",
        ) from e
