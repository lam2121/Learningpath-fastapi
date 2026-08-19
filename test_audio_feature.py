import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.feature.audio.stt_service import calculate_similarity_and_diff
from app.feature.audio.tts_service import (
    DEFAULT_VOICE,
    get_voice_list,
    synthesize_to_file,
)
from app.main import app


def test_voice_list():
    """Verify supported English voices."""
    voices_resp = get_voice_list()
    assert len(voices_resp.voices) >= 8
    voice_ids = [v.id for v in voices_resp.voices]
    assert "en-US-JennyNeural" in voice_ids
    assert "en-GB-SoniaNeural" in voice_ids
    assert "en-AU-NatashaNeural" in voice_ids
    assert "en-CA-ClaraNeural" in voice_ids
    print("✅ Voice list test passed:", len(voices_resp.voices), "voices available.")


def test_similarity_diff():
    """Verify pronunciation similarity and word diff calculation."""
    target = "The server crashed due to a memory leak"

    # Perfect match
    score, diff, missing, extra, feedback = calculate_similarity_and_diff(target, target)
    assert score == 100.0
    assert len(missing) == 0
    assert all(d.status == "correct" for d in diff)
    print("✅ Perfect match test passed:", score)

    # Partial match
    spoken = "The server crashed due to memory lake"
    score, diff, missing, extra, feedback = calculate_similarity_and_diff(target, spoken)
    assert 60.0 <= score <= 95.0
    assert "leak" in missing or "a" in missing
    print("✅ Partial match test passed:", score, "Missing:", missing, "Extra:", extra)


def test_fastapi_endpoints():
    """Test API endpoints via TestClient."""
    client = TestClient(app)

    # 1. Test GET /api/audio/voices
    res = client.get("/api/audio/voices")
    assert res.status_code == 200
    data = res.json()
    assert "voices" in data
    assert len(data["voices"]) > 0
    print("✅ GET /api/audio/voices endpoint passed.")

    # 2. Test POST /api/audio/tts/generate
    res = client.post(
        "/api/audio/tts/generate",
        json={
            "text": "Hello world from TOEIC CareerPath audio integration test.",
            "voice": DEFAULT_VOICE,
            "rate": "+0%",
        },
    )
    if res.status_code != 200:
        print("Generate failed:", res.status_code, res.text)
    assert res.status_code == 200

    data = res.json()
    assert data["audio_url"].startswith("/static/audio_cache/")
    assert Path("static/audio_cache") / data["filename"]
    print("✅ POST /api/audio/tts/generate endpoint passed. Audio URL:", data["audio_url"])

    # 3. Test GET /api/audio/tts/stream
    res = client.get(
        "/api/audio/tts/stream",
        params={
            "text": "Welcome to our testing suite.",
            "voice": "en-GB-SoniaNeural",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("content-type") == "audio/mpeg"
    assert len(res.content) > 1000
    print("✅ GET /api/audio/tts/stream endpoint passed. Streamed bytes:", len(res.content))


if __name__ == "__main__":
    print("🚀 Running Audio Feature Tests...")
    test_voice_list()
    test_similarity_diff()
    test_fastapi_endpoints()
    print("🎉 All backend audio tests passed successfully!")
