"""Static pet cosmetics catalog (pet quest/evolution loop, 2026-07-09).

Cosmetics are the long-horizon POINTS sink that fights novelty decay: hats,
colors and accessories that a kid buys with points (privileges currency —
never cash) and unlocks progressively as the pet evolves. Static data on
purpose (no per-family authoring) — the DB only tracks OWNED/EQUIPPED per pet
(app/models/pet_cosmetic.py).

Each entry:
- ``slot``      one of COSMETIC_SLOTS. Only one equipped cosmetic per slot.
- ``price``     cost in POINTS (>0). Spent via the existing points-sink pattern.
- ``min_stage`` evolution_stage a pet must have REACHED to buy it (0..4).
- ``name``      bilingual display name ({"es":…, "en":…}).
- ``icon``      an emoji for the UI.
"""

from app.models.kid_pet import EVOLUTION_STAGE_NAMES

# Equip slots — at most one equipped cosmetic per slot per pet.
COSMETIC_SLOTS = ["hat", "color", "accessory"]


COSMETICS: dict[str, dict] = {
    # ── Stage 1 (baby) — cheap early unlocks ────────────────────────
    "hat_cap": {
        "slot": "hat",
        "price": 20,
        "min_stage": 1,
        "icon": "🧢",
        "name": {"es": "Gorra", "en": "Cap"},
    },
    "color_blue": {
        "slot": "color",
        "price": 40,
        "min_stage": 1,
        "icon": "🔵",
        "name": {"es": "Color azul", "en": "Blue coat"},
    },
    "acc_scarf": {
        "slot": "accessory",
        "price": 30,
        "min_stage": 1,
        "icon": "🧣",
        "name": {"es": "Bufanda", "en": "Scarf"},
    },
    # ── Stage 2 (kid) ───────────────────────────────────────────────
    "acc_glasses": {
        "slot": "accessory",
        "price": 60,
        "min_stage": 2,
        "icon": "🕶️",
        "name": {"es": "Lentes", "en": "Sunglasses"},
    },
    "hat_bow": {
        "slot": "hat",
        "price": 70,
        "min_stage": 2,
        "icon": "🎀",
        "name": {"es": "Moño", "en": "Bow"},
    },
    # ── Stage 3 (teen) ──────────────────────────────────────────────
    "hat_crown": {
        "slot": "hat",
        "price": 120,
        "min_stage": 3,
        "icon": "👑",
        "name": {"es": "Corona", "en": "Crown"},
    },
    "color_galaxy": {
        "slot": "color",
        "price": 150,
        "min_stage": 3,
        "icon": "🌌",
        "name": {"es": "Color galaxia", "en": "Galaxy coat"},
    },
    # ── Stage 4 (adult) — prestige, expensive long-horizon goals ────
    "acc_wings": {
        "slot": "accessory",
        "price": 180,
        "min_stage": 4,
        "icon": "🪽",
        "name": {"es": "Alas", "en": "Wings"},
    },
    "hat_halo": {
        "slot": "hat",
        "price": 200,
        "min_stage": 4,
        "icon": "😇",
        "name": {"es": "Aureola", "en": "Halo"},
    },
}


def cosmetic_or_none(key: str) -> dict | None:
    return COSMETICS.get(key)


def catalog_public() -> list[dict]:
    """Catalog as a stable, ordered list for the API (adds ``key`` +
    ``min_stage_name``)."""
    out = []
    for key, c in COSMETICS.items():
        out.append(
            {
                "key": key,
                "slot": c["slot"],
                "price": c["price"],
                "min_stage": c["min_stage"],
                "min_stage_name": EVOLUTION_STAGE_NAMES[c["min_stage"]],
                "icon": c["icon"],
                "name": c["name"],
            }
        )
    return out
