from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.models.user import User
from app.feature.onboarding.survey_schema import (
    SurveyQuestionResponse,
    SubmitSurveyRequest,
    SubmitSurveyResponse,
    OnboardingStatusResponse,
    CompletePlacementTestRequest,
    CompletePlacementTestResponse,
)
from app.feature.onboarding.survey_service import (
    fetch_all_surveys,
    save_user_survey_answers,
    has_user_completed_survey,
    complete_placement_test,
)
from app.feature.onboarding.placement_test_schema import PlacementTestQuestionResponse
from app.feature.onboarding.placement_test_service import fetch_questions_by_role

router = APIRouter()

@router.get("/status", response_model=OnboardingStatusResponse, status_code=status.HTTP_200_OK)
def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Check if the authenticated user has completed the onboarding survey and placement test.
    """
    if not current_user:
        return OnboardingStatusResponse(user_id=0, has_completed_survey=False, is_finished_placement_test=False)
    
    completed = has_user_completed_survey(db, current_user.id)
    is_finished = getattr(current_user, 'is_finished_placement_test', False)
    return OnboardingStatusResponse(
        user_id=current_user.id,
        has_completed_survey=completed,
        is_finished_placement_test=bool(is_finished)
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

@router.post("/placement-test/complete", response_model=CompletePlacementTestResponse, status_code=status.HTTP_200_OK)
def finalize_placement_test(
    request: CompletePlacementTestRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Finalize onboarding: save placement test answers, set user role_id, and set is_finished_placement_test = 1.
    """
    try:
        if current_user:
            user_id = current_user.id
        elif request.user_id:
            user_id = request.user_id
        else:
            fallback_user = db.query(User).first()
            if not fallback_user:
                raise ValueError("No user found in database for placement test fallback")
            user_id = fallback_user.id

        complete_placement_test(
            db,
            user_id=user_id,
            role_id=request.role_id,
            placement_test_answers=request.placement_test_answers
        )
        return CompletePlacementTestResponse(
            message="Placement test completed and onboarding saved successfully",
            is_finished_placement_test=True
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to finalize placement test: {str(e)}"
        )


@router.get("/placement-test/questions", response_model=List[PlacementTestQuestionResponse], status_code=status.HTTP_200_OK)
def get_placement_test_questions(
    role_id: int = Query(..., description="job_role_id to filter questions"),
    db: Session = Depends(get_db),
):
    """
    Return all placement_test_question rows for the given job_role_id.
    The frontend adaptive engine picks 24 questions from this pool.
    Returns an empty list if no questions exist for the role.
    """
    try:
        return fetch_questions_by_role(db, role_id=role_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch placement test questions: {str(e)}"
        )
