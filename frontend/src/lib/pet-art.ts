/**
 * Shared pet-art constants for the quest/evolution loop UI.
 *
 * Mirrors the backend evolution ladder (app/models/kid_pet.py) so the frontend
 * can render stage art, bilingual stage labels, and XP-to-next-stage progress
 * without a round-trip. Kept dependency-free + emoji/CSS only (no images) so it
 * imports cleanly into both Astro frontmatter and client-side <script> bundles.
 */

export type Lang = "en" | "es";

export const SPECIES_EMOJI: Record<string, string> = {
    cat: "🐱",
    dog: "🐶",
    dragon: "🐲",
    fox: "🦊",
    owl: "🦉",
    bunny: "🐰",
};

/** Bilingual stage labels — indexed by evolution_stage (0..4). */
export const STAGE_LABELS: { es: string; en: string }[] = [
    { es: "huevo", en: "egg" },
    { es: "bebé", en: "baby" },
    { es: "pequeño", en: "kid" },
    { es: "joven", en: "teen" },
    { es: "adulto", en: "adult" },
];

/** Cumulative xp required to REACH each stage (mirrors EVOLUTION_XP_THRESHOLDS). */
export const STAGE_XP_THRESHOLDS = [0, 100, 400, 1000, 2000];
export const MAX_STAGE = STAGE_LABELS.length - 1;

/** Colour tint per "color"-slot cosmetic key — rendered as the pet's aura. */
export const COLOR_AURA: Record<string, string> = {
    color_blue: "radial-gradient(circle, rgba(79,184,230,0.55), rgba(79,184,230,0) 70%)",
    color_galaxy:
        "radial-gradient(circle, rgba(167,139,250,0.6), rgba(99,102,241,0.15) 60%, rgba(0,0,0,0) 75%)",
};

/** The base emoji for a pet at a given species + stage (egg before hatching). */
export function petEmoji(species: string, stage: number): string {
    if ((stage ?? 0) <= 0) return "🥚";
    return SPECIES_EMOJI[species] ?? "🐾";
}

/** A mood face override for the pet's current status_label, else its species art. */
export function petFace(status: string, species: string, stage: number): string {
    if ((stage ?? 0) <= 0) return "🥚";
    if (status === "starving") return "😫";
    if (status === "sad") return "😞";
    if (status === "happy") return "🤩";
    return SPECIES_EMOJI[species] ?? "🐾";
}

export function stageLabel(stage: number, lang: Lang): string {
    const s = STAGE_LABELS[Math.min(Math.max(stage ?? 0, 0), MAX_STAGE)];
    return lang === "es" ? s.es : s.en;
}

/**
 * Progress (0..100) toward the NEXT evolution stage given cumulative xp.
 * Returns 100 at the final (adult) stage.
 */
export function stageProgressPct(xp: number, stage: number): number {
    if ((stage ?? 0) >= MAX_STAGE) return 100;
    const floor = STAGE_XP_THRESHOLDS[stage];
    const ceil = STAGE_XP_THRESHOLDS[stage + 1];
    if (ceil <= floor) return 100;
    return Math.max(0, Math.min(100, Math.round(((xp - floor) / (ceil - floor)) * 100)));
}
