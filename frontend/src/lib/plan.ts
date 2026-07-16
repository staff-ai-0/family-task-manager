import { apiFetch } from "@lib/api";

/**
 * Server-side plan check for premium upsell UI.
 *
 * Returns true ONLY when the family's plan is positively "free".
 * Fails OPEN: a fetch error or unknown response shape returns false so a
 * paying parent is never shown an upsell by a hiccup — the backend still
 * enforces require_feature, so nothing leaks.
 *
 * /api/subscriptions/current returns the plan name at plan.name for a paid
 * subscription (SubscriptionResponse) but as a flat plan_name on the free
 * fallback dict — read both. Same logic as budget/reports.astro.
 */
export async function isFreePlan(token: string | undefined): Promise<boolean> {
    const { data } = await apiFetch<any>("/api/subscriptions/current", { token });
    const planName = (data?.plan?.name ?? data?.plan_name ?? "").toLowerCase();
    return planName === "free";
}
