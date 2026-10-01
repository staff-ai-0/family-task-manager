"""UX-D2 pure badge rules (no DB)."""
import pytest

from app.services.badge_service import BADGES, MAX_TIER, next_target, tiers_for, visible_badges

ALL = ("chores", "streak", "perfect_week", "extra_mile", "gigs", "saver", "rewards", "cup")


class TestCatalog:
    def test_catalog_is_the_spec_table_in_order(self):
        assert [(k, b.thresholds, b.module) for k, b in BADGES.items()] == [
            ("chores", (10, 50, 200), None),
            ("streak", (7, 30, 100), None),
            ("perfect_week", (1, 4, 12), None),
            ("extra_mile", (1, 10, 50), None),
            ("gigs", (1, 10, 50), "gigs"),
            ("saver", (1, 3, 10), "gigs"),
            ("rewards", (1, 5, 20), None),
            ("cup", (1, 3, 10), None),
        ]
        assert MAX_TIER == 3

    @pytest.mark.parametrize("key", ALL)
    def test_tier_boundaries_for_every_family(self, key):
        bronze, silver, gold = BADGES[key].thresholds
        t = BADGES[key].thresholds
        assert tiers_for(0, t) == 0
        assert tiers_for(bronze - 1, t) == 0
        assert tiers_for(bronze, t) == 1
        assert tiers_for(silver - 1, t) == 1
        assert tiers_for(silver, t) == 2
        assert tiers_for(gold - 1, t) == 2
        assert tiers_for(gold, t) == 3
        assert tiers_for(gold * 10, t) == 3

    def test_negative_count_is_tier_zero(self):
        assert tiers_for(-5, (1, 3, 10)) == 0

    def test_next_target(self):
        t = (10, 50, 200)
        assert next_target(0, t) == 10
        assert next_target(1, t) == 50
        assert next_target(2, t) == 200
        assert next_target(3, t) is None


class TestVisible:
    def test_null_modules_means_every_family(self):
        assert visible_badges(None) == ALL

    def test_gigs_module_off_hides_gigs_and_saver(self):
        assert visible_badges(["chat", "pet"]) == ("chores", "streak", "perfect_week", "extra_mile", "rewards", "cup")

    def test_gigs_module_on_explicitly(self):
        assert visible_badges(["gigs"]) == ALL
