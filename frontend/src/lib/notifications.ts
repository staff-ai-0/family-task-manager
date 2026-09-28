import { dayKeyInTz } from "./datetime";

export type DayBucket = "today" | "yesterday" | "earlier";

function previousDayKey(key: string): string {
    const [y, m, d] = key.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/** Group feed items under Today / Yesterday / Earlier in the FAMILY timezone
 *  (SSR runs in UTC; a 10 pm Mexico City item is already "tomorrow" in UTC). */
export function groupByDay<T extends { created_at: string }>(
    items: T[],
    tz: string | null | undefined,
    now: Date = new Date(),
): { bucket: DayBucket; items: T[] }[] {
    const today = dayKeyInTz(now, tz);
    const yesterday = previousDayKey(today);
    const buckets: Record<DayBucket, T[]> = { today: [], yesterday: [], earlier: [] };
    for (const item of items) {
        const key = dayKeyInTz(item.created_at, tz);
        // A slightly-ahead server clock can stamp an item "tomorrow": still today.
        const bucket: DayBucket =
            key && key >= today ? "today" : key === yesterday ? "yesterday" : "earlier";
        buckets[bucket].push(item);
    }
    return (["today", "yesterday", "earlier"] as const)
        .filter((b) => buckets[b].length > 0)
        .map((b) => ({ bucket: b, items: buckets[b] }));
}

/** Where tapping a notification may send the browser: same-origin paths only. */
export function safeNotificationLink(link: unknown): string {
    if (typeof link !== "string") return "/notifications";
    const path = link.trim();
    if (!path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) {
        return "/notifications";
    }
    // Belt-and-suspenders: the WHATWG URL parser strips embedded tab/newline
    // bytes before parsing, so "/\t/evil.example/x" becomes "//evil.example/x"
    // (protocol-relative) even though the startsWith checks above missed it.
    // Resolving against a sentinel origin and checking it survived catches that.
    try {
        const u = new URL(path, "http://x.invalid");
        return u.origin === "http://x.invalid" ? u.pathname + u.search + u.hash : "/notifications";
    } catch (_) {
        return "/notifications";
    }
}
