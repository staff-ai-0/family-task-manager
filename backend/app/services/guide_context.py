"""Support-mode grounding: TOC + keyword-matched user-guide sections.

The user guides (docs/USER_GUIDE_{ES,EN}.md, ~27-30k tokens each) are far too
big to inject whole on every turn. This module parses each guide once into
'## '-delimited sections, then per message emits the table of contents plus
the best keyword-matched sections under a hard character budget (~6k tokens).
Deterministic on purpose — no vector store, no LLM: same inputs, same block.

Consumed by jarvis_service in support mode, where this block REPLACES the
family-state context block (support answers app-usage questions; it never
sees family data).
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# <=6k tokens ~= 24k chars at ~4 chars/token — the design's injection budget.
CHAR_BUDGET = 24_000
# Words shorter than this are matching noise ("el", "the", "de", "las", ...).
MIN_TERM_LEN = 4

# docs/ lives beside backend/ in the repo; inside the container the backend
# Dockerfile copies it to /app/docs (WORKDIR /app == the backend tree).
# parents[2] is the backend root (container: /app), parents[3] the repo root
# (bare-metal dev / CI checkout).
_CANDIDATE_DIRS = (
    Path(__file__).resolve().parents[2] / "docs",
    Path(__file__).resolve().parents[3] / "docs",
)

GUIDE_FILENAMES = {"es": "USER_GUIDE_ES.md", "en": "USER_GUIDE_EN.md"}


@dataclass(frozen=True)
class GuideSection:
    title: str
    body: str


@dataclass(frozen=True)
class GuideDoc:
    lang: str
    sections: tuple[GuideSection, ...]

    @property
    def toc(self) -> tuple[str, ...]:
        return tuple(s.title for s in self.sections)


_cache: dict[str, GuideDoc] = {}


def reset_cache() -> None:
    """Test hook — drop parsed guides (e.g. after monkeypatching paths)."""
    _cache.clear()


def _docs_dir() -> Path:
    for d in _CANDIDATE_DIRS:
        if d.is_dir():
            return d
    raise FileNotFoundError(
        f"user-guide docs dir not found in {[str(d) for d in _CANDIDATE_DIRS]}"
        " — the backend image must COPY docs/ (see backend/Dockerfile)"
    )


def parse_guide(text: str, lang: str) -> GuideDoc:
    """Split markdown into '## '-delimited sections. Preamble before the
    first '## ' is dropped — we emit our own TOC from the parsed titles."""
    sections: list[GuideSection] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                sections.append(
                    GuideSection(title=title, body="\n".join(body).strip())
                )
            title = line[3:].strip()
            body = []
        elif title is not None:
            body.append(line)
    if title is not None:
        sections.append(GuideSection(title=title, body="\n".join(body).strip()))
    return GuideDoc(lang=lang, sections=tuple(sections))


def load_guide(lang: str) -> GuideDoc:
    lang = lang if lang in GUIDE_FILENAMES else "es"
    if lang not in _cache:
        path = _docs_dir() / GUIDE_FILENAMES[lang]
        _cache[lang] = parse_guide(path.read_text(encoding="utf-8"), lang)
    return _cache[lang]


def _normalize(text: str) -> str:
    """Lowercase + strip accents so 'Configuración' matches 'configuracion'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _terms(query: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", _normalize(query))
        if len(t) >= MIN_TERM_LEN
    ]


def select_sections(
    doc: GuideDoc, query: str, char_budget: int = CHAR_BUDGET
) -> list[GuideSection]:
    """Best keyword-matched sections, deterministic: score desc, then guide
    order. Title hits weigh 3x a body occurrence. Zero-score sections are
    never selected; over-budget sections are skipped (smaller later matches
    may still fit)."""
    terms = _terms(query)
    scored: list[tuple[int, int, GuideSection]] = []
    for idx, sec in enumerate(doc.sections):
        title_n = _normalize(sec.title)
        body_n = _normalize(sec.body)
        score = 0
        for t in terms:
            if t in title_n:
                score += 3
            score += body_n.count(t)
        if score > 0:
            scored.append((score, idx, sec))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked: list[GuideSection] = []
    used = 0
    for _score, _idx, sec in scored:
        size = len(sec.title) + len(sec.body) + 8
        if used + size > char_budget:
            continue
        picked.append(sec)
        used += size
    return picked


def build_support_context(
    message: str, last_user_turn: str = "", lang: str = "es"
) -> str:
    """The support-mode system-prompt grounding block: guide TOC + sections
    relevant to the current message (+ the previous user turn, so follow-ups
    like 'and how do I delete it?' keep their subject)."""
    doc = load_guide(lang)
    toc_block = "\n".join(f"- {t}" for t in doc.toc)
    sections = select_sections(
        doc,
        f"{message}\n{last_user_turn}",
        char_budget=max(CHAR_BUDGET - len(toc_block), 0),
    )
    if sections:
        sections_block = "\n\n".join(f"## {s.title}\n{s.body}" for s in sections)
    else:
        sections_block = (
            "(no matching guide sections — if the table of contents does not "
            "cover the question either, say you don't know and point the "
            "user to soporte@agent-ia.mx)"
        )
    return (
        "USER GUIDE (Family Task Manager) — TABLE OF CONTENTS:\n"
        f"{toc_block}\n\n"
        "RELEVANT GUIDE SECTIONS:\n"
        f"{sections_block}"
    )
