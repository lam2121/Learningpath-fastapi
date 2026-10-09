from pydantic import BaseModel, Field


class FlashcardCreateRequest(BaseModel):
    """One vocabulary card saved from the lesson workspace.

    Field limits mirror the `user_flashcard` columns so an oversized card is
    rejected as a 422 by FastAPI instead of a MySQL "Data too long" error.
    """

    word_eng: str = Field(min_length=1, max_length=45)
    word_vi: str | None = Field(default=None, max_length=50)
    word_ja: str | None = Field(default=None, max_length=150)
    transcription: str | None = Field(default=None, max_length=45)
    context: str | None = Field(default=None, max_length=500)
    workspace_example: str | None = Field(default=None, max_length=500)


class FlashcardResponse(BaseModel):
    id: int
    word_eng: str
    word_vi: str | None = None
    word_ja: str | None = None
    transcription: str | None = None
    context: str | None = None
    workspace_example: str | None = None

    class Config:
        from_attributes = True
