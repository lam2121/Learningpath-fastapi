"""Roadmap selection (spec §2.C) — pure backend, zero AI.

Ports the v2.1 topic-selection algorithm exactly. The role's topics are scored
by weak-skill relevance, the top 8 are taken, then both floors are repaired
jointly by swapping in pool topics:

  1. Representation Floor — every skill keeps >= MIN_TOPICS_PER_SKILL[track]
     topics in the roadmap, so the Final Test (which tests all 4 skills) always
     has taught content.
  2. Adaptive Lesson Floor — every skill keeps >= MIN_LESSONS_PER_SKILL[track]
     lessons in the roadmap, counted on the ASSIGNED lessons for the track
     (not the full 6-shell set).

Fairness fix (docs/07 §12.1.2): the role's topics are shuffled with a per-user
seed BEFORE scoring, so ties break per user instead of by B-1 pool insertion
order. The same (user_id, role_id) pair always produces the identical roadmap
(reproducible, incl. on a forced re-select); across the population every topic
gets a fair chance in every weak-skill combination.

The topics/shells are duck-typed: topics only need `.id`, `.primary_skill`,
`.seed_tier`; shells only need `.topic_id`, `.difficulty_tier`,
`.primary_skill`. That keeps the module DB-free and trivially testable.
"""

import random
from collections.abc import Iterable

SKILLS = ["D_doc", "C_comm", "T_trouble", "G_custom"]
MIN_LESSONS_PER_SKILL = {"basic": 4, "intermediate": 3, "advanced": 2}
MIN_TOPICS_PER_SKILL = {"basic": 1, "intermediate": 1, "advanced": 1}
# Advanced users take exactly 2 (Advanced) lessons per topic, both tagged with
# the topic's primary skill, so 1 topic fully satisfies their 2-lesson floor.
TRACK_TIERS = {
    "basic": {"basic", "intermediate", "advanced"},
    "intermediate": {"intermediate", "advanced"},
    "advanced": {"advanced"},
}
NUM_ROADMAP_TOPICS = 8


def assigned_lessons(selected_topics, lesson_shells, track: str) -> dict[str, int]:
    """Lessons actually assigned for this track, counted per skill (lesson-tag level)."""
    topic_ids = {t.id for t in selected_topics}
    counts = {s: 0 for s in SKILLS}
    for shell in lesson_shells:
        if shell.topic_id in topic_ids and shell.difficulty_tier in TRACK_TIERS[track]:
            counts[shell.primary_skill] += 1
    return counts


def select_roadmap(
    *,
    user_id: int,
    role_id: int,
    weak_skills: list[str],
    role_topics: Iterable,
    lesson_shells: Iterable,
    track: str,
) -> list:
    """
    Select 8 topics from the role's 20 topics, prioritizing the user's weak
    skills, while enforcing both floors. Returns the selected topics sorted by
    `seed_tier` (Tier 1 is taught before Tier 2).

    `user_id`/`role_id` feed the seeded shuffle; `weak_skills` are the tags
    whose score < 0.5 (absolute, spec §3 / walkthrough Q15).
    """
    role_topics = list(role_topics)

    # Step 0 — seeded shuffle (docs/07 §12.1.2): deterministic per user so
    # tie-breaks are fair across the population instead of B-1 pool order.
    rng = random.Random(f"{user_id}:{role_id}")
    rng.shuffle(role_topics)

    # Step 1 — score topics by weakness relevance + base relevance
    scored = [
        (topic, 2 if topic.primary_skill in weak_skills else 1) for topic in role_topics
    ]

    # Step 2 — take top 8
    ordered = sorted(scored, key=lambda x: x[1], reverse=True)
    selected = [t for t, _ in ordered[:NUM_ROADMAP_TOPICS]]

    def gain(topic, skill):
        """Contribution of `topic` to `skill` — 1 topic (topic floor)."""
        return 1 if topic.primary_skill == skill else 0

    def lesson_gain(topic, skill):
        return sum(
            1
            for shell in lesson_shells
            if shell.topic_id == topic.id
            and shell.difficulty_tier in TRACK_TIERS[track]
            and shell.primary_skill == skill
        )

    def repair_floors(selected_topics):
        """Bounded best-effort repair that enforces BOTH floors in one pass:
        the representation floor (>= MIN_TOPICS_PER_SKILL topics per skill) and
        the adaptive lesson floor (>= MIN_LESSONS_PER_SKILL lessons per skill).

        Each iteration swaps in a pool topic that helps the most deficient
        skill, dropping a selected topic that helps it the least (preferring to
        keep weak-skill topics). A swap is only accepted when it strictly
        reduces total floor deficiency, so the loop converges instead of
        ping-ponging between two deficits."""

        def topic_counts(ts):
            return {s: sum(1 for t in ts if t.primary_skill == s) for s in SKILLS}

        def lesson_counts(ts):
            return assigned_lessons(ts, lesson_shells, track)

        def deficiency(tc, lc):
            return sum(
                max(0, MIN_TOPICS_PER_SKILL[track] - tc[s])
                + max(0, MIN_LESSONS_PER_SKILL[track] - lc[s])
                for s in SKILLS
            )

        selected_ids = {t.id for t in selected_topics}
        for _ in range(len(role_topics) * 4):
            tc, lc = topic_counts(selected_topics), lesson_counts(selected_topics)
            deficit = next(
                (
                    s
                    for s in SKILLS
                    if tc[s] < MIN_TOPICS_PER_SKILL[track]
                    or lc[s] < MIN_LESSONS_PER_SKILL[track]
                ),
                None,
            )
            if deficit is None:
                break
            topic_deficient = tc[deficit] < MIN_TOPICS_PER_SKILL[track]
            lesson_deficient = lc[deficit] < MIN_LESSONS_PER_SKILL[track]
            pool = [
                t
                for t in role_topics
                if t.id not in selected_ids
                and (
                    (topic_deficient and gain(t, deficit))
                    or (lesson_deficient and lesson_gain(t, deficit))
                )
            ]
            if not pool:
                break  # unsatisfiable — remediation (§4.2) covers the remainder
            best = max(
                pool,
                key=lambda t: (
                    lesson_gain(t, deficit) if lesson_deficient else gain(t, deficit),
                    gain(t, deficit),
                    rng.random(),
                ),
            )
            current = deficiency(tc, lc)
            removable = []
            for t in selected_topics:
                nt = {s: tc[s] - gain(t, s) + gain(best, s) for s in SKILLS}
                nl = {
                    s: lc[s] - lesson_gain(t, s) + lesson_gain(best, s) for s in SKILLS
                }
                if deficiency(nt, nl) < current:
                    removable.append(t)
            if not removable:
                break  # no swap improves the deficit — remediation (§4.2)
            removed = min(
                removable,
                key=lambda t: (
                    t.primary_skill in weak_skills,
                    lesson_gain(t, deficit) + gain(t, deficit),
                    rng.random(),
                ),
            )
            selected_topics.remove(removed)
            selected_ids.remove(removed.id)
            selected_topics.append(best)
            selected_ids.add(best.id)
        return selected_topics

    # Step 3 — enforce both floors (representation + adaptive lesson) jointly
    selected = repair_floors(selected)

    # Step 4 — sort chronologically so Tier 1 is taught before Tier 2
    selected.sort(key=lambda t: t.seed_tier)
    return selected
