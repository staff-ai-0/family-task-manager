/**
 * Shared client-side mutation helper.
 *
 * The app has ~30 `location.reload()` calls after writes — each one re-runs a
 * full SSR page (4-8 serial API calls) just to reflect one change. This helper
 * is the optimistic alternative: apply the UI change immediately, POST, and on
 * failure revert + toast the real error. No full reload.
 *
 *   await mutate("/api/chat/123/reactions", {
 *     body: { emoji: "👍" },
 *     optimistic: () => bumpChip(+1),
 *     revert: () => bumpChip(-1),
 *   });
 */
import { showToast } from "./toast";

export interface MutateOptions {
  method?: string;
  body?: unknown;
  /** Apply the UI change immediately (before the request). */
  optimistic?: () => void;
  /** Undo the optimistic change if the request fails. */
  revert?: () => void;
  /** Toast shown on success (optional). */
  successToast?: string;
  /** Message when the backend gives no detail. */
  errorFallback?: string;
}

/** Returns the Response on success (body unread, caller may parse it for
 *  authoritative state), or null on failure (after reverting + toasting). */
export async function mutate(url: string, opts: MutateOptions = {}): Promise<Response | null> {
  opts.optimistic?.();
  try {
    const hasBody = opts.body !== undefined && opts.body !== null;
    const res = await fetch(url, {
      method: opts.method ?? "POST",
      headers: hasBody ? { "Content-Type": "application/json" } : undefined,
      body: hasBody ? JSON.stringify(opts.body) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      const detail = err && (err.detail || err.message);
      throw new Error(typeof detail === "string" ? detail : (opts.errorFallback ?? `Error ${res.status}`));
    }
    if (opts.successToast) showToast(opts.successToast, "success");
    return res;
  } catch (e) {
    opts.revert?.();
    showToast(e instanceof Error ? e.message : (opts.errorFallback ?? "Error"), "error");
    return null;
  }
}
