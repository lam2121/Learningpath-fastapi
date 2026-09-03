import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException,Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

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
    synthesize_to_file,
)
# Import hàm lấy user từ cơ chế Cookie bảo mật mới của bạn
from app.core.dependencies import get_current_user 

logger = logging.getLogger(__name__)
router = APIRouter()

# Khởi tạo bộ giới hạn tốc độ (Rate Limiter)
limiter = Limiter(key_func=get_remote_address)

# Giới hạn kích thước file âm thanh tối đa (Ví dụ: 10 MB) để tránh tràn bộ nhớ RAM (OOM)
MAX_AUDIO_FILE_SIZE = 10 * 1024 * 1024 


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
):
    """
    Stream MP3 audio directly. Protected against unauthenticated access and spamming.
    """
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
            detail=f"Failed to stream TTS audio: {e!s}",
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
):
    """
    Generate and cache an MP3 audio file on the server.
    Protected to prevent quota burn.
    """
    try:
        file_path, was_cached = await synthesize_to_file(
            text=body_request.text,
            voice=body_request.voice,
            rate=body_request.rate,
            pitch=body_request.pitch,
        )
        return TTSGenerateResponse(
            audio_url=f"/api/static/audio_cache/{file_path.name}",
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
            detail=f"Failed to generate TTS audio: {e!s}",
        ) from e


@router.post("/stt", response_model=STTResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute") # Giới hạn 10 request/phút để tránh lạm dụng STT
async def speech_to_text(
    request: Request,
    audio_file: UploadFile = File(..., description="Audio recording file (.webm, .wav, .mp3, etc.)"),
    target_text: str | None = Form(None, description="Optional target phrase for pronunciation evaluation"),
    current_user = Depends(get_current_user), # Bắt buộc đăng nhập qua HttpOnly Cookie
):
    """
    Transcribe user speech with strict file size validation and rate-limiting to prevent memory exhaustion (OOM).
    """
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
            detail=f"Failed to process speech to text: {e!s}",
        ) from e
