import unittest

from app.core.lesson_duration import (
    MAX_MINUTES,
    MIN_MINUTES,
    calculate_quiz_minutes,
    calculate_theory_minutes,
    estimate_lesson_duration,
)


class LessonDurationTest(unittest.TestCase):
    def test_estimate_matches_reference_style_payload(self):
        theory = [
            [
                "scenario",
                "You are joining a project kickoff meeting for a new mobile app release.",
                "The client wants clear next steps and risk visibility.",
                "Focus on concise professional updates.",
            ],
            [
                "vocab",
                "scope|pham vi|project scope|what is included#timeline|lich trinh|delivery timeline|key dates",
                "Use these terms when aligning expectations.",
                "Keep the wording consistent across meetings.",
            ],
            [
                "phrases",
                "Can we confirm the final scope?|We need to flag the delivery risk.",
                "Repeat the phrases until they feel natural.",
                "",
            ],
            [
                "reading",
                "The release plan includes discovery, design, testing, and launch support.",
                "Each phase has an owner and a review checkpoint.",
                "Escalate blockers early to avoid schedule drift.",
            ],
            [
                "dialogue",
                "PM: Can we keep the current scope?||Lead: Yes, if we move analytics to phase two.",
                "Client: Please document that decision.",
                "",
            ],
            [
                "process",
                "Review scope|Confirm owners|Publish timeline|Track risks",
                "Follow the order when starting a new release.",
                "",
            ],
            [
                "dos_donts",
                "Do confirm dependencies#Don't promise dates without engineering input",
                "Use careful language with the client.",
                "",
            ],
            [
                "wrapup",
                "Summarize the scope, timeline, and next action in one message.",
                "",
                "",
            ],
        ]
        quiz = {
            "ordering": [["q", "a|b|c|d", "a", "exp"]] * 10,
            "fill_blank": [["q", "a|b|c|d", "a", "exp"]] * 10,
            "multi_select": [["q", "a|b|c|d", "a", "exp"]] * 10,
        }

        theory_minutes = calculate_theory_minutes(theory)
        quiz_minutes = calculate_quiz_minutes(quiz)
        total = estimate_lesson_duration(theory, quiz)

        self.assertGreater(theory_minutes, 0)
        self.assertAlmostEqual(quiz_minutes, 15.3333333333, places=2)
        self.assertEqual(total, 17)

    def test_unknown_quiz_type_uses_default_seconds(self):
        total = calculate_quiz_minutes({"matching": [["q", "a", "b", "c"]] * 4})
        self.assertAlmostEqual(total, 100 / 60, places=4)

    def test_empty_or_malformed_payloads_are_clamped_to_minimum(self):
        self.assertEqual(estimate_lesson_duration([], {}), MIN_MINUTES)
        self.assertEqual(estimate_lesson_duration(None, None), MIN_MINUTES)

    def test_large_payload_is_clamped_to_maximum(self):
        huge_theory = [["reading", "word " * 10000, "", ""]]
        huge_quiz = {"ordering": [["q", "a", "b", "c"]] * 200}
        self.assertEqual(estimate_lesson_duration(huge_theory, huge_quiz), MAX_MINUTES)


if __name__ == "__main__":
    unittest.main()
