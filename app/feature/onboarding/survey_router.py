from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.models.user import User
from app.feature.onboarding.survey_schema import (
    SurveyQuestionResponse,
    SubmitSurveyRequest,
    SubmitSurveyResponse,
    OnboardingStatusResponse,
)
from app.feature.onboarding.survey_service import (
    fetch_all_surveys,
    save_user_survey_answers,
    has_user_completed_survey,
)

router = APIRouter()

@router.get("/status", response_model=OnboardingStatusResponse, status_code=status.HTTP_200_OK)
def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Check if the authenticated user has completed the onboarding survey.
    """
    if not current_user:
        return OnboardingStatusResponse(user_id=0, has_completed_survey=False)
    
    completed = has_user_completed_survey(db, current_user.id)
    return OnboardingStatusResponse(
        user_id=current_user.id,
        has_completed_survey=completed
    )

@router.get("/surveys", response_model=List[SurveyQuestionResponse], status_code=status.HTTP_200_OK)
def get_survey_questions(db: Session = Depends(get_db)):
    """
    Get all dynamic survey questions from database.
    """
    try:
        return fetch_all_surveys(db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while fetching survey questions: {str(e)}"
        )

@router.post("/surveys/submit", response_model=SubmitSurveyResponse, status_code=status.HTTP_201_CREATED)
def submit_survey_answers(
    request: SubmitSurveyRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Save user survey ratings and deep-dive sub-answers into survey_user table.
    """
    try:
        user_id = current_user.id if current_user else request.user_id
        saved_count = save_user_survey_answers(db, user_id=user_id, answers=request.answers)
        return SubmitSurveyResponse(
            message="Survey answers recorded successfully",
            recorded_count=saved_count
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit survey answers: {str(e)}"
        )


