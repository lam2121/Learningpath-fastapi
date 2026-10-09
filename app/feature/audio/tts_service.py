import hashlib
import logging
import os
import ssl
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import os
import uuid

import aiofiles
import anyio
import edge_tts
import edge_tts.communicate

from app.core.infra.config import app_config
from app.feature.audio.audio_schema import VoiceListResponse, VoiceProfile

logger = logging.getLogger(__name__)

# Directory for cached audio clips
STATIC_DIR = app_config.RESOLVED_STATIC_DIR
AUDIO_CACHE_DIR = STATIC_DIR / "audio_cache"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Audio Cache LRU Eviction Configuration ──────────────────────────────
MAX_CACHE_SIZE_MB = app_config.MAX_CACHE_SIZE_MB          # Maximum total cache folder size in MB
MAX_FILE_AGE_SECONDS = app_config.MAX_FILE_AGE_SECONDS # Auto-delete files not accessed for configured period


def clean_audio_cache() -> None:
    """
    Automatic LRU cache cleanup.
    1. Purge files older than MAX_FILE_AGE_SECONDS (7 days by default).
    2. If total size still exceeds MAX_CACHE_SIZE_MB, evict oldest files first.
    """
    if not AUDIO_CACHE_DIR.exists():
        return

    now = time.time()
    max_bytes = MAX_CACHE_SIZE_MB * 1024 * 1024

    # Phase 1: Remove stale files beyond TTL
    files = list(AUDIO_CACHE_DIR.glob("*.mp3"))
    for f in files:
        try:
            stat = f.stat()
            # Use last-access time (st_atime) for LRU, fall back to mtime
            last_used = max(stat.st_atime, stat.st_mtime)
            if now - last_used > MAX_FILE_AGE_SECONDS:
                f.unlink()
                logger.debug("Cache eviction (TTL): removed %s", f.name)
        except OSError:
            pass

    # Phase 2: Enforce total size cap via LRU eviction
    files = list(AUDIO_CACHE_DIR.glob("*.mp3"))
    if not files:
        return

    # Sort by last access time ascending (oldest first)
    files.sort(key=lambda p: max(p.stat().st_atime, p.stat().st_mtime))
    total_size = sum(f.stat().st_size for f in files)

    evicted = 0
    for f in files:
        if total_size <= max_bytes:
            break
        try:
            fsize = f.stat().st_size
            f.unlink()
            total_size -= fsize
            evicted += 1
        except OSError:
            pass

    if evicted:
        logger.info(
            "Cache eviction (LRU): removed %d files, remaining size %.1f MB",
            evicted,
            total_size / (1024 * 1024),
        )



def _init_edge_tts_ssl():
    """Configure SSL context for edge_tts based on app_config."""
    if app_config.DISABLE_SSL_VERIFY:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        edge_tts.communicate._SSL_CTX = ctx
    elif app_config.SSL_CERT_FILE and Path(app_config.SSL_CERT_FILE).is_file():
        edge_tts.communicate._SSL_CTX = ssl.create_default_context(
            cafile=app_config.SSL_CERT_FILE
        )


_init_edge_tts_ssl()


# Curated multi-accent voices specifically for TOEIC listening sections
SUPPORTED_VOICES: list[VoiceProfile] = [
    VoiceProfile(
        id="en-US-JennyNeural",
        name="Jenny",
        gender="Female",
        accent="US",
        flag="🇺🇸",
        locale="en-US",
        description="Clear, natural American female voice (TOEIC Standard)",
        sample_text="Welcome to the TOEIC CareerPath listening practice.",
    ),
    VoiceProfile(
        id="en-US-GuyNeural",
        name="Guy",
        gender="Male",
        accent="US",
        flag="🇺🇸",
        locale="en-US",
        description="Professional, calm American male voice",
        sample_text="The quarterly financial reports have been uploaded to the shared drive.",
    ),
    VoiceProfile(
        id="en-US-AriaNeural",
        name="Aria",
        gender="Female",
        accent="US",
        flag="🇺🇸",
        locale="en-US",
        description="Conversational American female voice for dialogues",
        sample_text="Could you please send me the updated meeting agenda before noon?",
    ),
    VoiceProfile(
        id="en-GB-SoniaNeural",
        name="Sonia",
        gender="Female",
        accent="UK",
        flag="🇬🇧",
        locale="en-GB",
        description="Refined British female voice (Part 3 & 4 conversations)",
        sample_text="Mind the gap between the train and the platform, please.",
    ),
    VoiceProfile(
        id="en-GB-RyanNeural",
        name="Ryan",
        gender="Male",
        accent="UK",
        flag="🇬🇧",
        locale="en-GB",
        description="Clear British male voice for business dialogues",
        sample_text="We should definitely schedule a follow-up call next Tuesday.",
    ),
    VoiceProfile(
        id="en-AU-NatashaNeural",
        name="Natasha",
        gender="Female",
        accent="AU",
        flag="🇦🇺",
        locale="en-AU",
        description="Friendly Australian female voice",
        sample_text="The flight from Sydney to Melbourne has been delayed by thirty minutes.",
    ),
    VoiceProfile(
        id="en-AU-WilliamNeural",
        name="William",
        gender="Male",
        accent="AU",
        flag="🇦🇺",
        locale="en-AU",
        description="Authentic Australian male voice",
        sample_text="Let's grab a coffee and review the project timeline together.",
    ),
    VoiceProfile(
        id="en-CA-ClaraNeural",
        name="Clara",
        gender="Female",
        accent="CA",
        flag="🇨🇦",
        locale="en-CA",
        description="Natural Canadian female voice",
        sample_text="The software update is now available for download on all workstations.",
    ),
    VoiceProfile(
        id="en-CA-LiamNeural",
        name="Liam",
        gender="Male",
        accent="CA",
        flag="🇨🇦",
        locale="en-CA",
        description="Professional Canadian male voice",
        sample_text="Our team has resolved the database issue and restored full access.",
    ),
]

VOICE_MAP = {v.id: v for v in SUPPORTED_VOICES}
DEFAULT_VOICE = app_config.DEFAULT_TTS_VOICE


def get_voice_list() -> VoiceListResponse:
    """Return the list of curated English voices."""
    return VoiceListResponse(voices=SUPPORTED_VOICES, default_voice=DEFAULT_VOICE)


def get_audio_cache_filename(
    text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz"
) -> str:
    """Generate a deterministic filename for an audio configuration."""
    raw_key = f"{text.strip()}|{voice}|{rate}|{pitch}"
    hash_digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
    return f"{hash_digest}.mp3"


async def synthesize_to_file(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> tuple[Path, bool]:
    """
    Synthesize text to an MP3 file using edge-tts.
    Returns (file_path, was_cached).
    """
    if voice not in VOICE_MAP:
        voice = DEFAULT_VOICE

    filename = get_audio_cache_filename(text, voice, rate, pitch)
    output_path = AUDIO_CACHE_DIR / filename

    # Check cache hit
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path, True

    # Generate via edge-tts into a temporary file first, then atomically replace
    temp_fd, temp_str = tempfile.mkstemp(dir=AUDIO_CACHE_DIR, prefix="tmp_tts_", suffix=".mp3")
    os.close(temp_fd)
    temp_path = Path(temp_str)
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(temp_path))
        if temp_path.exists() and temp_path.stat().st_size > 0:
            os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    # Evict stale / oversized cache entries after writing a new file
    await anyio.to_thread.run_sync(clean_audio_cache)

    return output_path, False


async def stream_audio_chunks(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> AsyncGenerator[bytes, None]:
    """
    Stream MP3 audio chunks. If cached, streams from local file;
    otherwise streams live from edge-tts while saving to cache.
    """
    if voice not in VOICE_MAP:
        voice = DEFAULT_VOICE

    filename = get_audio_cache_filename(text, voice, rate, pitch)
    cached_path = AUDIO_CACHE_DIR / filename

    if cached_path.exists() and cached_path.stat().st_size > 0:
        async with aiofiles.open(cached_path, "rb") as f:
            while chunk := await f.read(64 * 1024):
                yield chunk
        return

    # Stream from edge_tts and write cache in background buffer
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data = chunk["data"]
            buffer.extend(data)
            yield data

    # Save to disk cache atomically for future requests
    if buffer:
        temp_fd, temp_str = tempfile.mkstemp(dir=AUDIO_CACHE_DIR, prefix="tmp_tts_stream_", suffix=".mp3")
        os.close(temp_fd)
        temp_path = Path(temp_str)
        try:
            async with aiofiles.open(temp_path, "wb") as f:
                await f.write(buffer)
            if temp_path.exists() and temp_path.stat().st_size > 0:
                os.replace(temp_path, cached_path)
            # Evict stale / oversized cache entries after writing a new file
            clean_audio_cache()
        except OSError:
            logger.warning(f"Could not save cached audio to {cached_path}")
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

