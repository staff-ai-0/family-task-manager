/**
 * Shared Jarvis SSE chat client. Owns the POST /api/jarvis/chat-stream fetch
 * and the SSE frame parsing (event:/data: blocks separated by \n\n) so chat
 * pages (parent/jarvis.astro copilot, soporte.astro support) don't each carry
 * a hand-rolled stream parser. Rendering stays page-owned via callbacks.
 */

export interface JarvisStreamHandlers {
    /** Non-OK HTTP response (403 gate, 422 validation, 429 cap, 503 disabled). */
    onHttpError: (resp: Response) => void | Promise<void>;
    /** SSE "tool" event (copilot only). */
    onTool?: (payload: any) => void;
    /** SSE "confirm" event (copilot HITL only). */
    onConfirm?: (payload: any) => void;
    /** SSE "reply" event — the final assistant message. */
    onReply: (payload: any) => void;
    /** SSE "error" event — in-stream failure payload ({detail}). */
    onError: (payload: any) => void;
    /** Transport failure (fetch threw / stream broke mid-read). */
    onNetworkError: (err: unknown) => void;
}

export async function streamJarvisChat(
    body: { message: string; model?: string; mode?: "copilot" | "support" },
    handlers: JarvisStreamHandlers,
): Promise<void> {
    try {
        const resp = await fetch("/api/jarvis/chat-stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok || !resp.body) {
            await handlers.onHttpError(resp);
            return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });

            let idx;
            while ((idx = buf.indexOf("\n\n")) >= 0) {
                const chunk = buf.slice(0, idx);
                buf = buf.slice(idx + 2);
                let event = "message";
                let dataStr = "";
                for (const line of chunk.split("\n")) {
                    if (line.startsWith("event: ")) event = line.slice(7).trim();
                    else if (line.startsWith("data: ")) dataStr += line.slice(6);
                }
                let payload: any = {};
                try {
                    payload = dataStr ? JSON.parse(dataStr) : {};
                } catch {}

                if (event === "tool") handlers.onTool?.(payload);
                else if (event === "confirm") handlers.onConfirm?.(payload);
                else if (event === "reply") handlers.onReply(payload);
                else if (event === "error") handlers.onError(payload);
                // "thinking" / "done" are UI no-ops: the pages show their own
                // pending indicator optimistically and "done" is a sentinel.
            }
        }
    } catch (err) {
        handlers.onNetworkError(err);
    }
}
