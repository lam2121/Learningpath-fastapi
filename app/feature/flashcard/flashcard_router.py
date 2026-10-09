from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.infra.database import get_db
from app.core.infra.dependencies import get_current_user
from app.feature.flashcard.flashcard_schema import (
    FlashcardCreateRequest,
    FlashcardResponse,
)
import json
from app.models.lesson import Lesson
from app.models.user import User
from app.models.user_flashcard import UserFlashcard

router = APIRouter()


def _lookup_lesson_meanings(word_eng: str, db: Session) -> tuple[str | None, str | None]:
    target = word_eng.strip().lower()
    if not target:
        return None, None
    lessons = db.query(Lesson.theory_content).all()
    for (tc,) in lessons:
        if not tc:
            continue
        try:
            if isinstance(tc, (dict, list)):
                tc_str = json.dumps(tc, ensure_ascii=False).lower()
                data = tc
            else:
                tc_str = str(tc).lower()
                data = json.loads(tc)
            if target not in tc_str:
                continue
            items = []
            if isinstance(data, dict):
                vocab = data.get("vocab", {})
                if isinstance(vocab, dict):
                    items = vocab.get("items", [])
                elif isinstance(vocab, list):
                    items = vocab
                for s in data.get("sections", []):
                    if isinstance(s, dict) and s.get("items"):
                        items.extend(s["items"])
            elif isinstance(data, list):
                for s in data:
                    if isinstance(s, dict) and s.get("items"):
                        items.extend(s["items"])

            for it in items:
                if not isinstance(it, dict):
                    continue
                term = it.get("term")
                eng = ""
                vi = ""
                ja = ""
                if isinstance(term, dict):
                    eng = term.get("en", "")
                    vi = term.get("vi", "")
                    ja = term.get("ja", "")
                elif isinstance(term, str):
                    eng = term
                if it.get("term_display"):
                    eng = eng or it.get("term_display")
                if it.get("vn_meaning"):
                    vi = vi or it.get("vn_meaning")
                if it.get("ja_meaning"):
                    ja = ja or it.get("ja_meaning")
                if it.get("reading") and not ja:
                    ja = it.get("reading")
                if eng and eng.strip().lower() == target:
                    return vi or None, ja or None
        except Exception:
            continue
    return None, None


@router.get("", response_model=list[FlashcardResponse])
def list_flashcards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UserFlashcard]:
    """Every card the current user has saved.

    The lesson workspace calls this once per vocabulary section to decide which
    hearts render as filled.
    """
    cards = (
        db.query(UserFlashcard)
        .filter(UserFlashcard.user_id == current_user.id)
        .order_by(UserFlashcard.id.desc())
        .all()
    )
    has_updates = False
    for c in cards:
        if not c.word_ja or not c.word_vi:
            l_vi, l_ja = _lookup_lesson_meanings(c.word_eng, db)
            if not c.word_ja and l_ja:
                c.word_ja = l_ja
                has_updates = True
            if not c.word_vi and l_vi:
                c.word_vi = l_vi
                has_updates = True
    if has_updates:
        db.commit()
    return cards


@router.post("", response_model=FlashcardResponse, status_code=status.HTTP_201_CREATED)
def save_flashcard(
    payload: FlashcardCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserFlashcard:
    """Save a vocabulary card for the current user.

    Idempotent by (user_id, word_eng): re-saving a word the user already has
    updates the stored text and returns 200 instead of failing on the unique
    index, so a double-click on the heart cannot error.
    """
    word_eng = payload.word_eng.strip()
    if not word_eng:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="word_eng must not be blank.",
        )

    flashcard = (
        db.query(UserFlashcard)
        .filter(
            UserFlashcard.user_id == current_user.id,
            UserFlashcard.word_eng == word_eng,
        )
        .one_or_none()
    )

    if flashcard is None:
        flashcard = UserFlashcard(user_id=current_user.id, word_eng=word_eng)
        db.add(flashcard)
    else:
        response.status_code = status.HTTP_200_OK

    flashcard.word_vi = payload.word_vi
    flashcard.word_ja = payload.word_ja
    flashcard.transcription = payload.transcription
    flashcard.context = payload.context
    flashcard.workspace_example = payload.workspace_example

    if not flashcard.word_vi or not flashcard.word_ja:
        l_vi, l_ja = _lookup_lesson_meanings(word_eng, db)
        if not flashcard.word_vi and l_vi:
            flashcard.word_vi = l_vi
        if not flashcard.word_ja and l_ja:
            flashcard.word_ja = l_ja

    db.commit()
    db.refresh(flashcard)
    return flashcard


@router.delete("/{flashcard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flashcard(
    flashcard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Remove one saved card. Scoped to the owner so ids cannot be probed."""
    flashcard = (
        db.query(UserFlashcard)
        .filter(
            UserFlashcard.id == flashcard_id,
            UserFlashcard.user_id == current_user.id,
        )
        .one_or_none()
    )
    if flashcard is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Flashcard not found.",
        )

    db.delete(flashcard)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
