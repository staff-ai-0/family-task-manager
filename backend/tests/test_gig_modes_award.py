"""Award points respects gig_mode (W4.1b)."""

import pytest

from app.models.task_template import TaskTemplate, GigMode


class TestAwardPointsPerCompleter:
    def test_claim_full_amount(self):
        t = TaskTemplate(points=20, effort_level=1, gig_mode="claim", collaboration_min_count=2)
        assert t.effective_points == 20
        assert t.award_points_per_completer == 20

    def test_competition_full_amount(self):
        t = TaskTemplate(points=20, effort_level=1, gig_mode="competition", collaboration_min_count=2)
        assert t.award_points_per_completer == 20

    def test_rotation_full_amount(self):
        t = TaskTemplate(points=20, effort_level=1, gig_mode="rotation", collaboration_min_count=2)
        assert t.award_points_per_completer == 20

    def test_collaboration_split_by_min_count(self):
        t = TaskTemplate(points=20, effort_level=1, gig_mode="collaboration", collaboration_min_count=2)
        assert t.award_points_per_completer == 10

    def test_collaboration_split_by_three(self):
        t = TaskTemplate(points=30, effort_level=1, gig_mode="collaboration", collaboration_min_count=3)
        assert t.award_points_per_completer == 10

    def test_collaboration_with_effort_multiplier(self):
        # 30 base × 1.5 effort = 45 effective, split by 3 = 15
        t = TaskTemplate(points=30, effort_level=2, gig_mode="collaboration", collaboration_min_count=3)
        assert t.effective_points == 45
        assert t.award_points_per_completer == 15


class TestCollaborationDistribution:
    """L15/M11: collaboration splits must conserve the pot — the remainder is
    distributed to the first completers, not floored away."""

    def test_distribute_points_conserves_pot(self):
        assert TaskTemplate.distribute_points(10, 3) == [4, 3, 3]
        assert sum(TaskTemplate.distribute_points(10, 3)) == 10
        assert TaskTemplate.distribute_points(7, 3) == [3, 2, 2]
        assert TaskTemplate.distribute_points(9, 3) == [3, 3, 3]
        assert TaskTemplate.distribute_points(20, 2) == [10, 10]
        # property is fully general
        for pot in (0, 1, 5, 13, 100):
            for n in (1, 2, 3, 4, 7):
                shares = TaskTemplate.distribute_points(pot, n)
                assert sum(shares) == pot
                assert max(shares) - min(shares) <= 1

    def test_collaboration_share_distributes_remainder(self):
        t = TaskTemplate(
            points=10, effort_level=1, gig_mode="collaboration",
            collaboration_min_count=3,
        )
        shares = [t.collaboration_share(i) for i in range(3)]
        assert shares == [4, 3, 3]
        assert sum(shares) == 10  # no points lost (old floor split gave 9)

    def test_non_collaboration_share_is_full_effective(self):
        t = TaskTemplate(
            points=10, effort_level=1, gig_mode="competition",
            collaboration_min_count=3,
        )
        assert t.collaboration_share(0) == 10
