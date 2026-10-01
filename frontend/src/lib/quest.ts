/**
 * UX-D3 weekly quest view-model: the quest copy (the ONLY copy — goals and
 * progress come from the backend's quest_service.py) and the shapes the kid
 * home card and the parent hub render.
 */
import { gigTerm } from "./gigTerm";

export type Lang = "es" | "en";
type Gig = { one: string; many: string };

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

// Key order = the backend's rotation order. A key missing here is skipped.
export const QUEST_META: Record<string, { emoji: string; title: (n: number, lang: Lang, gig: Gig) => string }> = {
    on_time: {
        emoji: "⏰",
        title: (n, lang) => lang === "es"
            ? `Termina ${n} ${plural(n, "tarea", "tareas")} a tiempo`
            : `Finish ${n} ${plural(n, "chore", "chores")} on time`,
    },
    extra_mile: {
        emoji: "🚀",
        title: (n, lang) => lang === "es"
            ? `Haz ${n} ${plural(n, "tarea extra", "tareas extra")}`
            : `Do ${n} bonus ${plural(n, "task", "tasks")}`,
    },
    perfect_days: {
        emoji: "✨",
        title: (n, lang) => lang === "es"
            ? `Logra ${n} ${plural(n, "día perfecto", "días perfectos")}`
            : `Have ${n} perfect ${plural(n, "day", "days")}`,
    },
    go_getter: {
        emoji: "💼",
        title: (n, lang, gig) => lang === "es"
            ? `Logra ${n} ${plural(n, gig.one, gig.many)} ${plural(n, "aprobada", "aprobadas")}`
            : `Get ${n} ${plural(n, gig.one, gig.many)} approved`,
    },
};

export interface QuestCardView {
    emoji: string;
    title: string;
    progressLabel: string;
    barPct: number;
    daysLeftLabel: string;
    bonusLabel: string;
    /** The bonus was paid. */
    done: boolean;
}

export interface QuestCelebrateView {
    id: string;
    emoji: string;
    heading: string;
    bonusLabel: string;
}

export interface QuestView {
    /** This week's quest, or null when there is none (or its key is unknown). */
    card: QuestCardView | null;
    /** A paid quest the kid has not seen as done yet (last week's first). */
    celebrate: QuestCelebrateView | null;
}

const int = (v: unknown) => Math.max(0, Math.trunc(Number(v) || 0));

function bonusLabel(points: number, lang: Lang, starMode: boolean): string {
    if (starMode) return `+${points} ⭐`;
    return lang === "es" ? `+${points} ${plural(points, "punto", "puntos")}` : `+${points} ${plural(points, "point", "points")}`;
}

const doneHeading = (lang: Lang, lastWeek: boolean) =>
    lastWeek
        ? (lang === "es" ? "La misión de la semana pasada: ¡lograda!" : "Last week's quest: done!")
        : (lang === "es" ? "¡Misión lograda!" : "Quest done!");

export function questView(resp: any, lang: Lang, starMode = false): QuestView | null {
    if (!resp || resp.applies !== true) return null;
    const gig = gigTerm(String(resp.gig_term ?? "gig"), lang);

    let card: QuestCardView | null = null;
    const q = resp.quest;
    const meta = q ? QUEST_META[String(q.quest)] : undefined;
    if (q && meta) {
        const target = Math.max(1, int(q.target));
        const done = q.completed === true;
        const progress = done ? target : Math.min(int(q.progress), target);
        const days = Math.max(1, int(q.days_left));
        card = {
            emoji: meta.emoji,
            title: meta.title(target, lang, gig),
            progressLabel: `${progress}/${target}`,
            barPct: Math.round((progress / target) * 100),
            daysLeftLabel: days === 1
                ? (lang === "es" ? "Último día" : "Last day")
                : (lang === "es" ? `Quedan ${days} días` : `${days} days left`),
            bonusLabel: bonusLabel(int(q.bonus_points), lang, starMode),
            done,
        };
    }

    let celebrate: QuestCelebrateView | null = null;
    const c = resp.celebrate;
    const cMeta = c ? QUEST_META[String(c.quest)] : undefined;
    if (c && cMeta && c.id) {
        celebrate = {
            id: String(c.id),
            emoji: cMeta.emoji,
            heading: doneHeading(lang, c.last_week === true),
            bonusLabel: bonusLabel(int(c.bonus_points), lang, starMode),
        };
    }

    return card || celebrate ? { card, celebrate } : null;
}

/** Exactly what QuestCard.astro renders, and what its live refresh (on
 * `ftm:deck-empty`) writes back into the DOM. Pure so it is testable without one. */
export interface QuestDomUpdate {
    showDone: boolean;
    emoji: string;
    title: string;
    progressLabel: string;
    barWidthPct: number;
    daysLeftLabel: string;
    bonusLabel: string;
    doneHeading: string;
    doneBonusLabel: string;
}

export function questDomUpdate(view: QuestView, lang: Lang): QuestDomUpdate {
    const { card, celebrate } = view;
    return {
        // A result waiting to be seen wins over this week's progress.
        showDone: celebrate != null || card?.done === true,
        emoji: card?.emoji ?? celebrate?.emoji ?? "",
        title: card?.title ?? "",
        progressLabel: card?.progressLabel ?? "",
        barWidthPct: card?.barPct ?? 0,
        daysLeftLabel: card?.daysLeftLabel ?? "",
        bonusLabel: card?.bonusLabel ?? "",
        doneHeading: celebrate?.heading ?? doneHeading(lang, false),
        doneBonusLabel: celebrate?.bonusLabel ?? card?.bonusLabel ?? "",
    };
}

/** Parent hub chip for a kid's weekly quest: "🏁 3/5", "🏁 ✓", or null. */
export function questChip(kid: any): string | null {
    if (kid?.quest_target == null) return null;
    if (kid.quest_done === true) return "🏁 ✓";
    return `🏁 ${int(kid.quest_progress)}/${int(kid.quest_target)}`;
}
