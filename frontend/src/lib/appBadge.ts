/** UX-D4a: the number on the app icon — "things waiting for you".
 *  App Badging API (installed PWA on iOS 16.4+, Android, desktop Chromium).
 *  Everything here is a no-op where the API is missing. */

export type BadgeNavigator = {
    setAppBadge?: (n?: number) => Promise<void>;
    clearAppBadge?: () => Promise<void>;
};

export type BadgeAction = { op: "set"; n: number } | { op: "clear" };

/** A positive whole number is shown; anything else clears the icon. */
export function badgeAction(count: unknown): BadgeAction {
    return typeof count === "number" && Number.isInteger(count) && count > 0
        ? { op: "set", n: count }
        : { op: "clear" };
}

function defaultNav(): BadgeNavigator {
    return typeof navigator === "undefined" ? {} : (navigator as unknown as BadgeNavigator);
}

export async function applyAppBadge(count: unknown, nav: BadgeNavigator = defaultNav()): Promise<void> {
    const action = badgeAction(count);
    try {
        if (action.op === "set") await nav.setAppBadge?.(action.n);
        else await nav.clearAppBadge?.();
    } catch {
        /* permission denied / unsupported: the number is a nicety */
    }
}

/** Ask the server and update the icon. 401/403 means the session is gone, so
 *  the number is cleared; any other failure leaves the current number alone. */
export async function refreshAppBadge(
    fetchImpl: typeof fetch = fetch,
    nav: BadgeNavigator = defaultNav(),
): Promise<void> {
    try {
        const r = await fetchImpl("/api/notifications/waiting-count", { credentials: "same-origin" });
        if (r.status === 401 || r.status === 403) return applyAppBadge(0, nav);
        if (!r.ok) return;
        const data = await r.json();
        await applyAppBadge(data?.count, nav);
    } catch {
        /* offline: keep what is shown */
    }
}
