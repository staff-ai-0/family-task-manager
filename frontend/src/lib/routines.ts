/** Kid-dashboard strip for icon tap-through routines (UX-A): at most two,
 *  morning first, then evening, then the rest. */
export interface DashboardRoutine {
    id: string;
    name: string;
    name_es?: string | null;
    icon?: string | null;
    time_of_day?: string | null;
    sort_order?: number | null;
    steps_done: number;
    total_steps: number;
    completed: boolean;
}

const TIME_RANK: Record<string, number> = { morning: 0, evening: 1 };
const rank = (r: DashboardRoutine) => TIME_RANK[r.time_of_day ?? ""] ?? 2;

export function pickDashboardRoutines(routines: unknown, max = 2): DashboardRoutine[] {
    if (!Array.isArray(routines)) return [];
    return (routines as DashboardRoutine[])
        .filter((r) => (r?.total_steps ?? 0) > 0)
        .sort((a, b) => rank(a) - rank(b) || (a.sort_order ?? 0) - (b.sort_order ?? 0))
        .slice(0, max);
}

export function routineName(r: DashboardRoutine, lang: string): string {
    return lang === "es" ? r.name_es || r.name : r.name;
}

export function routineProgress(r: DashboardRoutine): string {
    return r.completed ? "✓" : `${r.steps_done}/${r.total_steps}`;
}
