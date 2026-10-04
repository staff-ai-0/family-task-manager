"""UX-E3: every starter-pack chore carries priority tags the setup wizard filters on."""
from app.data.starter_packs import CHORE_TAGS, PRIORITY_TAGS, STARTER_PACKS


def test_priority_tags_are_the_six_wizard_chips():
    assert PRIORITY_TAGS == ("routine", "school", "home", "kitchen", "pets", "self_care")


def test_every_chore_has_at_least_one_known_tag():
    for band, pack in STARTER_PACKS.items():
        for chore in pack["chores"]:
            tags = chore.get("tags")
            assert isinstance(tags, list) and tags, f"{chore['id']} has no tags"
            assert set(tags) <= set(PRIORITY_TAGS), f"{chore['id']} unknown tag {tags}"


def test_chore_tags_map_matches_the_catalog_exactly():
    ids = {c["id"] for p in STARTER_PACKS.values() for c in p["chores"]}
    assert set(CHORE_TAGS) == ids


def test_every_priority_is_reachable_in_every_age_band():
    # The pack path filters a kid's band by the family's priorities; a tag no
    # band can answer would always fall back to the whole pack.
    for band in ("3-5", "6-8", "9-12", "13+"):
        covered = {t for c in STARTER_PACKS[band]["chores"] for t in c["tags"]}
        assert covered == set(PRIORITY_TAGS), f"{band} misses {set(PRIORITY_TAGS) - covered}"
