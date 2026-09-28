import { describe, expect, it } from "vitest";

import { groupByDay, safeNotificationLink } from "../src/lib/notifications";

const TZ = "America/Mexico_City"; // UTC-6, no DST since 2022
// 2026-09-27 12:00 local = 18:00Z
const NOW = new Date("2026-09-27T18:00:00Z");

describe("groupByDay", () => {
    it("buckets by the family's local day, not UTC", () => {
        const items = [
            { id: "late-tonight", created_at: "2026-09-28T04:30:00Z" }, // 22:30 local, 27th
            { id: "yesterday", created_at: "2026-09-26T20:00:00Z" },
            { id: "old", created_at: "2026-09-20T12:00:00Z" },
        ];
        const groups = groupByDay(items, TZ, NOW);
        expect(groups.map((g) => g.bucket)).toEqual(["today", "yesterday", "earlier"]);
        expect(groups[0].items.map((i) => i.id)).toEqual(["late-tonight"]);
    });

    it("treats a just-after-midnight-UTC item as the local day before", () => {
        const items = [{ id: "a", created_at: "2026-09-27T03:00:00Z" }]; // 21:00 local on the 26th
        expect(groupByDay(items, TZ, NOW)[0].bucket).toBe("yesterday");
    });

    it("keeps input order within a bucket and drops empty buckets", () => {
        const items = [
            { id: "1", created_at: "2026-09-27T17:00:00Z" },
            { id: "2", created_at: "2026-09-27T15:00:00Z" },
        ];
        const groups = groupByDay(items, TZ, NOW);
        expect(groups).toHaveLength(1);
        expect(groups[0].items.map((i) => i.id)).toEqual(["1", "2"]);
    });

    it("files unparseable timestamps under earlier", () => {
        expect(groupByDay([{ created_at: "garbage" }], TZ, NOW)[0].bucket).toBe("earlier");
    });
});

describe("safeNotificationLink", () => {
    it("keeps same-origin paths", () => {
        expect(safeNotificationLink("/parent/approvals?x=1")).toBe("/parent/approvals?x=1");
    });
    it.each([
        ["https://evil.example/x"],
        ["//evil.example/x"],
        ["/\\evil.example"],
        ["javascript:alert(1)"],
        [""],
        [null],
        [undefined],
    ])("sends %s back to /notifications", (link) => {
        expect(safeNotificationLink(link)).toBe("/notifications");
    });
});
