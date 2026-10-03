"""UX-D4b pure rules: the points fallback and the jar pick."""
import random
from uuid import uuid4

import pytest

from app.models.mystery import MysterySurprise
from app.services.mystery_service import JAR_MAX, TITLE_MAX, pick_surprise, points_for


def surprise(title="x"):
    return MysterySurprise(id=uuid4(), family_id=uuid4(), title=title)


def test_constants():
    assert (JAR_MAX, TITLE_MAX) == (20, 60)


class TestPoints:
    @pytest.mark.parametrize("maximum,lo", [(20, 5), (10, 2), (4, 1), (3, 1), (1, 1), (500, 125)])
    def test_between_a_quarter_and_the_maximum(self, maximum, lo):
        rng = random.Random(7)
        seen = {points_for(maximum, rng) for _ in range(400)}
        assert min(seen) >= lo and max(seen) <= maximum
        if maximum - lo < 50:                      # small ranges: both ends must come up
            assert lo in seen and maximum in seen

    def test_never_zero(self):
        assert points_for(1, random.Random(1)) == 1
        assert points_for(0, random.Random(1)) == 1


class TestPick:
    def test_nothing_from_an_empty_jar(self):
        assert pick_surprise([], None, random.Random(1)) is None

    def test_never_the_last_one_when_the_jar_has_two_or_more(self):
        a, b, c = surprise("a"), surprise("b"), surprise("c")
        rng = random.Random(3)
        for _ in range(100):
            assert pick_surprise([a, b, c], a.id, rng) is not a

    def test_the_only_one_is_allowed_again(self):
        only = surprise("only")
        assert pick_surprise([only], only.id, random.Random(1)) is only

    def test_every_eligible_surprise_can_come_up(self):
        items = [surprise(str(i)) for i in range(4)]
        rng = random.Random(11)
        picked = {pick_surprise(items, items[0].id, rng).id for _ in range(300)}
        assert picked == {s.id for s in items[1:]}
