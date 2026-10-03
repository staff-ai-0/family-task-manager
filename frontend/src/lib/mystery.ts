/** UX-D4b mystery box — the only place its copy lives. Pure helpers: the
 *  server view → the card's state, and the exact strings the card writes. */

export type Lang = "es" | "en";

export const MYSTERY_COPY = {
    heading: { es: "Caja sorpresa", en: "Mystery box" },
    closed: { es: "🎁 ¡Una caja sorpresa! Toca para abrir", en: "🎁 A mystery box! Tap to open" },
    opening: { es: "Abriendo…", en: "Opening…" },
    off: { es: "Las cajas están apagadas por ahora.", en: "Boxes are off right now." },
    failed: { es: "No se pudo abrir. Intenta de nuevo.", en: "Could not open. Try again." },
} as const;

export type Revealed = { kind: "surprise" | "points"; title: string; emoji: string; points: number };
export type MysteryView = { closedCount: number; closedId: string | null; revealed: Revealed | null };

/** An opened box from the API, or null for anything else. */
export function revealedFrom(box: unknown): Revealed | null {
    const b = box as Record<string, unknown> | null;
    if (!b || b.opened !== true || (b.kind !== "surprise" && b.kind !== "points")) return null;
    return {
        kind: b.kind,
        title: typeof b.surprise_title === "string" ? b.surprise_title : "",
        emoji: typeof b.surprise_emoji === "string" ? b.surprise_emoji : "",
        points: typeof b.points === "number" ? b.points : 0,
    };
}

/** "today" / "yesterday" / "N days ago" for a YYYY-MM-DD day, in the parent's
 *  language; "" for anything unparsable. Compared on UTC calendar days. */
export function dayLabel(day: string, lang: Lang, now: Date = new Date()): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
    if (!m) return "";
    const then = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const days = Math.round((today - then) / 86_400_000);
    if (days <= 0) return lang === "es" ? "hoy" : "today";
    if (days === 1) return lang === "es" ? "ayer" : "yesterday";
    return lang === "es" ? `hace ${days} días` : `${days} days ago`;
}

/** null unless the boxes apply to this user and are on for the family. An
 *  enabled family with nothing to show still gets a view: the card renders
 *  hidden and wakes up when the deck empties. */
export function mysteryView(resp: unknown): MysteryView | null {
    const r = resp as Record<string, unknown> | null;
    if (!r || r.applies !== true || r.enabled !== true) return null;
    const unopened = Array.isArray(r.unopened) ? (r.unopened as Array<Record<string, unknown>>) : [];
    const first = unopened[0];
    return {
        closedCount: unopened.length,
        closedId: first && typeof first.id === "string" ? first.id : null,
        revealed: revealedFrom(r.opened_today),
    };
}

export function mysteryDomUpdate(view: MysteryView, lang: Lang, starMode: boolean) {
    // Both can show at once: today's reveal stays on screen while the next
    // box waits underneath — a reveal must never vanish behind a repaint.
    const showClosed = view.closedCount > 0;
    const showRevealed = view.revealed !== null;
    let revealedText = "";
    if (view.revealed) {
        if (view.revealed.kind === "points") {
            revealedText = starMode ? `+${view.revealed.points} ⭐` : lang === "es" ? `+${view.revealed.points} puntos` : `+${view.revealed.points} points`;
        } else {
            const what = [view.revealed.title, view.revealed.emoji].filter(Boolean).join(" ");
            revealedText = lang === "es" ? `Te tocó: ${what} — ¡pídesela a tus papás!` : `You got: ${what} — ask your parents!`;
        }
    }
    return {
        showClosed,
        closedLabel: showClosed ? `${MYSTERY_COPY.closed[lang]}${view.closedCount > 1 ? ` ×${view.closedCount}` : ""}` : "",
        showRevealed,
        revealedText,
    };
}
