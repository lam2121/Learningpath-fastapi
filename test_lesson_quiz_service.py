import unittest

from app.feature.onboarding.lesson_quiz_service import (
    _extract_best_passing_attempt,
    _extract_best_score,
)
from app.feature.onboarding.lesson_quiz_scoring import (
    compute_lesson_score_percent,
    compute_radar_score_for_skill,
    normalize_index_answer,
)


class LessonQuizServiceTest(unittest.TestCase):
    def test_hint_weighted_lesson_score_matches_design(self):
        score = compute_lesson_score_percent(
            correct_no_hint_count=20,
            correct_with_hint_count=4,
            total_questions=30,
        )
        self.assertAlmostEqual(score, 76.6666666667, places=4)

    def test_radar_score_uses_initial_evidence_plus_first_passes(self):
        score = compute_radar_score_for_skill(68.0, [100.0, 80.0])
        self.assertAlmostEqual(score, 76.4615384615, places=4)

    def test_multi_select_indices_are_normalized_before_compare(self):
        self.assertEqual(normalize_index_answer("2|0|2|1"), "0|1|2")
        self.assertEqual(normalize_index_answer(" 3 | 1 "), "1|3")

    def test_best_score_ignores_failed_attempt(self):
        saved_state = {
            "attempt_count": 1,
            "failed_attempts": 1,
            "latest_attempt": {
                "weighted_score_percent": 40.0,
                "passed": False,
                "answers": [
                    {
                        "question_id": "fill-0",
                        "question_type": "fill_blank",
                        "answer": "wrong",
                        "used_hint": False,
                    }
                ],
            },
        }

        self.assertEqual(_extract_best_score(saved_state, 0.0), 0.0)
        self.assertEqual(_extract_best_passing_attempt(saved_state), {})
        self.assertEqual(saved_state["attempt_count"], 1)
        self.assertEqual(saved_state["failed_attempts"], 1)

    def test_best_attempt_uses_latest_passing_snapshot_with_hints(self):
        saved_state = {
            "attempt_count": 2,
            "failed_attempts": 1,
            "latest_attempt": {
                "weighted_score_percent": 70.0,
                "passed": True,
                "answers": [
                    {
                        "question_id": "fill-1",
                        "question_type": "fill_blank",
                        "answer": "correct",
                        "used_hint": True,
                    }
                ],
            },
            "best_attempt": {
                "weighted_score_percent": 70.0,
                "passed": True,
                "answers": [
                    {
                        "question_id": "fill-1",
                        "question_type": "fill_blank",
                        "answer": "correct",
                        "used_hint": True,
                    }
                ],
                "correct_no_hint_count": 18,
                "correct_with_hint_count": 4,
                "total_questions": 30,
            },
        }

        best_attempt = _extract_best_passing_attempt(saved_state)

        self.assertEqual(_extract_best_score(saved_state, 0.0), 70.0)
        self.assertTrue(best_attempt["answers"][0]["used_hint"])
        self.assertEqual(best_attempt["correct_with_hint_count"], 4)
        self.assertEqual(saved_state["attempt_count"], 2)
        self.assertEqual(saved_state["failed_attempts"], 1)

    def test_best_attempt_prefers_best_attempt_over_legacy_redundant_keys(self):
        saved_state = {
            "best_attempt": {
                "weighted_score_percent": 85.0,
                "passed": True,
                "answers": [
                    {
                        "question_id": "multi-2",
                        "question_type": "multi_select",
                        "answer": "0|2|4",
                        "used_hint": True,
                    }
                ],
            },
            "best_pass_attempt": {
                "weighted_score_percent": 70.0,
                "passed": True,
                "answers": [
                    {
                        "question_id": "multi-2",
                        "question_type": "multi_select",
                        "answer": "0|2",
                        "used_hint": False,
                    }
                ],
            },
        }

        best_attempt = _extract_best_passing_attempt(saved_state)

        self.assertEqual(best_attempt["weighted_score_percent"], 85.0)
        self.assertTrue(best_attempt["answers"][0]["used_hint"])
        self.assertEqual(_extract_best_score(saved_state, 70.0), 85.0)


if __name__ == "__main__":
    unittest.main()
