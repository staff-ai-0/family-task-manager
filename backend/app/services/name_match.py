"""Member-name matching shared by the chart scanner (UX-E1) and the guided
setup wizard (UX-E3): a name typed by a parent or read by the model → the
family member it means, never a guess."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Member:
    id: UUID
    name: str
    role: str


def fold(text: str) -> str:
    """Lower-case, accents stripped, whitespace collapsed — the comparison form."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def match_members(names: list[str], members: list[Member]) -> tuple[list[UUID], list[str]]:
    """Member ids for the names given, in order, plus the names that matched
    nobody. A name matches a member's full name or first name; an ambiguous
    first name (two members share it) matches nobody — never assign a chore
    to the wrong kid."""
    by_full: dict[str, UUID] = {fold(m.name): m.id for m in members}
    first_counts: dict[str, int] = {}
    for m in members:
        first = fold(m.name).split(" ")[0] if fold(m.name) else ""
        first_counts[first] = first_counts.get(first, 0) + 1
    by_first: dict[str, UUID] = {
        fold(m.name).split(" ")[0]: m.id for m in members if first_counts.get(fold(m.name).split(" ")[0]) == 1
    }
    ids: list[UUID] = []
    missing: list[str] = []
    for raw in names or []:
        name = (raw or "").strip() if isinstance(raw, str) else ""
        if not name:
            continue
        key = fold(name)
        hit = by_full.get(key) or by_first.get(key)
        if hit is None:
            if name not in missing:
                missing.append(name)
        elif hit not in ids:
            ids.append(hit)
    return ids, missing
