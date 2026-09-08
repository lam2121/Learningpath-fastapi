import unittest
from types import SimpleNamespace

from app.feature.user.user_router import (
    _compute_hint_breakdown,
    _derive_lesson_quiz_status,
    _extract_best_passing_attempt,
    _extract_best_passing_score,
    _extract_latest_attempt,
)


class LessonQuizHistoryMappingTest(unittest.TestCase):
    def test_exact_database_record_maps_to_expected_values(self):
        saved_state = {
            "question_results": [
                {
                    "question_id": f"q-{index}",
                    "used_hint": True,
                    "is_correct": True,
                }
                for index in range(30)
            ],
            "weighted_score_percent": 75.0,
            "passed": True,
            "submitted_at": "2026-08-20T04:08:19",
        }

        best_attempt = _extract_best_passing_attempt(saved_state)
        latest_attempt = _extract_latest_attempt(saved_state)
        breakdown = _compute_hint_breakdown(best_attempt)
        user_lesson = SimpleNamespace(status="completed")

        self.assertEqual(_extract_best_passing_score(saved_state, 75.0), 75.0)
        self.assertEqual(best_attempt["weighted_score_percent"], 75.0)
        self.assertEqual(latest_attempt["submitted_at"], "2026-08-20T04:08:19")
        self.assertEqual(breakdown, (0, 0, 30, 30, 30))
        self.assertEqual(
            _derive_lesson_quiz_status(
                user_lesson,
                best_attempt=best_attempt,
                latest_attempt=latest_attempt,
            ),
            "passed",
        )

    def test_user_with_no_quiz_attempt_returns_empty_counts(self):
        saved_state = {}

        self.assertEqual(_extract_best_passing_attempt(saved_state), {})
        self.assertEqual(_extract_latest_attempt(saved_state), {})
        self.assertIsNone(_extract_best_passing_score(saved_state, 0.0))
        self.assertEqual(_compute_hint_breakdown({}), (0, 0, 0, 0, 0))

    def test_failed_attempt_uses_failed_status_and_no_best_score(self):
        saved_state = {
            "latest_attempt": {
                "question_results": [
                    {"used_hint": False, "is_correct": False},
                    {"used_hint": True, "is_correct": True},
                ],
                "weighted_score_percent": 35.0,
                "passed": False,
                "submitted_at": "2026-08-19T10:00:00",
            }
        }

        latest_attempt = _extract_latest_attempt(saved_state)
        user_lesson = SimpleNamespace(status="in_progress")

        self.assertEqual(_extract_best_passing_attempt(saved_state), {})
        self.assertIsNone(_extract_best_passing_score(saved_state, 0.0))
        self.assertEqual(_compute_hint_breakdown({}), (0, 0, 0, 0, 0))
        self.assertEqual(
            _derive_lesson_quiz_status(
                user_lesson,
                best_attempt={},
                latest_attempt=latest_attempt,
            ),
            "failed",
        )

    def test_passed_attempt_without_hints_counts_no_hint_bucket(self):
        saved_state = {
            "best_attempt": {
                "question_results": [
                    {"used_hint": False, "is_correct": True},
                    {"used_hint": False, "is_correct": True},
                    {"used_hint": False, "is_correct": False},
                ],
                "weighted_score_percent": 80.0,
                "passed": True,
            }
        }

        self.assertEqual(_compute_hint_breakdown(saved_state["best_attempt"]), (2, 3, 0, 0, 3))
        self.assertEqual(_extract_best_passing_score(saved_state, 0.0), 80.0)

    def test_passed_attempt_with_hints_counts_hint_bucket(self):
        saved_state = {
            "best_attempt": {
                "question_results": [
                    {"used_hint": True, "is_correct": True},
                    {"used_hint": True, "is_correct": True},
                    {"used_hint": True, "is_correct": False},
                ],
                "weighted_score_percent": 75.0,
                "passed": True,
            }
        }

        self.assertEqual(_compute_hint_breakdown(saved_state["best_attempt"]), (0, 0, 2, 3, 3))
        self.assertEqual(_extract_best_passing_score(saved_state, 0.0), 75.0)

    def test_multiple_attempts_keep_highest_passing_score(self):
        saved_state = {
            "latest_attempt": {
                "question_results": [{"used_hint": True, "is_correct": True}],
                "weighted_score_percent": 75.0,
                "passed": True,
            },
            "best_attempt": {
                "question_results": [{"used_hint": False, "is_correct": True}],
                "weighted_score_percent": 85.0,
                "passed": True,
            },
        }

        best_attempt = _extract_best_passing_attempt(saved_state)
        latest_attempt = _extract_latest_attempt(saved_state)

        self.assertEqual(best_attempt["weighted_score_percent"], 85.0)
        self.assertEqual(latest_attempt["weighted_score_percent"], 75.0)
        self.assertEqual(_extract_best_passing_score(saved_state, 0.0), 85.0)

    def test_saved_states_are_isolated_per_user_snapshot(self):
        user_one_state = {
            "best_attempt": {
                "weighted_score_percent": 90.0,
                "passed": True,
                "question_results": [{"used_hint": False, "is_correct": True}],
            }
        }
        user_two_state = {
            "best_attempt": {
                "weighted_score_percent": 75.0,
                "passed": True,
                "question_results": [{"used_hint": True, "is_correct": True}],
            }
        }

        self.assertEqual(_extract_best_passing_score(user_one_state, 0.0), 90.0)
        self.assertEqual(_extract_best_passing_score(user_two_state, 0.0), 75.0)
        self.assertEqual(_compute_hint_breakdown(user_one_state["best_attempt"]), (1, 1, 0, 0, 1))
        self.assertEqual(_compute_hint_breakdown(user_two_state["best_attempt"]), (0, 0, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()
