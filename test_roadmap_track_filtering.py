import unittest
from types import SimpleNamespace

from app.core.roadmap import lesson_is_assigned
from app.feature.onboarding.placement_test_service import get_user_roadmap
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user import User
from app.models.user_roadmap import UserRoadmap


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    def __init__(self, query_rows):
        self.query_rows = query_rows

    def query(self, model):
        return FakeQuery(self.query_rows[model])


class RoadmapTrackFilteringTest(unittest.TestCase):
    def test_lesson_is_assigned_obeys_track_tiers(self):
        self.assertTrue(lesson_is_assigned("basic", "basic"))
        self.assertTrue(lesson_is_assigned("intermediate", "advanced"))
        self.assertFalse(lesson_is_assigned("intermediate", "basic"))
        self.assertFalse(lesson_is_assigned("advanced", "intermediate"))

    def test_get_user_roadmap_filters_lessons_for_intermediate_track(self):
        user = SimpleNamespace(id=1)
        roadmap_rows = [SimpleNamespace(topic_id=10, sort_order=0, track="intermediate")]
        topics = [
            SimpleNamespace(
                id=10,
                name="API Communication",
                primary_skill="C_comm",
                seed_tier="Tier 1",
                sort_order=0,
            )
        ]
        lessons = [
            SimpleNamespace(
                id=100,
                topic_id=10,
                title="Basic lesson",
                primary_skill="C_comm",
                difficulty_tier="basic",
                estimated_minutes=11,
                is_generated=False,
                theory_content=None,
                quiz_content=None,
            ),
            SimpleNamespace(
                id=101,
                topic_id=10,
                title="Intermediate lesson",
                primary_skill="C_comm",
                difficulty_tier="intermediate",
                estimated_minutes=17,
                is_generated=False,
                theory_content=None,
                quiz_content=None,
            ),
            SimpleNamespace(
                id=102,
                topic_id=10,
                title="Advanced lesson",
                primary_skill="C_comm",
                difficulty_tier="advanced",
                estimated_minutes=23,
                is_generated=False,
                theory_content=None,
                quiz_content=None,
            ),
        ]
        db = FakeDB(
            {
                User: [user],
                UserRoadmap: roadmap_rows,
                Topic: topics,
                Lesson: lessons,
            }
        )

        response = get_user_roadmap(db, user_id=1)

        self.assertEqual(response.track, "intermediate")
        self.assertEqual(
            [lesson.difficulty_tier for lesson in response.topics[0].lessons],
            ["intermediate", "advanced"],
        )
        self.assertEqual(
            [lesson.estimated_minutes for lesson in response.topics[0].lessons],
            [17, 23],
        )
        self.assertEqual(response.topics[0].sort_order, 1)
        self.assertEqual(response.topics[0].total_estimated_minutes, 40)
        self.assertEqual(response.assigned_lessons["C_comm"], 2)
        self.assertEqual(response.total_estimated_minutes, 40)

    def test_get_user_roadmap_uses_user_specific_topic_positions(self):
        user = SimpleNamespace(id=1)
        roadmap_rows = [
            SimpleNamespace(topic_id=20, sort_order=0, track="basic"),
            SimpleNamespace(topic_id=10, sort_order=1, track="basic"),
        ]
        topics = [
            SimpleNamespace(
                id=10,
                name="Later in roadmap",
                primary_skill="D_doc",
                seed_tier="tier_1",
                sort_order=17,
            ),
            SimpleNamespace(
                id=20,
                name="First in roadmap",
                primary_skill="C_comm",
                seed_tier="tier_2",
                sort_order=4,
            ),
        ]
        lessons = [
            SimpleNamespace(
                id=100,
                topic_id=10,
                title="Lesson A",
                primary_skill="D_doc",
                difficulty_tier="basic",
                estimated_minutes=12,
                is_generated=False,
                theory_content=None,
                quiz_content=None,
            ),
            SimpleNamespace(
                id=200,
                topic_id=20,
                title="Lesson B",
                primary_skill="C_comm",
                difficulty_tier="basic",
                estimated_minutes=19,
                is_generated=False,
                theory_content=None,
                quiz_content=None,
            ),
        ]
        db = FakeDB(
            {
                User: [user],
                UserRoadmap: roadmap_rows,
                Topic: topics,
                Lesson: lessons,
            }
        )

        response = get_user_roadmap(db, user_id=1)

        self.assertEqual([topic.id for topic in response.topics], [20, 10])
        self.assertEqual([topic.sort_order for topic in response.topics], [1, 2])


if __name__ == "__main__":
    unittest.main()
