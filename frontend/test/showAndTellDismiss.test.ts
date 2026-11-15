import { describe, expect, it } from "vitest";
import { cleanSuggestions, dismiss, dismissKey, isDismissed } from "../src/lib/showAndTell";

describe("card dismissal (per calendar month)", () => {
    const mem = () => {
        const m = new Map<string, string>();
        return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
    };
    it("key includes year and month", () => {
        expect(dismissKey(new Date(2026, 10, 13))).toBe("ftm-show-tell-dismissed-2026-11");
    });
    it("dismissed this month, back next month", () => {
        const s = mem();
        expect(isDismissed(s, new Date(2026, 10, 13))).toBe(false);
        dismiss(s, new Date(2026, 10, 13));
        expect(isDismissed(s, new Date(2026, 10, 28))).toBe(true);
        expect(isDismissed(s, new Date(2026, 11, 1))).toBe(false);
    });
    it("never throws when storage is blocked or missing", () => {
        const bad = {
            getItem: () => {
                throw new Error("denied");
            },
            setItem: () => {
                throw new Error("denied");
            },
        };
        expect(isDismissed(bad)).toBe(false);
        expect(() => dismiss(bad)).not.toThrow();
        expect(isDismissed(null)).toBe(false);
        expect(() => dismiss(undefined)).not.toThrow();
    });
});

describe("suggestion cap matches the backend (160 chars)", () => {
    it("truncates at 160", () => {
        expect(cleanSuggestions(["x".repeat(300)])[0]).toHaveLength(160);
    });
});
