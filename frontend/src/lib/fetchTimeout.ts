/**
 * fetch() with a hard deadline. Without one, a stalled mobile connection leaves
 * the swipe deck "busy" forever: the card never moves and nothing says why.
 *
 * Rejects with `FetchTimeoutError` (distinguishable from a plain offline
 * `TypeError`) so callers can word the message honestly.
 */
export class FetchTimeoutError extends Error {
    constructor(ms: number) {
        super(`Request timed out after ${ms}ms`);
        this.name = "FetchTimeoutError";
    }
}

export async function fetchWithTimeout(
    input: RequestInfo | URL,
    init: RequestInit | undefined,
    ms: number,
): Promise<Response> {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, ms);
    try {
        return await fetch(input, { ...init, signal: controller.signal });
    } catch (e) {
        if (timedOut) throw new FetchTimeoutError(ms);
        throw e;
    } finally {
        clearTimeout(timer);
    }
}
