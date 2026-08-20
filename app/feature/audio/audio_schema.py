from pydantic import BaseModel, Field


class VoiceProfile(BaseModel):
    id: str = Field(..., description="Voice identifier for edge-tts, e.g. en-US-JennyNeural")
    name: str = Field(..., description="Display name, e.g. Jenny")
    gender: str = Field(..., description="Female or Male")
    accent: str = Field(..., description="Accent code/name, e.g. US, UK, AU, CA")
    flag: str = Field(..., description="Country flag emoji, e.g. 🇺🇸, 🇬🇧, 🇦🇺, 🇨🇦")
    locale: str = Field(..., description="Locale code, e.g. en-US")
    description: str = Field(..., description="Short description of the voice character")
    sample_text: str = Field(
        default="Welcome to the TOEIC CareerPath listening practice.",
        description="Sample phrase for preview",
    )


class VoiceListResponse(BaseModel):
    voices: list[VoiceProfile]
    default_voice: str = "en-US-JennyNeural"


class TTSGenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    voice: str = Field(default="en-US-JennyNeural", description="Voice ID from available voices")
    rate: str = Field(default="+0%", description="Speech speed adjustment, e.g. -10%, +0%, +15%")
    pitch: str = Field(default="+0Hz", description="Pitch adjustment, e.g. +0Hz, +5Hz")


class TTSGenerateResponse(BaseModel):
    audio_url: str
    filename: str
    cached: bool
    voice: str
    rate: str
    text_length: int


class STTWordMatch(BaseModel):
    word: str
    status: str = Field(..., description="correct | missing | mispronounced | extra")


class STTResponse(BaseModel):
    transcript: str
    confidence: float = 1.0
    target_text: str | None = None
    accuracy_score: float = Field(
        ..., description="Pronunciation / matching accuracy score from 0.0 to 100.0"
    )
    is_match: bool
    word_analysis: list[STTWordMatch] = []
    missing_words: list[str] = []
    extra_words: list[str] = []
    feedback: str
