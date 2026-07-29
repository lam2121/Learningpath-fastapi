import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.survey import Survey
from app.models.survey_user import SurveyUser
from app.feature.onboarding.survey_schema import (
    SurveyQuestionResponse,
    SubQuestion,
    SubQuestionOption,
    SubmitSurveyRequest,
)

AXIS_MAPPING = ['C_comm', 'C_comm', 'D_doc', 'T_trouble', 'G_biz', 'C_comm']

def fetch_all_surveys(db: Session) -> List[SurveyQuestionResponse]:
    records = db.query(Survey).order_by(Survey.id.asc()).all()
    results: List[SurveyQuestionResponse] = []

    for index, record in enumerate(records):
        content = record.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                content = {}
        elif not isinstance(content, dict):
            content = {}

        axis = content.get('axis') or content.get('skill_axis')
        if not axis:
            axis = AXIS_MAPPING[index % len(AXIS_MAPPING)]

        sub_q_raw = content.get('subQuestion') or content.get('sub_question')
        sub_question_model = None

        if isinstance(sub_q_raw, dict):
            raw_options = sub_q_raw.get('options', [])
            parsed_options = [
                SubQuestionOption(
                    id=str(opt.get('id', '')),
                    label=str(opt.get('label', opt.get('text', '')))
                )
                for opt in raw_options if isinstance(opt, dict)
            ]
            sub_question_model = SubQuestion(
                question=sub_q_raw.get('question', ''),
                options=parsed_options
            )

        question_item = SurveyQuestionResponse(
            id=str(record.id),
            axis=axis,
            question=content.get('question', ''),
            context=content.get('context', ''),
            subQuestion=sub_question_model
        )
        results.append(question_item)

    return results

from app.models.user import User

def has_user_completed_survey(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.is_finished_placement_test:
        return True
    return db.query(SurveyUser).filter(SurveyUser.user_id == user_id).first() is not None

def save_user_survey_answers(db: Session, user_id: int, answers: List[Any]) -> int:
    # Pre-fetch survey questions content to resolve option IDs to exact labels if needed
    survey_records = {s.id: s.content for s in db.query(Survey).all()}

    # Remove existing survey responses for this user to allow clean updates
    db.query(SurveyUser).filter(SurveyUser.user_id == user_id).delete()

    count = 0
    for item in answers:
        survey_id = getattr(item, 'survey_id', item.get('survey_id') if isinstance(item, dict) else 0)
        rating = getattr(item, 'rating', item.get('rating') if isinstance(item, dict) else None)
        sub_answer = getattr(item, 'sub_answer', item.get('sub_answer') if isinstance(item, dict) else None)

        # If sub_answer is an ID (e.g. 'a', 'b', 'c'), resolve it to full text label from survey content
        if sub_answer and survey_id in survey_records:
            content = survey_records[survey_id]
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except Exception:
                    content = {}
            if isinstance(content, dict):
                sub_q = content.get('subQuestion') or content.get('sub_question')
                if isinstance(sub_q, dict):
                    options = sub_q.get('options', [])
                    for opt in options:
                        if isinstance(opt, dict) and str(opt.get('id')) == str(sub_answer):
                            sub_answer = opt.get('label') or opt.get('text') or sub_answer
                            break

        answer_payload = {
            "rating": rating,
            "subAnswer": sub_answer
        }
        survey_user_record = SurveyUser(
            survey_id=survey_id,
            user_id=user_id,
            answer=answer_payload
        )
        db.add(survey_user_record)
        count += 1

    db.commit()
    return count

def complete_placement_test(
    db: Session,
    user_id: int,
    answers: Optional[List[Any]] = None,
    role_id: Optional[int] = None
) -> bool:
    if answers:
        save_user_survey_answers(db, user_id=user_id, answers=answers)

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        if role_id:
            user.role_id = role_id
        user.is_finished_placement_test = True
        db.commit()
        return True
    return False




