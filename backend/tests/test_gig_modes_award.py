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
