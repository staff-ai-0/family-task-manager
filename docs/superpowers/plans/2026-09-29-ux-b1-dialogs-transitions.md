# UX-B1 In-App Dialogs + Page Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every native `alert` / `confirm` / `prompt` in the frontend with toasts and one shared, bilingual in-app sheet, and add browser-native cross-fade page transitions.

**Architecture:** A pure TS library (`lib/dialogs.ts`) owns the API, validation, FIFO queue and a queued-toast helper; one `<dialog>` host component mounted in `Layout.astro` implements it, handles declarative `data-confirm-sheet` confirms on forms/links/buttons, and exposes `window.ftmDialogs` for `define:vars` (inline, non-module) scripts. Call sites are migrated by area; a vitest guard keeps native dialogs out.

**Tech Stack:** Astro 5 SSR, Tailwind v4, vanilla TS client scripts, vitest (node environment — no DOM tests).

**Spec:** `docs/superpowers/specs/2026-09-29-ux-b1-dialogs-transitions-design.md`

## Execution environment (read once)

- Worktree: `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-b1-dialogs` (branch `feat/ux-b1-dialogs`). Never edit the main checkout.
- From the worktree's `frontend/`: `npx vitest run test/<file>.test.ts`, `npx vitest run`, `npm run check` (astro check), `npm run build`. Run `npm ci` once if `frontend/node_modules` is missing.
- No backend change in this plan; no backend tests.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never run `git stash`.
- Call-site inventory (98 grep hits: 96 real calls + 2 comment lines in `pages/parent/jarvis.astro`) was taken on `c9c3b99`; line numbers below are from that commit — search by the quoted text if they drifted.

## Global Constraints

- No native `alert(`, `confirm(`, `prompt(` or `window.alert/confirm/prompt(` may remain anywhere in `frontend/src` (comments excepted). Google's `google.accounts.id.prompt()` is not a native dialog and stays.
- `alert` → `showToast(message, type)` from `lib/toast.ts`: `"error"` with duration `6000` for failures, `"success"` for completed actions, `"info"` otherwise. Keep the existing message text.
- Toasts that the old code showed right before `location.reload()` use `queueToast(message, type)` so they appear after the reload.
- Destructive confirms (delete, remove, reject, revoke, reset, restore, cancel a subscription/invitation, clean up duplicates) use `danger: true` and a verb label instead of "Aceptar"/"OK".
- Default sheet labels: `es` → "Aceptar" / "Cancelar"; any other `lang` → "OK" / "Cancel" (from `document.documentElement.lang`).
- Copy stays bilingual the way each page already does it. Admin pages (`pages/admin/*`) are English-only operator tools and stay English.
- Declarative confirm attributes: `data-confirm-sheet` (title, required), `data-confirm-body`, `data-confirm-label`, `data-confirm-danger` (presence = true). Do NOT reuse `data-confirm` — admin pages and mcp-tokens already use it with their own handlers.
- Inline (`define:vars` / `is:inline`) scripts cannot import modules: they call `window.ftmDialogs?.confirmSheet(...)`, `window.ftmDialogs?.promptSheet(...)`, `window.ftmDialogs?.toast(...)`, `window.ftmDialogs?.queueToast(...)`. Missing host ⇒ treat as cancel.
- Client scripts use the project pattern `document.addEventListener("astro:page-load", init); if (document.readyState !== "loading") init();` with an idempotency guard.
- Transitions: 150 ms cross-fade; bottom nav excluded from the fade; none under `prefers-reduced-motion: reduce`.
- Every new test is mutation-checked (break the guarded line, see the test fail, restore).

## Review Focus

1. **Spanish decimal comma in amount prompts** ("12,50") → accepted and returned as "12.50" (not rejected, not silently truncated to 12). Pinned in Task 1 (`isPromptValueValid` / `normalizePromptValue` tests).
2. **Typed-name confirmation** with a trailing space ("Diego ") → accepted; different case or inner text ("diego") → confirm stays disabled. Pinned in Task 1.
3. **A second dialog requested while one is open** waits its turn instead of replacing it (FIFO). Pinned in Task 1 (queue test with a fake host).
4. **"…Recargando" messages** survive the reload and show exactly once. Pinned in Task 1 (`queueToast` / `takeQueuedToast`).
5. **Guard false positives/negatives:** `google.accounts.id.prompt()`, `confirmSheet(`, `onConfirm(`, `obj.confirm(` are not flagged; code after a closed `/* … */` on the same line still is; `https://` in a string doesn't hide a later call. Pinned in Task 6.

## Plan-time refinements (vs. the spec)

- **Declarative confirms.** The scan found 10 inline `onsubmit`/`onclick="return confirm(…)"` handlers, not 2. Instead of hand-writing a listener per page, the host handles `data-confirm-sheet` attributes on forms (intercept `submit`) and on links/buttons (intercept `click`), then re-submits / re-clicks after "OK". Two existing submit listeners (logout in `MoreSheet`, redeem in `rewards.astro`) move to the attributes too.
- **`window.ftmDialogs`** for the 9 files whose calls live in `define:vars` inline scripts.
- **`minLength`** option on `promptSheet` for the two admin "reason (≥3 chars)" prompts, replacing their post-hoc alert.
- **Number prompts accept a decimal comma** and return the value normalized to a dot.
- **`queueToast`** for the 3 alert-then-reload sites.
- **Guard needs no allowlist:** the regex never matches a call preceded by `.`, so `google.accounts.id.prompt(` is naturally excluded.
- **`login.astro`**: its two `alert` calls are fallbacks for when `window.__showToast` hasn't loaded; they become `console.error(msg)` (the Google callback runs after the page's module script has loaded).

---

### Task 1: `lib/dialogs.ts` — API, validation, queue, queued toast

**Files:**
- Create: `frontend/src/lib/dialogs.ts`
- Test: `frontend/test/dialogs.test.ts`

**Interfaces:**
- Produces (used by Tasks 2–5):
  - `interface ConfirmOptions { title: string; body?: string; confirmLabel?: string; cancelLabel?: string; danger?: boolean }`
  - `interface PromptOptions extends ConfirmOptions { label?: string; defaultValue?: string; placeholder?: string; inputType?: "text" | "number"; requireMatch?: string; minLength?: number }`
  - `type DialogRequest = { kind: "confirm"; opts: ConfirmOptions } | { kind: "prompt"; opts: PromptOptions }`
  - `interface DialogHost { open(req: DialogRequest): Promise<boolean | string | null> }`
  - `registerDialogHost(h: DialogHost | null): void`
  - `confirmSheet(opts: ConfirmOptions): Promise<boolean>`
  - `promptSheet(opts: PromptOptions): Promise<string | null>`
  - `defaultLabels(lang: string): { ok: string; cancel: string }`
  - `isPromptValueValid(value: string, opts: Pick<PromptOptions, "requireMatch" | "inputType" | "minLength">): boolean`
  - `normalizePromptValue(value: string, opts: Pick<PromptOptions, "inputType">): string`
  - `confirmOptionsFromDataset(ds: Record<string, string | undefined>): ConfirmOptions | null`
  - `type ToastKind = "success" | "error" | "info"`
  - `queueToast(message: string, type?: ToastKind, storage?: Pick<Storage, "setItem"> | null): void`
  - `takeQueuedToast(storage?: Pick<Storage, "getItem" | "removeItem"> | null): { message: string; type: ToastKind } | null`

- [ ] **Step 1: Write the failing tests**

Create `frontend/test/dialogs.test.ts`:

```ts
import { afterEach, describe, expect, it } from "vitest";

import {
    confirmOptionsFromDataset,
    confirmSheet,
    defaultLabels,
    isPromptValueValid,
    normalizePromptValue,
    promptSheet,
    queueToast,
    registerDialogHost,
    takeQueuedToast,
    type DialogRequest,
} from "../src/lib/dialogs";

afterEach(() => registerDialogHost(null));

const memoryStorage = () => {
    const m = new Map<string, string>();
    return {
        getItem: (k: string) => m.get(k) ?? null,
        setItem: (k: string, v: string) => void m.set(k, v),
        removeItem: (k: string) => void m.delete(k),
    };
};

describe("defaultLabels", () => {
    it("follows the page language", () => {
        expect(defaultLabels("es")).toEqual({ ok: "Aceptar", cancel: "Cancelar" });
        expect(defaultLabels("en")).toEqual({ ok: "OK", cancel: "Cancel" });
        expect(defaultLabels("")).toEqual({ ok: "OK", cancel: "Cancel" });
    });
});

describe("isPromptValueValid", () => {
    it("requireMatch is exact after trimming", () => {
        expect(isPromptValueValid("Diego ", { requireMatch: "Diego" })).toBe(true);
        expect(isPromptValueValid("diego", { requireMatch: "Diego" })).toBe(false);
        expect(isPromptValueValid("", { requireMatch: "Diego" })).toBe(false);
    });
    it("minLength counts trimmed characters", () => {
        expect(isPromptValueValid("  ab ", { minLength: 3 })).toBe(false);
        expect(isPromptValueValid("abc", { minLength: 3 })).toBe(true);
    });
    it("numbers accept empty, dot and comma decimals, reject text", () => {
        for (const ok of ["", "12", "12.5", "12,50", "1e3", " 7 "]) {
            expect(isPromptValueValid(ok, { inputType: "number" })).toBe(true);
        }
        for (const bad of ["abc", "12abc", "1,2,3"]) {
            expect(isPromptValueValid(bad, { inputType: "number" })).toBe(false);
        }
    });
    it("plain text is always valid, even empty", () => {
        expect(isPromptValueValid("", {})).toBe(true);
    });
});

describe("normalizePromptValue", () => {
    it("turns a decimal comma into a dot for numbers only", () => {
        expect(normalizePromptValue("12,50", { inputType: "number" })).toBe("12.50");
        expect(normalizePromptValue("12,50", {})).toBe("12,50");
    });
});

describe("confirmOptionsFromDataset", () => {
    it("reads the data-confirm-sheet attributes", () => {
        expect(confirmOptionsFromDataset({ confirmSheet: "¿Eliminar?", confirmLabel: "Eliminar", confirmDanger: "" }))
            .toEqual({ title: "¿Eliminar?", body: undefined, confirmLabel: "Eliminar", danger: true });
        expect(confirmOptionsFromDataset({ confirmSheet: "¿Seguro?", confirmBody: "Detalle" }))
            .toEqual({ title: "¿Seguro?", body: "Detalle", confirmLabel: undefined, danger: false });
    });
    it("is null without a title", () => {
        expect(confirmOptionsFromDataset({ confirm: "legacy admin attribute" })).toBeNull();
        expect(confirmOptionsFromDataset({ confirmSheet: "" })).toBeNull();
    });
});

describe("confirmSheet / promptSheet", () => {
    it("fail safe without a host", async () => {
        expect(await confirmSheet({ title: "x" })).toBe(false);
        expect(await promptSheet({ title: "x" })).toBeNull();
    });
    it("a host error counts as cancel", async () => {
        registerDialogHost({ open: async () => { throw new Error("boom"); } });
        expect(await confirmSheet({ title: "x" })).toBe(false);
        expect(await promptSheet({ title: "x" })).toBeNull();
    });
    it("passes the host's answer through", async () => {
        registerDialogHost({ open: async (req) => (req.kind === "confirm" ? true : "Comida") });
        expect(await confirmSheet({ title: "¿Seguro?" })).toBe(true);
        expect(await promptSheet({ title: "Nombre" })).toBe("Comida");
    });
    it("normalizes a number prompt's answer", async () => {
        registerDialogHost({ open: async () => "12,50" });
        expect(await promptSheet({ title: "Monto", inputType: "number" })).toBe("12.50");
    });
    it("opens one dialog at a time, in order", async () => {
        const opened: string[] = [];
        const resolvers: Array<(v: boolean) => void> = [];
        registerDialogHost({
            open: (req: DialogRequest) => {
                opened.push(req.opts.title);
                return new Promise((resolve) => resolvers.push(resolve));
            },
        });
        const flush = () => new Promise((r) => setTimeout(r, 0));
        const first = confirmSheet({ title: "A" });
        const second = confirmSheet({ title: "B" });
        await flush();
        expect(opened).toEqual(["A"]);
        resolvers[0](true);
        expect(await first).toBe(true);
        await flush();
        expect(opened).toEqual(["A", "B"]);
        resolvers[1](false);
        expect(await second).toBe(false);
    });
});

describe("queueToast / takeQueuedToast", () => {
    it("hands the toast to the next page exactly once", () => {
        const s = memoryStorage();
        queueToast("3 duplicados eliminados", "success", s);
        expect(takeQueuedToast(s)).toEqual({ message: "3 duplicados eliminados", type: "success" });
        expect(takeQueuedToast(s)).toBeNull();
    });
    it("ignores garbage and missing storage", () => {
        const s = memoryStorage();
        s.setItem("ftm:pending-toast", "{not json");
        expect(takeQueuedToast(s)).toBeNull();
        expect(() => queueToast("x", "info", null)).not.toThrow();
        expect(takeQueuedToast(null)).toBeNull();
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npx vitest run test/dialogs.test.ts`
Expected: FAIL — cannot resolve `../src/lib/dialogs`.

- [ ] **Step 3: Implement `frontend/src/lib/dialogs.ts`**

```ts
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
```

Note for `takeQueuedToast`: the key is removed **before** parsing, so a garbage value is dropped too (the "ignores garbage" test then sees `null` on the first call).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run test/dialogs.test.ts`
Expected: PASS.

- [ ] **Step 5: Mutation-check**

One at a time, confirm the named test fails, then restore: (a) drop `.trim()` on the value in the `requireMatch` branch → "requireMatch is exact after trimming"; (b) remove `.replace(",", ".")` in `asNumber` → "numbers accept … comma decimals"; (c) replace `chain.then(run, run)` with `run()` → "opens one dialog at a time, in order"; (d) remove `storage.removeItem(...)` → "hands the toast to the next page exactly once"; (e) return `true` instead of `cancelled` when `!host` → "fail safe without a host".

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/dialogs.ts frontend/test/dialogs.test.ts
git commit -m "feat(dialogs): in-app confirm/prompt API with queue and queued toasts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `AppDialog.astro` host, declarative confirms, `window.ftmDialogs`

**Files:**
- Create: `frontend/src/components/ui/AppDialog.astro`
- Modify: `frontend/src/layouts/Layout.astro` (mount it after `<ToastContainer />`)
- Modify: `frontend/src/env.d.ts` (type `window.ftmDialogs`)

**Interfaces:**
- Consumes (Task 1): everything exported by `lib/dialogs.ts`; `showToast(message, type, durationMs)` from `lib/toast.ts`.
- Produces: a registered dialog host on every page; declarative `data-confirm-sheet` handling for `form` (submit) and `a` / `button` (click); `window.ftmDialogs = { confirmSheet, promptSheet, toast, queueToast }`; queued toast shown on load.

- [ ] **Step 1: Create `frontend/src/components/ui/AppDialog.astro`**

```astro
---
/**
 * The one in-app confirm/prompt sheet (UX-B1). Mounted once by Layout.astro.
 * Native <dialog> + showModal(): top layer (always above the bottom nav),
 * Esc handling and an inert page behind it. Bottom sheet on phones, centered
 * card from `sm`. Callers use lib/dialogs.ts (or window.ftmDialogs from
 * define:vars scripts); declarative confirms use data-confirm-sheet.
 */
---

<dialog
    id="app-dialog"
    aria-labelledby="app-dialog-title"
    class="app-dialog p-0 bg-transparent backdrop:bg-black/40"
>
    <form method="dialog" class="app-dialog-panel bg-brand-cream text-brand-ink border-2 border-brand-ink rounded-t-3xl sm:rounded-3xl shadow-[var(--shadow-card)] px-5 pt-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
        <h2 id="app-dialog-title" class="font-display text-lg font-extrabold leading-tight"></h2>
        <p id="app-dialog-body" class="mt-2 text-sm text-brand-ink-soft whitespace-pre-line" hidden></p>
        <div id="app-dialog-field" class="mt-4" hidden>
            <label id="app-dialog-label" for="app-dialog-input" class="sr-only"></label>
            <input
                id="app-dialog-input"
                autocomplete="off"
                class="w-full rounded-xl border-2 border-brand-ink/20 bg-white px-3 py-2.5 text-base text-brand-ink outline-none focus:border-brand-sky-deep"
            />
        </div>
        <div class="mt-5 flex gap-2">
            <button type="button" id="app-dialog-cancel"
                class="flex-1 rounded-xl border-2 border-brand-ink/15 bg-white py-3 text-sm font-bold text-brand-ink"></button>
            <button type="submit" id="app-dialog-ok"
                class="flex-1 rounded-xl py-3 text-sm font-bold text-white disabled:opacity-40"></button>
        </div>
    </form>
</dialog>

<style>
    .app-dialog {
        position: fixed;
        inset: auto 0 0 0;
        width: 100%;
        max-width: none;
        margin: 0;
        max-height: 100dvh;
    }
    @media (min-width: 640px) {
        .app-dialog {
            inset: 0;
            margin: auto;
            width: min(24rem, calc(100% - 2rem));
            height: fit-content;
        }
    }
    .app-dialog[open] .app-dialog-panel {
        animation: app-sheet-in 160ms ease-out;
    }
    @keyframes app-sheet-in {
        from { transform: translateY(24px); opacity: 0; }
        to { transform: none; opacity: 1; }
    }
    @media (prefers-reduced-motion: reduce) {
        .app-dialog[open] .app-dialog-panel { animation: none; }
    }
</style>

<script>
    import {
        confirmOptionsFromDataset,
        confirmSheet,
        defaultLabels,
        isPromptValueValid,
        promptSheet,
        queueToast,
        registerDialogHost,
        takeQueuedToast,
        type DialogRequest,
    } from "../../lib/dialogs";
    import { showToast } from "../../lib/toast";

    function initAppDialog() {
        const dlg = document.getElementById("app-dialog") as HTMLDialogElement | null;
        if (!dlg || dlg.dataset.bound === "1") return;
        dlg.dataset.bound = "1";

        const title = dlg.querySelector<HTMLElement>("#app-dialog-title")!;
        const body = dlg.querySelector<HTMLElement>("#app-dialog-body")!;
        const field = dlg.querySelector<HTMLElement>("#app-dialog-field")!;
        const label = dlg.querySelector<HTMLElement>("#app-dialog-label")!;
        const input = dlg.querySelector<HTMLInputElement>("#app-dialog-input")!;
        const ok = dlg.querySelector<HTMLButtonElement>("#app-dialog-ok")!;
        const cancel = dlg.querySelector<HTMLButtonElement>("#app-dialog-cancel")!;

        let current: DialogRequest | null = null;
        let settle: ((v: boolean | string | null) => void) | null = null;
        let returnFocus: HTMLElement | null = null;

        const cancelled = () => (current?.kind === "prompt" ? null : false);
        const finish = (value: boolean | string | null) => {
            const resolve = settle;
            settle = null;
            current = null;
            if (dlg.open) dlg.close();
            returnFocus?.focus?.();
            returnFocus = null;
            resolve?.(value);
        };
        const validate = () => {
            ok.disabled = current?.kind === "prompt" ? !isPromptValueValid(input.value, current.opts) : false;
        };

        registerDialogHost({
            open(req) {
                return new Promise((resolve) => {
                    current = req;
                    settle = resolve;
                    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                    const labels = defaultLabels(document.documentElement.lang);
                    const o = req.opts;
                    title.textContent = o.title;
                    body.textContent = o.body ?? "";
                    body.hidden = !o.body;
                    ok.textContent = o.confirmLabel ?? labels.ok;
                    cancel.textContent = o.cancelLabel ?? labels.cancel;
                    ok.classList.toggle("bg-red-600", !!o.danger);
                    ok.classList.toggle("bg-brand-sky-deep", !o.danger);
                    if (req.kind === "prompt") {
                        field.hidden = false;
                        label.textContent = req.opts.label ?? o.title;
                        input.type = "text";
                        input.inputMode = req.opts.inputType === "number" ? "decimal" : "text";
                        input.placeholder = req.opts.placeholder ?? "";
                        input.value = req.opts.defaultValue ?? "";
                    } else {
                        field.hidden = true;
                    }
                    validate();
                    dlg.showModal();
                    if (req.kind === "prompt") {
                        input.focus();
                        input.select();
                    } else {
                        (o.danger ? cancel : ok).focus();
                    }
                });
            },
        });

        dlg.addEventListener("submit", (e) => {
            e.preventDefault();
            if (!current || ok.disabled) return;
            finish(current.kind === "prompt" ? input.value : true);
        });
        cancel.addEventListener("click", () => finish(cancelled()));
        // Esc
        dlg.addEventListener("cancel", (e) => {
            e.preventDefault();
            finish(cancelled());
        });
        // Tap on the backdrop (the click lands on the <dialog> itself, outside the panel)
        dlg.addEventListener("click", (e) => {
            if (e.target === dlg) finish(cancelled());
        });
        input.addEventListener("input", validate);

        // Declarative confirms: <form data-confirm-sheet="…"> and
        // <a|button data-confirm-sheet="…">. After "OK" the original action is
        // replayed once (flag data-confirm-sheet-ok lets it through).
        document.addEventListener(
            "submit",
            async (e) => {
                const form = e.target;
                if (!(form instanceof HTMLFormElement)) return;
                const opts = confirmOptionsFromDataset(form.dataset);
                if (!opts) return;
                if (form.dataset.confirmSheetOk === "1") {
                    delete form.dataset.confirmSheetOk;
                    return;
                }
                e.preventDefault();
                const submitter = (e as SubmitEvent).submitter;
                if (await confirmSheet(opts)) {
                    form.dataset.confirmSheetOk = "1";
                    form.requestSubmit(submitter instanceof HTMLElement && (submitter as HTMLButtonElement).form === form ? submitter : undefined);
                }
            },
            true,
        );
        document.addEventListener(
            "click",
            async (e) => {
                const el = (e.target as Element | null)?.closest?.("a[data-confirm-sheet], button[data-confirm-sheet]");
                if (!(el instanceof HTMLElement)) return;
                if (el.dataset.confirmSheetOk === "1") {
                    delete el.dataset.confirmSheetOk;
                    return;
                }
                const opts = confirmOptionsFromDataset(el.dataset);
                if (!opts) return;
                e.preventDefault();
                e.stopImmediatePropagation();
                if (await confirmSheet(opts)) {
                    el.dataset.confirmSheetOk = "1";
                    el.click();
                }
            },
            true,
        );

        // For define:vars / is:inline scripts, which cannot import modules.
        window.ftmDialogs = { confirmSheet, promptSheet, toast: showToast, queueToast };

        const pending = takeQueuedToast();
        if (pending) showToast(pending.message, pending.type, pending.type === "error" ? 6000 : 4000);
    }

    document.addEventListener("astro:page-load", initAppDialog);
    // astro:page-load is one-shot on DOMContentLoaded; a module running after
    // it would miss it (see WelcomeTour.astro). data-bound keeps this idempotent.
    if (document.readyState !== "loading") initAppDialog();
</script>
```

- [ ] **Step 2: Type `window.ftmDialogs`**

In `frontend/src/env.d.ts`, inside `interface Window { … }`, add:

```ts
    /** In-app dialogs for define:vars / is:inline scripts (UX-B1, set by AppDialog.astro). */
    ftmDialogs?: {
        confirmSheet: typeof import("./lib/dialogs").confirmSheet;
        promptSheet: typeof import("./lib/dialogs").promptSheet;
        toast: typeof import("./lib/toast").showToast;
        queueToast: typeof import("./lib/dialogs").queueToast;
    };
```

- [ ] **Step 3: Mount it once**

In `frontend/src/layouts/Layout.astro`: add `import AppDialog from "../components/ui/AppDialog.astro";` next to the `ToastContainer` import, and render `<AppDialog />` on the line right after `<ToastContainer />` inside `<body>`.

- [ ] **Step 4: Verify**

Run (from `frontend/`): `npm run check && npx vitest run && npm run build`
Expected: 0 errors / 0 warnings in the files you touched; vitest green; build completes.
Then self-review by hand-tracing: confirm (danger → focus Cancel, red button; Esc / backdrop / Cancel → false; OK → true), prompt (default value selected; Enter with a valid value → string; `requireMatch` keeps OK disabled until it matches; Cancel → null), declarative form (submit → sheet → OK → exactly one real submit with the original submitter; Cancel → no submit), declarative link/button (click → sheet → OK → exactly one real navigation/submit).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/AppDialog.astro frontend/src/layouts/Layout.astro frontend/src/env.d.ts
git commit -m "feat(dialogs): shared in-app sheet host with declarative confirms

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Migrate the budget area (6 files, 42 calls)

**Files:**
- Modify: `frontend/src/pages/budget/transactions.astro`, `frontend/src/pages/budget/settings.astro`, `frontend/src/pages/budget/index.astro`, `frontend/src/pages/budget/reports.astro`, `frontend/src/components/budget/ReceiptScanSheet.astro`, `frontend/src/components/AssignFundsModal.astro`

**Interfaces:**
- Consumes (Tasks 1–2): in **module** `<script>` blocks import `confirmSheet`, `promptSheet`, `queueToast` from `lib/dialogs` and `showToast` from `lib/toast` (use the relative path the file's other imports use). In **`define:vars` / `is:inline`** blocks use `window.ftmDialogs?.confirmSheet / promptSheet / toast / queueToast`. `budget/settings.astro` already defines a local `showToast(msg, type)` — keep using it there. Files with inline blocks: `AssignFundsModal.astro` (whole script), `budget/settings.astro` (whole script), `budget/transactions.astro` (the two `define:vars` blocks around lines 629–971 and 972–1288; lines 1289+ are a module script).

**Conversion patterns** (apply to every row):

```ts
// alert → toast
showToast(msg, "error", 6000);                       // module
window.ftmDialogs?.toast(msg, "error", 6000);        // inline

// confirm → sheet (make the enclosing handler async if it isn't)
if (!(await confirmSheet({ title: MSG, confirmLabel: LABEL, danger: true }))) return;
if (!(await window.ftmDialogs?.confirmSheet({ title: MSG, confirmLabel: LABEL }))) return;   // inline

// prompt → sheet (null = cancelled, same as before)
const name = await promptSheet({ title: MSG, defaultValue: CURRENT, confirmLabel: LABEL });
const name = (await window.ftmDialogs?.promptSheet({ title: MSG })) ?? null;                  // inline

// alert then reload → queued toast
queueToast(msg, "success");  window.location.reload();
```

Labels below are written `es / en`; use the file's own language switch (`es`, `isEs`, `lang === "es"`).

| File:line (c9c3b99) | Now | Becomes |
|---|---|---|
| AssignFundsModal:333 | `prompt(...)` amount | `promptSheet({ title: <same text>, defaultValue: <same default>, inputType: "number", confirmLabel: "Guardar / Save" })` (inline → `window.ftmDialogs`) |
| AssignFundsModal:338 | alert invalid amount | toast error |
| AssignFundsModal:345 | alert could not hold | toast error |
| ReceiptScanSheet:285 | confirm premium gate | `confirmSheet({ title: "El escaneo de recibos requiere un plan Plus o Pro / Receipt scanning requires a Plus or Pro plan", body: "¿Ver los planes? / See the plans?", confirmLabel: "Ver planes / See plans" })` |
| ReceiptScanSheet:302, 309, 441, 445 | alert errors | toast error |
| budget/index:293 | prompt new category | `promptSheet({ title: "Nueva categoría en {group} / New category in {group}", label: "Nombre / Name", confirmLabel: "Crear / Create" })` |
| budget/index:311 | alert create failed | toast error |
| budget/index:368 | confirm close/reopen month | `confirmSheet({ title: <same text>, confirmLabel: closed ? "Reabrir / Reopen" : "Cerrar mes / Close month" })` |
| budget/index:376 | alert lock failed | toast error |
| budget/index:385 | confirm auto-fill | `confirmSheet({ title: <same text>, confirmLabel: "Llenar / Fill" })` |
| budget/index:419 | confirm copy last month | `confirmSheet({ title: <same text>, confirmLabel: "Copiar / Copy" })` |
| budget/index:456 | alert copy failed | toast error |
| reports:706 | confirm delete report | `confirmSheet({ title: <same text>, confirmLabel: "Eliminar / Delete", danger: true })` |
| reports:723 | alert name the report | toast info |
| reports:742 | alert save failed | toast error |
| settings:919 | prompt new group | `promptSheet({ title: <same text>, confirmLabel: "Crear / Create" })` |
| settings:929 | prompt rename group | `promptSheet({ title: <same text>, defaultValue: current, confirmLabel: "Guardar / Save" })` |
| settings:961 | prompt new category | `promptSheet({ title: <same text>, confirmLabel: "Crear / Create" })` |
| settings:971 | prompt rename category | `promptSheet({ title: <same text>, defaultValue: current, confirmLabel: "Guardar / Save" })` |
| settings:989 | prompt category notes | `promptSheet({ title: <same text>, defaultValue: <same default>, confirmLabel: "Guardar / Save" })` |
| settings:1002 | prompt monthly goal | `promptSheet({ title: <same text>, defaultValue: <same default>, inputType: "number", confirmLabel: "Guardar / Save" })` — keep the existing `parseFloat(val \|\| "0")` handling |
| settings:1123 | prompt type RESTAURAR | `promptSheet({ title: "Restaurar copia / Restore backup", body: <same warning text>, requireMatch: word, danger: true, confirmLabel: "Restaurar / Restore" })`; keep `if (typed !== word) return;` (compare `typed?.trim()`) |
| transactions:700 | alert need 2 rows | toast info (inline) |
| transactions:726 | alert split failed | toast error (inline) |
| transactions:1234 | alert no duplicates | toast info (inline) |
| transactions:1240 | confirm clean duplicates | `confirmSheet({ title: <same text>, confirmLabel: "Limpiar / Clean up", danger: true })` (inline) |
| transactions:1243 | alert "…Recargando" then reload | `window.ftmDialogs?.queueToast(<same text without "Recargando..." / "Reloading...">, "success")` then reload |
| transactions:1248 | alert error | toast error (inline) |
| transactions:1264 | confirm AI-categorize | `confirmSheet({ title: <same text>, confirmLabel: "Categorizar / Categorize" })` (inline) |
| transactions:1273 | alert "…Recargando" then reload | queueToast success (same rule as 1243) |
| transactions:1278 | alert error | toast error (inline) |
| transactions:1354, 1363, 1376 | alert `e.message` | toast error |
| transactions:1367 | confirm bulk delete | `confirmSheet({ title: <same text>, confirmLabel: "Eliminar / Delete", danger: true })` |
| transactions:1410 | confirm delete filter | `confirmSheet({ title: <same text>, confirmLabel: "Eliminar / Delete", danger: true })` |
| transactions:1428 | alert apply a filter first | toast info |
| transactions:1431 | prompt filter name | `promptSheet({ title: "Guardar filtro / Save filter", label: <same text>, confirmLabel: "Guardar / Save" })` |
| transactions:1439 | alert save failed | toast error |

- [ ] **Step 1: Apply the table file by file.** Read each call in context first; keep every existing behavior (early returns, disabled buttons, reloads) and only swap the dialog. Where a handler becomes `async`, make sure nothing relied on its synchronous return value.
- [ ] **Step 2: Prove none remain in these files**

Run (from `frontend/src`): `grep -nE '(^|[^a-zA-Z0-9_.$])(alert|confirm|prompt)\s*\(|window\.(alert|confirm|prompt)\s*\(' pages/budget/*.astro components/budget/ReceiptScanSheet.astro components/AssignFundsModal.astro | grep -vE '^\S+:\s*(//|\*)' || echo "clean"`
Expected: `clean`.

- [ ] **Step 3: Verify** — from `frontend/`: `npm run check && npx vitest run && npm run build` (0 errors).
- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/budget frontend/src/components/budget/ReceiptScanSheet.astro frontend/src/components/AssignFundsModal.astro
git commit -m "refactor(budget): in-app sheets and toasts instead of native dialogs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Migrate the parent area (14 files, 28 calls)

**Files:**
- Modify: `frontend/src/pages/parent/{gigs,approvals,members,tasks,rewards,consequences,kiosk,jarvis-schedules,routines,starter-packs}.astro`, `frontend/src/pages/parent/settings/{mcp-tokens,a2a,subscription,family-bank}.astro`

**Interfaces:**
- Consumes (Tasks 1–2): same as Task 3 (module scripts import; `define:vars` scripts use `window.ftmDialogs`). Inline-script files here: `kiosk.astro`, `routines.astro`, `starter-packs.astro`, `settings/mcp-tokens.astro`, `settings/subscription.astro`.
- **Declarative confirms** (for the inline `onsubmit` / `onclick` handlers): delete the handler attribute and add, on the same element, `data-confirm-sheet={TITLE}` plus `data-confirm-label={LABEL}` and `data-confirm-danger` where the table says so. The host replays the submit/click after "OK".

| File:line (c9c3b99) | Now | Becomes |
|---|---|---|
| gigs:565, 595, 615 | alert `err.detail ?? "Error"` | toast error |
| gigs:574 | confirm reject proposal | `confirmSheet({ title: <same text>, confirmLabel: "Rechazar / Reject", danger: true })` |
| gigs:603 | confirm archive gig | `confirmSheet({ title: <same text>, confirmLabel: "Archivar / Archive" })` |
| approvals:368, 376 | alert `lastError \|\| "Error al procesar"` | toast error |
| approvals:404 | alert `${failed} no se pudieron aprobar` | toast error |
| approvals:409 | confirm approve all | `confirmSheet({ title: <same text>, confirmLabel: "Aprobar todo / Approve all" })` |
| members:407 | inline `onsubmit` reject request | form: `data-confirm-sheet={<same text>} data-confirm-label="Rechazar / Reject" data-confirm-danger` |
| members:499 | inline `onsubmit` typed-name permanent delete | see Step 2 |
| members:669 | confirm cancel invitation | `confirmSheet({ title: <same text>, confirmLabel: "Cancelar invitación / Cancel invitation", cancelLabel: "Volver / Back", danger: true })` |
| mcp-tokens:212, 291 | confirm revoke (`btn.dataset.confirm`) | `window.ftmDialogs?.confirmSheet({ title: <same>, confirmLabel: "Revocar / Revoke", danger: true })` — keep the existing `data-confirm` attribute as the title source |
| mcp-tokens:254 | alert mint failed | toast error (inline) |
| a2a:89 | alert msg (error) | toast error |
| a2a:98 | alert "Guardado." | toast success |
| a2a:101 | alert connection error | toast error |
| tasks:249 | inline `onclick` shuffle | button: `data-confirm-sheet={t(lang,"shuffle_confirm")} data-confirm-label="Mezclar / Shuffle"` |
| tasks:364 | inline `onclick` delete template | `data-confirm-sheet={t(lang,"pt_delete_confirm")} data-confirm-label="Eliminar / Delete" data-confirm-danger` |
| rewards:229 | inline `onclick` delete reward | `data-confirm-sheet={t(lang,"confirm_delete")} data-confirm-label="Eliminar / Delete" data-confirm-danger` |
| consequences:301 | inline `onclick` delete | same as rewards:229 |
| kiosk:253 | inline `onsubmit` revoke device | form: `data-confirm-sheet={labels.confirm} data-confirm-label="Revocar / Revoke" data-confirm-danger` |
| jarvis-schedules:201 | inline `onsubmit` delete schedule | form: `data-confirm-sheet={labels.confirm} data-confirm-label="Eliminar / Delete" data-confirm-danger` |
| routines:314 | confirm delete routine | `window.ftmDialogs?.confirmSheet({ title: L.confirm_del, confirmLabel: "Eliminar / Delete", danger: true })` |
| starter-packs:302 | alert nothing selected | toast info (inline) |
| subscription:765 | confirm cancel subscription | `window.ftmDialogs?.confirmSheet({ title: cancelConfirm, confirmLabel: "Cancelar suscripción / Cancel subscription", cancelLabel: "Mantener plan / Keep plan", danger: true })` |
| family-bank:782 | confirm remove goal | `confirmSheet({ title: <same text>, confirmLabel: "Quitar / Remove", danger: true })` |

`pages/parent/jarvis.astro:365-366` are comments ("never alert()") — leave them.

- [ ] **Step 1: Apply the table** (same rules as Task 3 Step 1). For a label that must be bilingual inside an Astro attribute, write it as `data-confirm-label={lang === "es" ? "Eliminar" : "Delete"}`.

- [ ] **Step 2: Permanent member delete (members:499)** — replace the inline `onsubmit` on that form with `data-typed-delete` (keep `data-member-name`), and add to the page's existing module `<script>` (line ~597):

```ts
import { promptSheet } from "../../lib/dialogs";

function initTypedDelete() {
    document.querySelectorAll<HTMLFormElement>("form[data-typed-delete]").forEach((form) => {
        if (form.dataset.bound === "1") return;
        form.dataset.bound = "1";
        form.addEventListener("submit", async (e) => {
            if (form.dataset.typedOk === "1") {
                delete form.dataset.typedOk;
                return;
            }
            e.preventDefault();
            const name = form.dataset.memberName ?? "";
            const es = document.documentElement.lang === "es";
            const typed = await promptSheet({
                title: es ? `¿Eliminar a ${name} para siempre?` : `Delete ${name} permanently?`,
                body: es
                    ? "Borrado PERMANENTE (tareas, puntos e historial). Escribe el nombre exacto para confirmar."
                    : "PERMANENT deletion (tasks, points, history). Type the exact name to confirm.",
                label: es ? "Nombre del miembro" : "Member name",
                placeholder: name,
                requireMatch: name,
                danger: true,
                confirmLabel: es ? "Eliminar" : "Delete",
            });
            if (typed === null) return;
            form.querySelector<HTMLInputElement>("[name=confirm_name]")!.value = typed;
            form.dataset.typedOk = "1";
            form.requestSubmit();
        });
    });
}
document.addEventListener("astro:page-load", initTypedDelete);
if (document.readyState !== "loading") initTypedDelete();
```

(If the page's script already has an init function wired to `astro:page-load`, call `initTypedDelete()` from it instead of adding a second listener pair.)

- [ ] **Step 3: Prove none remain** — from `frontend/src`: `grep -nE '(^|[^a-zA-Z0-9_.$])(alert|confirm|prompt)\s*\(|window\.(alert|confirm|prompt)\s*\(' pages/parent/*.astro pages/parent/settings/*.astro | grep -vE ':\s*(//|\*)' || echo "clean"` → `clean`.
- [ ] **Step 4: Verify** — `npm run check && npx vitest run && npm run build`.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent
git commit -m "refactor(parent): in-app sheets and toasts instead of native dialogs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Migrate the remaining pages, components and admin (11 files, 26 calls)

**Files:**
- Modify: `frontend/src/components/MoreSheet.astro`, `frontend/src/components/TaskCreateModal.astro`, `frontend/src/pages/{rewards,shopping,chat,login,bank}.astro`, `frontend/src/pages/gigs/my-gigs.astro`, `frontend/src/pages/admin/coupons.astro`, `frontend/src/pages/admin/families/[id].astro`

**Interfaces:**
- Consumes (Tasks 1–2): same as Task 3. `TaskCreateModal.astro`'s script is inline (use attributes / `window.ftmDialogs`); `chat.astro:418-439` sit in its module script (line ~357).

| File:line (c9c3b99) | Now | Becomes |
|---|---|---|
| MoreSheet:241 | submit listener `confirm("¿Cerrar sesión?")` | delete the listener; on `form[data-logout-form]` add `data-confirm-sheet={es ? "¿Cerrar sesión?" : "Log out?"} data-confirm-label={es ? "Cerrar sesión" : "Log out"}` (use the component's server-side lang) |
| TaskCreateModal:951 | `onclick="return confirm('…')"` inside an HTML template string | replace with `data-confirm-sheet="${<same text>}" data-confirm-label="${isEs ? "Eliminar" : "Delete"}" data-confirm-danger` in the template string |
| rewards:290 | redeem submit listener with `window.confirm(msg)` | delete the listener; render on each `form[data-redeem-form]` `data-confirm-sheet={<same message built server-side from the reward name and cost>}` and `data-confirm-label={es ? "Canjear" : "Redeem"}` |
| shopping:221 | inline `onsubmit` delete | form: `data-confirm-sheet={labels.confirm_delete} data-confirm-label={<"Eliminar" / "Delete">} data-confirm-danger` |
| chat:418 | prompt edit message | `promptSheet({ title: isEs ? "Editar mensaje" : "Edit message", defaultValue: current, confirmLabel: isEs ? "Guardar" : "Save" })` |
| chat:429, 439 | alert edit/delete failed | toast error |
| chat:434 | confirm delete message | `confirmSheet({ title: <same text>, confirmLabel: isEs ? "Borrar" : "Delete", danger: true })` |
| login:99, 107 | `alert(msg)` fallback when `window.__showToast` is missing | `console.error(msg)` (keep the `window.__showToast` branch) |
| bank:592 | confirm change goal | `confirmSheet({ title: <same text>, confirmLabel: es ? "Cambiar meta" : "Change goal", danger: true })` |
| my-gigs:204, 223, 264 | alert errors | toast error |
| admin/coupons:299 | confirm deactivate | `confirmSheet({ title: \`Deactivate ${code}?\`, body: <rest of the same text>, confirmLabel: "Deactivate", danger: true })` |
| admin/coupons:320, 322, 429, 437 | `window.alert(...)` errors | toast error |
| admin/coupons:403 + 410 | prompt reason + post-check alert | `promptSheet({ title: \`Revoke this credit for ${r.family_name}?\`, label: "Reason (audited)", minLength: 3, danger: true, confirmLabel: "Revoke" })`; delete the `< 3` post-check and its alert (the sheet enforces it); keep `reason.trim()` in the payload |
| admin/families/[id]:503 | `confirm(confirmMsg)` | `confirmSheet({ title: confirmMsg, confirmLabel: "Continue", danger: true })` |
| admin/families/[id]:504 | prompt audit reason | `promptSheet({ title: "Reason for this action", body: "Recorded in the audit log.", label: "Reason", minLength: 3, confirmLabel: "Continue" })`; keep `if (!reason ...) return;` |
| admin/families/[id]:520, 526 | alert errors | toast error |
| admin/families/[id]:523 | `if (body.warning) alert(body.warning)` then reload | `if (body.warning) queueToast(body.warning, "info");` then reload |

- [ ] **Step 1: Apply the table** (same rules as Task 3 Step 1). The `data-confirm` attributes in `admin/families/[id].astro` (lines ~196–410) stay — they are read by that page's own handler, which now calls `confirmSheet`.
- [ ] **Step 2: Prove none remain anywhere** — from `frontend/src`: `grep -rnE '(^|[^a-zA-Z0-9_.$])(alert|confirm|prompt)\s*\(|window\.(alert|confirm|prompt)\s*\(' --include='*.astro' --include='*.ts' . | grep -vE ':\s*(//|\*)' || echo "clean"` → `clean` (the `google.accounts.id.prompt(` line does not match: it is preceded by `.`).
- [ ] **Step 3: Verify** — `npm run check && npx vitest run && npm run build`.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MoreSheet.astro frontend/src/components/TaskCreateModal.astro frontend/src/pages
git commit -m "refactor(ui): in-app sheets and toasts in chat, rewards, bank, admin and more

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Page transitions, regression guard, docs

**Files:**
- Modify: `frontend/src/styles/global.css`, `frontend/src/components/BottomNav.astro`, `CLAUDE.md`
- Create: `frontend/test/support/native-dialog-scan.ts`, `frontend/test/no-native-dialogs.test.ts`

**Interfaces:**
- Produces: `scanSource(text: string): { line: number; match: string }[]` (test support only).

- [ ] **Step 1: Write the failing guard test**

Create `frontend/test/no-native-dialogs.test.ts`:

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { scanSource } from "./support/native-dialog-scan";

const SRC = fileURLToPath(new URL("../src", import.meta.url));

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return walk(path);
        return /\.(astro|ts)$/.test(name) ? [path] : [];
    });
}

describe("scanSource", () => {
    it("flags every native form", () => {
        const src = [
            'alert("x");',
            'if (!confirm("y")) return;',
            'const v = prompt("z");',
            "window.alert(1); window.confirm(2); window.prompt(3);",
            `<form onsubmit="return confirm('Delete?')">`,
        ].join("\n");
        expect(scanSource(src).map((h) => h.line)).toEqual([1, 2, 3, 4, 4, 4, 5]);
    });
    it("ignores lookalikes", () => {
        const src = [
            "google.accounts.id.prompt();",
            "await confirmSheet({ title });",
            "await promptSheet({ title });",
            "obj.confirm();",
            "onConfirm();",
            "window.ftmDialogs?.confirmSheet({ title });",
        ].join("\n");
        expect(scanSource(src)).toEqual([]);
    });
    it("ignores comments but not code after them", () => {
        const src = [
            "// never alert() here",
            "/* confirm( */ prompt('after');",
            "/*",
            " * alert(",
            " */",
            'const url = "https://x.test/alert"; alert(url);',
        ].join("\n");
        expect(scanSource(src)).toEqual([
            { line: 2, match: "prompt(" },
            { line: 6, match: "alert(" },
        ]);
    });
});

describe("frontend/src", () => {
    it("has no native alert / confirm / prompt", () => {
        const hits = walk(SRC).flatMap((file) =>
            scanSource(readFileSync(file, "utf8")).map((h) => `${relative(SRC, file)}:${h.line} ${h.match}`),
        );
        expect(hits).toEqual([]);
    });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run test/no-native-dialogs.test.ts`
Expected: FAIL — cannot resolve `./support/native-dialog-scan`.

- [ ] **Step 3: Implement the scanner**

Create `frontend/test/support/native-dialog-scan.ts`:

```ts
/**
 * Finds native alert/confirm/prompt calls in source text (UX-B1 guard).
 * A call preceded by a letter, digit, `_`, `$` or `.` is not native
 * (confirmSheet, obj.confirm, google.accounts.id.prompt) — except the
 * explicit window.alert/confirm/prompt forms. Comments are skipped.
 */
const BARE = /(?<![A-Za-z0-9_.$])(?:alert|confirm|prompt)\s*\(/g;
const WINDOW = /\bwindow\.(?:alert|confirm|prompt)\s*\(/g;

export function scanSource(text: string): { line: number; match: string }[] {
    const hits: { line: number; match: string }[] = [];
    let inBlock = false;
    text.split("\n").forEach((raw, i) => {
        let line = raw;
        if (inBlock) {
            const end = line.indexOf("*/");
            if (end === -1) return;
            line = line.slice(end + 2);
            inBlock = false;
        }
        line = line.replace(/\/\*.*?\*\//g, " ");
        const open = line.indexOf("/*");
        if (open !== -1) {
            line = line.slice(0, open);
            inBlock = true;
        }
        line = line.replace(/(^|[^:])\/\/.*$/, "$1");
        const found: { index: number; match: string }[] = [];
        for (const m of line.matchAll(WINDOW)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        for (const m of line.matchAll(BARE)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        found.sort((a, b) => a.index - b.index).forEach((f) => hits.push({ line: i + 1, match: f.match }));
    });
    return hits;
}
```

(`window.alert(` is never double-counted: `BARE` skips it because `alert` there is preceded by `.`.)

- [ ] **Step 4: Run it to verify it passes** — `npx vitest run test/no-native-dialogs.test.ts` → PASS (Tasks 3–5 removed every call). If the "frontend/src" test lists a hit, it is a missed call site: migrate it with the Task 3 rules and re-run.

- [ ] **Step 5: Mutation-check** — (a) drop `.` from the lookbehind class → "ignores lookalikes" fails; (b) remove the `// …` stripping line → "ignores comments but not code after them" fails; (c) re-add one `alert("x")` to any page → the "frontend/src" test fails; restore each.

- [ ] **Step 6: Page transitions**

Append to `frontend/src/styles/global.css` (top level, outside any `@layer`):

```css
/* ---------- Page transitions (UX-B1) ----------
   Cross-document view transitions: a quick cross-fade between pages.
   Browsers without support navigate as before. The bottom nav has its own
   view-transition-name so it stays put instead of fading. */
@view-transition {
  navigation: auto;
}
::view-transition-old(root),
::view-transition-new(root) {
  animation-duration: 150ms;
}
@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) {
    animation: none !important;
  }
}
```

In `frontend/src/components/BottomNav.astro`, add `[view-transition-name:bottom-nav]` to the root `<nav>`'s class list (the one starting `fixed bottom-0 left-0 right-0`).

- [ ] **Step 7: Docs** — in `CLAUDE.md`, section "Frontend (Astro 5)", after the paragraph that starts "Pages live in `frontend/src/pages/`", add:

```markdown
**Dialogs (UX-B1):** never use native `alert` / `confirm` / `prompt` — a vitest guard (`frontend/test/no-native-dialogs.test.ts`) fails CI on them. Use `showToast` (`lib/toast.ts`) for messages, `queueToast` when a reload follows, and `confirmSheet` / `promptSheet` (`lib/dialogs.ts`) for questions; forms/links/buttons can use `data-confirm-sheet` (+ `-label`, `-body`, `-danger`) instead of a handler. `define:vars` / `is:inline` scripts can't import: they use `window.ftmDialogs`. The host is `components/ui/AppDialog.astro`, mounted once in `Layout.astro`. Page transitions are CSS-only (`@view-transition` in `global.css`).
```

- [ ] **Step 8: Verify** — `npx vitest run && npm run check && npm run build`.
- [ ] **Step 9: Commit**

```bash
git add frontend/test/support/native-dialog-scan.ts frontend/test/no-native-dialogs.test.ts frontend/src/styles/global.css frontend/src/components/BottomNav.astro CLAUDE.md
git commit -m "feat(ui): cross-fade page transitions and a guard against native dialogs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final verification (controller, after all tasks)

- Frontend: `npx vitest run`, `npm run check`, `npm run build` on the branch head.
- Whole-branch review, one fix wave, scoped re-review.
- Ship: PR → CI → merge → `./scripts/deploy-onprem.sh -y` → prod pass as the demo parent after confirming `family_id == b8312b5a-c9c0-469f-992f-8dbd412db4a7`: open and cancel a destructive confirm (budget category delete → Cancelar), open and cancel the chat edit prompt, check the sheet at phone width (bottom sheet above the nav) and desktop (centered), check the cross-fade between two pages. Only writes: create one saved budget filter via its name prompt, then delete it via its confirm. Never touch family `1998e48d-2ef0-48b6-a437-cbb730ae935c`.
