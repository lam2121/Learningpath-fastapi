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

# ─── Pronunciation assessment (POST /audio/pronunciation) ────────────────────
# Phoneme-level scoring via OpenPronounce, narrated by prompts F1/F2.
# Deliberately NOT echoed from the engine result: prosody.f0 / prosody.energy,
# differences.expected_vector / transcribed_vector, expected_phones, heard_phones
# and heard_phones_confidence. They are hundreds of floats the UI cannot render.


class PronunciationPhone(BaseModel):
    expected: str = Field(..., description="Expected phone in IPA")
    heard: str = Field(default="", description="Phone actually heard; empty means silent")
    confidence: float = Field(
        ..., description="Confidence that THIS phone is wrong, 0.0 to 1.0"
    )


class PronunciationWordError(BaseModel):
    position: int = Field(..., description="Index of the word in the expected sentence")
    word: str
    expected_ipa: str = Field(..., description="Expected pronunciation in IPA")
    heard_ipa: str = Field(default="", description="What was heard, in IPA")
    phone_distance: float = 0.0
    confidence: float = Field(
        ..., description="Confidence that this word IS mispronounced, 0.0 to 1.0"
    )
    phones: list[PronunciationPhone] = []


class PronunciationResponse(BaseModel):
    expected_text: str
    transcript: str = Field(
        ..., description="What the model heard (engine key is 'transcribe')"
    )
    score: float = Field(..., description="Overall pronunciation score, 0.0 to 100.0")
    # Both rates are fractions (0.0-1.0), not percentages. word_error_rate is a
    # character-level Levenshtein ratio and is noisy: a clean take can report ~0.28
    # purely because the ASR wrote "TO DAY" for "today".
    word_error_rate: float
    phoneme_error_rate: float
    words_with_errors: list[str] = []
    errors: list[PronunciationWordError] = []
    duration_seconds: float | None = None
    language: str = "en"
    feedback_summary: str = Field(
        ..., description="Coaching feedback in markdown, generated from prompts F1/F2"
    )
    llm_feedback_available: bool = Field(
        default=True,
        description="False when scoring succeeded but the LLM call failed; "
        "feedback_summary then holds the engine's own terse feedback.",
    )
    short_summary: str = Field(
        default="",
        description="Plain-text recap (<= 75 words) of which words/sounds went wrong; "
        "built from the engine errors when the LLM gives none.",
    )


class VocabWordContext(BaseModel):
    """One Section 2 vocabulary card, sent when the target is a single term.

    Present -> the coaching comment is written by prompts F4/F5 (word-level);
    absent -> F1/F2 as before (sentence-level). Every field but `term` is optional
    because a generated lesson can leave any of them blank.
    """

    term: str = Field(..., description="The vocabulary term the learner recorded")
    ipa: str = Field(default="", description="Expected pronunciation in IPA")
    pos: str = Field(default="", description="Part of speech")
    vn_meaning: str = Field(default="", description="Vietnamese meaning")
    pronunciation_guide: str = Field(
        default="", description="The lesson's own syllable/stress note for this term"
    )
    example: str = Field(default="", description="The card's workplace example sentence")
