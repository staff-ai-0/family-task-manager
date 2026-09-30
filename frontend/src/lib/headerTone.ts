/**
 * Section header colors (UX-B3) — the ONE place a header's fill is decided.
 * Color means the section: sky = doing things, mint = money, sun = earning &
 * winning, coral = treats/care/home, cream = talk & settings. Every tone is a
 * flat brand fill with an ink outline and ink text (≥ 6.3:1 on every tone).
 * Used by PageHeader, ChatShell and the custom hero headers.
 */
export type HeaderTone = "sky" | "mint" | "sun" | "coral" | "cream";

export const HEADER_TONES: readonly HeaderTone[] = ["sky", "mint", "sun", "coral", "cream"];

const FILL: Record<HeaderTone, string> = {
    sky: "bg-brand-sky",
    mint: "bg-brand-mint",
    sun: "bg-brand-sun",
    coral: "bg-brand-coral",
    cream: "bg-brand-cream",
};

/** Fill + ink bottom outline + ink text for a section header. */
export function headerToneClass(tone: HeaderTone): string {
    return `${FILL[tone] ?? FILL.cream} border-b-4 border-brand-ink text-brand-ink`;
}
