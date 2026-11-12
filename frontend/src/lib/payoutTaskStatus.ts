/**
 * Status line of one chore in a paycheck week (/parent/payouts: the
 * outstanding weeks rendered on the server and the history the page loads in
 * the browser). One copy, so the two lists cannot word a status differently.
 */
import { t } from "./i18n";

export function payoutTaskStatusLabel(task: any, lang: "es" | "en" | string): string {
    const es = lang === "es";
    if (task?.status === "credited") {
        const base = es ? "Completada ✓" : "Completed ✓";
        return task.grade === "partial"
            ? `${base} · ${es ? "parcial" : "partial"} ${task.partial_credit_pct}%`
            : base;
    }
    if (task?.status === "pending_review") return es ? "Esperando revisión" : "Awaiting review";
    if (task?.status === "missed") return es ? "No cumplida" : "Missed";
    if (task?.status === "taken") return t(es ? "es" : "en", "pac_status_taken");
    return es ? "Sin hacer" : "Not done yet";
}
