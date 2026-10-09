import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from app.core.infra.config import app_config
from app.core.infra.limiter import limiter

from app.feature.audio.audio_schema import (
    PronunciationResponse,
    STTResponse,
    TTSGenerateRequest,
    TTSGenerateResponse,
    VocabWordContext,
    VoiceListResponse,
)
from app.feature.audio.pronunciation_service import (
    PronunciationBusyError,
    PronunciationInputError,
    PronunciationDisabledError,
    evaluate_pronunciation,
)
from app.feature.audio.stt_service import process_speech_to_text
from app.feature.audio.tts_service import (
    DEFAULT_VOICE,
    get_voice_list,
    synthesize_to_file,
)
from sqlalchemy.orm import Session

# Import hàm lấy user từ cơ chế Cookie bảo mật mới của bạn
from app.core.infra.database import get_db
from app.core.infra.dependencies import get_current_user 

logger = logging.getLogger(__name__)
router = APIRouter()

# Giới hạn kích thước file âm thanh tối đa (Ví dụ: 10 MB) để tránh tràn bộ nhớ RAM (OOM)
MAX_AUDIO_FILE_SIZE = app_config.MAX_AUDIO_FILE_SIZE 


@router.get("/voices", response_model=VoiceListResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
def list_voices(
    request: Request,
    current_user = Depends(get_current_user), # Bắt buộc đăng nhập
):
    """
    Get all supported TOEIC English voices (US, UK, AU, CA accents).
    Protected by authentication and rate limiting.
    """
    return get_voice_list()


@router.get("/tts/stream", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def stream_tts(
    request: Request,
    text: str = Query(..., min_length=1, max_length=5000, description="Text to synthesize"),
    voice: str = Query(DEFAULT_VOICE, description="Voice ID, e.g. en-US-JennyNeural"),
    rate: str = Query("+0%", description="Speed adjustment e.g. -10%, +0%, +15%"),
    pitch: str = Query("+0Hz", description="Pitch adjustment e.g. +0Hz"),
    current_user = Depends(get_current_user), # Bắt buộc đăng nhập
    db: Session = Depends(get_db),
):
    """
    Stream MP3 audio directly. Protected against unauthenticated access and spamming.
    """
    db.close()
    try:
        file_path, _ = await synthesize_to_file(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        return FileResponse(
            path=str(file_path),
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
            detail="Failed to stream TTS audio. Please try again later.",
        ) from e


@router.post(
    "/tts/generate",
    response_model=TTSGenerateResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("15/minute")
async def generate_tts(
    request: Request,
    body_request: TTSGenerateRequest,
    current_user = Depends(get_current_user), # Bắt buộc đăng nhập
    db: Session = Depends(get_db),
):
    """
    Generate and cache an MP3 audio file on the server.
    Protected to prevent quota burn.
    """
    db.close()
    try:
        file_path, was_cached = await synthesize_to_file(
            text=body_request.text,
            voice=body_request.voice,
            rate=body_request.rate,
            pitch=body_request.pitch,
        )
        return TTSGenerateResponse(
            audio_url=f"{app_config.STATIC_URL_PREFIX.rstrip('/')}/audio_cache/{file_path.name}",
            filename=file_path.name,
            cached=was_cached,
            voice=body_request.voice,
            rate=body_request.rate,
            text_length=len(body_request.text),
        )
    except Exception as e:
        logger.exception("Failed to generate TTS audio")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate TTS audio. Please try again later.",
        ) from e


@router.post("/stt", response_model=STTResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute") # Giới hạn 10 request/phút để tránh lạm dụng STT
async def speech_to_text(
    request: Request,
    audio_file: UploadFile = File(..., description="Audio recording file (.webm, .wav, .mp3, etc.)"),
    target_text: str | None = Form(None, description="Optional target phrase for pronunciation evaluation"),
    current_user = Depends(get_current_user), # Bắt buộc đăng nhập qua HttpOnly Cookie
    db: Session = Depends(get_db),
):
    """
    Transcribe user speech with strict file size validation and rate-limiting to prevent memory exhaustion (OOM).
    """
    db.close()
    try:
        # KIỂM TRA DUNG LƯỢNG FILE AN TOÀN TRƯỚC KHI ĐỌC VÀO RAM
        audio_bytes = await audio_file.read(MAX_AUDIO_FILE_SIZE + 1)
        if len(audio_bytes) > MAX_AUDIO_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Audio file size exceeds the maximum allowed limit (10MB).",
            )
        
        mime_type = audio_file.content_type or "audio/webm"
        return await process_speech_to_text(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            target_text=target_text,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to process speech to text")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process speech to text. Please try again later.",
        ) from e


@router.post(
    "/pronunciation",
    response_model=PronunciationResponse,
    status_code=status.HTTP_200_OK,
)
# Deliberately stricter than /stt's 10/minute: each call is seconds of pinned CPU
# for the Wav2Vec2 forward passes, plus an LLM round-trip.
@limiter.limit("5/minute")
async def assess_pronunciation(
    request: Request,
    audio_file: UploadFile = File(..., description="Audio recording file (.webm, .wav, .mp3, etc.)"),
    expected_text: str = Form(..., description="The sentence the learner was asked to read aloud"),
    word_context: str | None = Form(
        None,
        description="Optional JSON VocabWordContext; send it when the target is one "
        "vocabulary term so the coaching comes from prompts F4/F5 instead of F1/F2",
    ),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Score a recording at the phoneme level and return AI coaching feedback.

    Unlike /stt, the target sentence is required: the engine has no reference-free mode.
    """
    db.close()
    try:
        parsed_word_context = None
        if word_context and word_context.strip():
            try:
                parsed_word_context = VocabWordContext.model_validate_json(word_context)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid word_context payload: {e!s}",
                ) from e

        # Same safe size check as /stt: read one byte past the cap rather than
        # pulling an unbounded upload into RAM.
        audio_bytes = await audio_file.read(MAX_AUDIO_FILE_SIZE + 1)
        if len(audio_bytes) > MAX_AUDIO_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Audio file size exceeds the maximum allowed limit (10MB).",
            )

        mime_type = audio_file.content_type or "audio/webm"
        return await evaluate_pronunciation(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            expected_text=expected_text,
            word_context=parsed_word_context,
        )
    except HTTPException:
        raise
    except PronunciationInputError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except PronunciationDisabledError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except PronunciationBusyError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
            headers={"Retry-After": "30"},
        ) from e
    except Exception as e:
        logger.exception("Failed to assess pronunciation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assess pronunciation. Please try again later.",
        ) from e
