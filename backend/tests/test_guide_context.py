"""Deterministic user-guide grounding for support mode (guide_context)."""

from app.services import guide_context
from app.services.guide_context import (
    CHAR_BUDGET,
    GuideDoc,
    GuideSection,
    build_support_context,
    load_guide,
    parse_guide,
    select_sections,
)


SAMPLE = """# Guide

intro text before any section

## Crear Cuenta

Pasos para crear una cuenta bancaria en el presupuesto.

## Tienda de Premios

Como canjear puntos por premios en la tienda.

## Importar CSV

Sube transacciones desde un archivo CSV del banco.
"""


class TestParse:
    def test_sections_split_on_h2(self):
        doc = parse_guide(SAMPLE, "es")
        assert doc.toc == ("Crear Cuenta", "Tienda de Premios", "Importar CSV")
        assert "cuenta bancaria" in doc.sections[0].body


class TestSelect:
    def test_keyword_match_is_deterministic(self):
        doc = parse_guide(SAMPLE, "es")
        # "importar" hits the title (x3) and "transacciones"/"archivo" hit the
        # body, so this section wins outright — a query that only tied on a
        # single body hit would be decided by guide order, not by relevance.
        query = "como importar transacciones de un archivo CSV?"
        first = select_sections(doc, query)
        second = select_sections(doc, query)
        assert first == second
        assert first[0].title == "Importar CSV"

    def test_accent_and_case_insensitive(self):
        doc = parse_guide(SAMPLE, "es")
        picked = select_sections(doc, "¿Cómo canjeo PREMIOS?")
        assert any(s.title == "Tienda de Premios" for s in picked)

    def test_zero_match_returns_empty(self):
        doc = parse_guide(SAMPLE, "es")
        assert select_sections(doc, "zzzz qqqq wwww") == []

    def test_char_budget_respected(self):
        big = GuideDoc(
            lang="es",
            sections=tuple(
                GuideSection(title=f"tema {i}", body="tema " + ("x" * 9000))
                for i in range(10)
            ),
        )
        picked = select_sections(big, "tema", char_budget=20_000)
        assert 0 < len(picked) <= 2  # each section is ~9k chars


class TestRealGuides:
    def test_loads_both_languages(self):
        guide_context.reset_cache()
        es = load_guide("es")
        en = load_guide("en")
        assert len(es.sections) > 30
        assert len(en.sections) > 30
        assert es.sections != en.sections

    def test_block_contains_toc_and_stays_in_budget(self):
        block = build_support_context(
            "¿Cómo importo transacciones desde un archivo CSV?", lang="es"
        )
        assert "TABLE OF CONTENTS" in block
        assert "Importar CSV" in block
        # TOC chars are deducted from the section budget, so the whole block
        # is bounded by CHAR_BUDGET plus the small fixed framing text.
        assert len(block) <= CHAR_BUDGET + 500

    def test_unknown_lang_falls_back_to_es(self):
        block = build_support_context("premios", lang="fr")
        assert "Tienda de Premios" in block
