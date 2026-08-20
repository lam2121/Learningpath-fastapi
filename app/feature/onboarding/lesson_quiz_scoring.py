PLACEMENT_EVIDENCE_WEIGHT = 3.2
HINT_CREDIT = 0.75
LESSON_PASS_THRESHOLD_PERCENT = 70.0


def normalize_index_answer(answer: str) -> str:
    return "|".join(
        str(index)
        for index in sorted(
            {
                int(part.strip())
                for part in answer.split("|")
                if part.strip() and part.strip().lstrip("-").isdigit()
            }
        )
    )


def compute_lesson_score_percent(
    *,
    correct_no_hint_count: int,
    correct_with_hint_count: int,
    total_questions: int,
) -> float:
    if total_questions <= 0:
        return 0.0
    return (
        (correct_no_hint_count + HINT_CREDIT * correct_with_hint_count)
        / total_questions
    ) * 100


def compute_radar_score_for_skill(
    initial_radar: float, passed_performances: list[float]
) -> float:
    if not passed_performances:
        return float(initial_radar)

    raw = (
        float(initial_radar) * PLACEMENT_EVIDENCE_WEIGHT + sum(passed_performances)
    ) / (PLACEMENT_EVIDENCE_WEIGHT + len(passed_performances))
    return max(0.0, min(100.0, raw))
