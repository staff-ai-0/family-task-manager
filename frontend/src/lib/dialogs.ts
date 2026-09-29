/**
 * In-app replacements for window.confirm / window.prompt (UX-B1).
 *
 * The <dialog> host (components/ui/AppDialog.astro, mounted once in
 * Layout.astro) registers itself here; callers only ever see
 * confirmSheet / promptSheet. One dialog at a time (FIFO). Anything that
 * goes wrong — no host yet, a host error — resolves as "cancel", so a
 * destructive action never runs by accident.
 */

export interface ConfirmOptions {
    title: string;
    body?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
}

export interface PromptOptions extends ConfirmOptions {
    label?: string;
    defaultValue?: string;
    placeholder?: string;
    inputType?: "text" | "number";
    requireMatch?: string;
    minLength?: number;
}

export type DialogRequest =
    | { kind: "confirm"; opts: ConfirmOptions }
    | { kind: "prompt"; opts: PromptOptions };

export interface DialogHost {
    open(req: DialogRequest): Promise<boolean | string | null>;
}

let host: DialogHost | null = null;
let chain: Promise<unknown> = Promise.resolve();

export function registerDialogHost(h: DialogHost | null): void {
    host = h;
}

export function defaultLabels(lang: string): { ok: string; cancel: string } {
    return lang === "es" ? { ok: "Aceptar", cancel: "Cancelar" } : { ok: "OK", cancel: "Cancel" };
}

const asNumber = (value: string) => Number(value.trim().replace(",", "."));

export function isPromptValueValid(
    value: string,
    opts: Pick<PromptOptions, "requireMatch" | "inputType" | "minLength">,
): boolean {
    if (opts.requireMatch !== undefined) return value.trim() === opts.requireMatch.trim();
    if (opts.minLength !== undefined && value.trim().length < opts.minLength) return false;
    if (opts.inputType === "number") {
        return value.trim() === "" || ((value.match(/,/g) ?? []).length <= 1 && Number.isFinite(asNumber(value)));
    }
    return true;
}

export function normalizePromptValue(value: string, opts: Pick<PromptOptions, "inputType">): string {
    return opts.inputType === "number" ? value.replace(",", ".") : value;
}

function enqueue<T>(req: DialogRequest, cancelled: T): Promise<T> {
    const run = async (): Promise<T> => {
        if (!host) return cancelled;
        try {
            return (await host.open(req)) as T;
        } catch {
            return cancelled;
        }
    };
    const result = chain.then(run, run);
    chain = result.catch(() => undefined);
    return result;
}

export function confirmSheet(opts: ConfirmOptions): Promise<boolean> {
    return enqueue<boolean | string | null>({ kind: "confirm", opts }, false).then((v) => v === true);
}

export function promptSheet(opts: PromptOptions): Promise<string | null> {
    return enqueue<boolean | string | null>({ kind: "prompt", opts }, null).then((v) =>
        typeof v === "string" ? normalizePromptValue(v, opts) : null,
    );
}

/** `data-confirm-sheet` / `-body` / `-label` / `-danger` → ConfirmOptions. */
export function confirmOptionsFromDataset(ds: Record<string, string | undefined>): ConfirmOptions | null {
    const title = ds.confirmSheet;
    if (!title) return null;
    return {
        title,
        body: ds.confirmBody || undefined,
        confirmLabel: ds.confirmLabel || undefined,
        danger: ds.confirmDanger !== undefined,
    };
}

export type ToastKind = "success" | "error" | "info";

const PENDING_TOAST_KEY = "ftm:pending-toast";

function session(): Storage | null {
    try {
        return typeof window !== "undefined" ? window.sessionStorage : null;
    } catch {
        return null;
    }
}

/** Show `message` as a toast after the next page load (for "…Recargando" flows). */
export function queueToast(
    message: string,
    type: ToastKind = "info",
    storage: Pick<Storage, "setItem"> | null = session(),
): void {
    try {
        storage?.setItem(PENDING_TOAST_KEY, JSON.stringify({ message, type }));
    } catch {
        /* storage full or blocked — the toast is best-effort */
    }
}

export function takeQueuedToast(
    storage: Pick<Storage, "getItem" | "removeItem"> | null = session(),
): { message: string; type: ToastKind } | null {
    if (!storage) return null;
    try {
        const raw = storage.getItem(PENDING_TOAST_KEY);
        if (!raw) return null;
        storage.removeItem(PENDING_TOAST_KEY);
        const parsed = JSON.parse(raw);
        if (typeof parsed?.message !== "string") return null;
        const type: ToastKind = parsed.type === "success" || parsed.type === "error" ? parsed.type : "info";
        return { message: parsed.message, type };
    } catch {
        return null;
    }
}
