"""The member-name matcher shared by the chart scanner (E1) and the setup wizard (E3)."""
from uuid import uuid4

from app.services.name_match import Member, fold, match_members


def test_fold_is_case_accent_and_space_insensitive():
    assert fold("  Sofía   MARTÍNEZ ") == "sofia martinez"


def test_match_by_first_or_full_name_and_report_unknown():
    d, s = uuid4(), uuid4()
    members = [Member(d, "Diego Martínez", "teen"), Member(s, "Sofía Martínez", "child")]
    ids, missing = match_members(["sofia", "Pepe"], members)
    assert ids == [s] and missing == ["Pepe"]


def test_chart_scanner_still_exposes_the_same_names():
    from app.services import chart_scanner_service as cs
    assert cs.fold is fold and cs.match_members is match_members and cs.Member is Member
