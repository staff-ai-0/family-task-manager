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
    it("rejects a comma read as thousands grouping, but not a decimal comma", () => {
        for (const bad of ["1,000", "12,500"]) {
            expect(isPromptValueValid(bad, { inputType: "number" })).toBe(false);
        }
        for (const ok of ["12,50", "12,5", "0,5", "1,0005"]) {
            expect(isPromptValueValid(ok, { inputType: "number" })).toBe(true);
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
    it("is null without the attribute (the legacy data-confirm doesn't count)", () => {
        expect(confirmOptionsFromDataset({})).toBeNull();
        expect(confirmOptionsFromDataset({ confirm: "legacy admin attribute" })).toBeNull();
    });
    it("an empty data-confirm-sheet still confirms, with a generic title", () => {
        expect(confirmOptionsFromDataset({ confirmSheet: "" }, "es")).toEqual({
            title: "¿Continuar?",
            body: undefined,
            confirmLabel: undefined,
            danger: false,
        });
        expect(confirmOptionsFromDataset({ confirmSheet: "" }, "en")).toEqual({
            title: "Continue?",
            body: undefined,
            confirmLabel: undefined,
            danger: false,
        });
        expect(confirmOptionsFromDataset({ confirmSheet: "" })).toEqual({
            title: "Continue?",
            body: undefined,
            confirmLabel: undefined,
            danger: false,
        });
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
