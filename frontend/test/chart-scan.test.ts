import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { CHART_COPY, DAY_LABELS, DAY_NAMES, createRows, errorDetail, isUnreadable, memberChips, proposalRows, templateBody, type PostResult } from "../src/lib/chartScan";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");

const resp = {
    doc_type: "chore_chart", confidence: 0.9, chores: [
        { title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], assignee_names: ["Diego"], assigned_user_ids: ["d1"], unmatched_names: [], duplicate_of: null, description: "evenings" },
        { title: "Take out trash", points: 5, is_bonus: true, days_of_week: [], assignee_names: ["Pepe"], assigned_user_ids: [], unmatched_names: ["Pepe"], duplicate_of: "t9", description: null },
    ],
};

describe("proposalRows", () => {
    it("maps proposals, unticking duplicates", () => {
        const rows = proposalRows(resp);
        expect(rows).toHaveLength(2);
        expect(rows[0]).toMatchObject({ key: "r0", title: "Feed the dog", points: 15, isBonus: false, days: [0, 2], kidIds: ["d1"], unmatched: [], duplicate: false, description: "evenings", checked: true });
        expect(rows[1]).toMatchObject({ title: "Take out trash", isBonus: true, days: [], kidIds: [], unmatched: ["Pepe"], duplicate: true, description: null, checked: false, error: null });
    });
    it("is empty for garbage", () => {
        for (const v of [null, undefined, {}, { chores: "x" }, { chores: [null, 1] }]) expect(proposalRows(v)).toEqual([]);
    });
});

describe("isUnreadable", () => {
    it("low confidence or no rows", () => {
        expect(isUnreadable({ confidence: 0.2, chores: [{ title: "x" }] })).toBe(true);
        expect(isUnreadable({ confidence: 0.9, chores: [] })).toBe(true);
        expect(isUnreadable(resp)).toBe(false);
        expect(isUnreadable(null)).toBe(true);
    });
});

describe("templateBody", () => {
    const row = proposalRows(resp)[0];
    it("FIXED with the kids when any are selected, days as given", () => {
        expect(templateBody(row)).toEqual({
            title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], interval_days: 1,
            assignment_type: "fixed", assigned_user_ids: ["d1"], description: "evenings",
        });
    });
    it("AUTO with no kids, null days when every day, no description when empty", () => {
        expect(templateBody({ ...row, kidIds: [], days: [], description: null, title: "  Sweep  " })).toEqual({
            title: "Sweep", points: 15, is_bonus: false, days_of_week: null, interval_days: 1, assignment_type: "auto", assigned_user_ids: null, description: null,
        });
    });
    it("a Spanish parent's titles go to the Spanish column too, so nothing is 'translated' from Spanish as English", () => {
        const es = templateBody({ ...row, description: "en las tardes" }, "es");
        expect(es).toMatchObject({ title: "Feed the dog", title_es: "Feed the dog", description: "en las tardes", description_es: "en las tardes" });
        const en = templateBody(row, "en");
        expect(en).not.toHaveProperty("title_es");
        expect(en).not.toHaveProperty("description_es");
    });
    it("points are whole numbers inside the app's range", () => {
        expect(templateBody({ ...row, points: 1500 }).points).toBe(1000);
        expect(templateBody({ ...row, points: -3 }).points).toBe(0);
        expect(templateBody({ ...row, points: 7.6 }).points).toBe(8);
    });
});

describe("errorDetail", () => {
    it("takes a string detail, the first message of a validation list, or the fallback", () => {
        expect(errorDetail({ detail: "Title already exists" }, "fb")).toBe("Title already exists");
        expect(errorDetail({ detail: [{ loc: ["body", "title"], msg: "String should have at least 1 character" }] }, "fb")).toBe("String should have at least 1 character");
        expect(errorDetail({ detail: [] }, "fb")).toBe("fb");
        expect(errorDetail(null, "fb")).toBe("fb");
    });
});

describe("memberChips", () => {
    it("keeps every participating member, labels parents, drops inactive and pending ones", () => {
        const members = [
            { id: "p1", name: "Mariana", role: "parent", is_active: true, approval_status: "approved" },
            { id: "k1", name: "Sofía", role: "child", is_active: true, approval_status: "approved" },
            { id: "g1", name: "Ghost", role: "child", is_active: false, approval_status: "approved" },
            { id: "q1", name: "Pending", role: "teen", is_active: true, approval_status: "pending" },
            { id: "x1", name: "NoRole" },
        ];
        expect(memberChips(members, "es")).toEqual([{ id: "p1", label: "Mariana (papá/mamá)" }, { id: "k1", label: "Sofía" }, { id: "x1", label: "NoRole" }]);
        expect(memberChips(members, "en")[0].label).toBe("Mariana (parent)");
        expect(memberChips(null, "en")).toEqual([]);
    });
});

describe("createRows", () => {
    const base = proposalRows(resp)[0];
    const mk = (key: string, title: string) => ({ ...base, key, title, checked: true, error: null });
    it("creates the ticked rows, keeps a failed row's message, and never re-posts a created one", async () => {
        const rows = [mk("a", "A"), mk("b", "B"), { ...mk("c", "C"), checked: false }];
        const created = new Set<string>();
        const calls: string[] = [];
        const post = async (body: Record<string, unknown>): Promise<PostResult> => {
            calls.push(String(body.title));
            return body.title === "B" ? { ok: false, detail: "Title already exists" } : { ok: true, detail: null };
        };
        const first = await createRows(rows, created, post, "en");
        expect(first).toBe(1);
        expect(calls).toEqual(["A", "B"]);
        expect([...created]).toEqual(["a"]);
        expect(rows[1].error).toBe("Title already exists");
        expect(rows[0].error).toBeNull();
        const second = await createRows(rows, created, post, "en");
        expect(second).toBe(0);
        expect(calls).toEqual(["A", "B", "B"]);                 // A is never re-posted; B is retried
        expect(rows[1].error).toBe("Title already exists");
    });
    it("a thrown post is a failure with the fallback message, and a later success clears the error", async () => {
        const rows = [mk("a", "A")];
        const created = new Set<string>();
        let fail = true;
        const post = async (): Promise<PostResult> => { if (fail) throw new Error("offline"); return { ok: true, detail: null }; };
        expect(await createRows(rows, created, post, "es")).toBe(0);
        expect(rows[0].error).toBe(CHART_COPY.createFailed.es);
        fail = false;
        expect(await createRows(rows, created, post, "es")).toBe(1);
        expect(rows[0].error).toBeNull();
    });
    it("reports progress", async () => {
        const rows = [mk("a", "A"), mk("b", "B")];
        const seen: string[] = [];
        await createRows(rows, new Set(), async () => ({ ok: true, detail: null }), "en", (i, n) => seen.push(`${i}/${n}`));
        expect(seen).toEqual(["1/2", "2/2"]);
    });
});

describe("copy", () => {
    it("has both languages and seven day labels", () => {
        expect(DAY_LABELS.es).toHaveLength(7);
        expect(DAY_LABELS.en).toHaveLength(7);
        expect(DAY_NAMES.es[0]).toBe("lunes");
        expect(DAY_NAMES.en[6]).toBe("Sunday");
        for (const key of ["title", "pick", "scanning", "found", "anyone", "exists", "unmatched", "create", "creating", "done", "unreadable", "failed", "createFailed", "tooBig", "note"] as const) {
            expect(CHART_COPY[key].es.length).toBeGreaterThan(2);
            expect(CHART_COPY[key].en.length).toBeGreaterThan(2);
        }
    });
});

describe("page", () => {
    const page = read("../src/pages/parent/tasks/scan.astro");
    it("is parent-only, paid-gated with the upgrade prompt, sky tone", () => {
        expect(page).toMatch(/if \(user\.role !== "parent"\) return Astro\.redirect\("\/dashboard"\);/);
        expect(page).toMatch(/const aiLocked = await isFreePlan\(token\);/);
        expect(page).toContain("<UpgradePrompt");
        expect(page).toMatch(/tone="sky"/);
    });
    it("scans through the proxied route and creates each ticked row through the ordinary chore API", () => {
        expect(page).toMatch(/fetch\("\/api\/task-templates\/scan-chart"/);
        expect(page).toMatch(/fetch\("\/api\/task-templates\/", \{\s*method: "POST"/);
        expect(page).toMatch(/createRows\(/);               // the shared loop builds the bodies
        expect(page).toMatch(/proposalRows\(/);
        expect(page).toMatch(/isUnreadable\(/);
        expect(existsSync(path("../src/pages/api/task-templates/[...path].ts"))).toBe(true);
    });
    it("creates through the shared loop, paints a row's stored error, and shows progress", () => {
        expect(page).toMatch(/await createRows\(rows, created, post, lang, \(i, n\) =>/);
        expect(page).toMatch(/if \(row\.error\) \{[\s\S]*?err\.textContent = row\.error;/);
        expect(page).toMatch(/fill\(c\.creating\[lang\], \{ i, n \}\)/);
        expect(page).toMatch(/errorDetail\(/);
    });
    it("shows every participating member (parents labelled) and the note, editable", () => {
        expect(page).toMatch(/const chips = memberChips\(members, lang\);/);
        expect(page).toMatch(/data-chips=\{JSON\.stringify\(chips\)\}/);
        expect(page).toMatch(/row\.description = /);
        expect(page).toContain("c.note[lang]");
        expect(page).toMatch(/r\.status === 413 \? c\.tooBig\[lang\]/);
        expect(page).toMatch(/DAY_NAMES\[lang\]\[d\]/);
    });
    it("uses no native dialog, no emoji in a heading 1, and a hidden attribute for states", () => {
        expect(page).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(page).not.toMatch(/<h1[^>]*>[^<]*[\u{1F300}-\u{1FAFF}]/u);
        expect(page).toMatch(/id="scanning" hidden/);
        expect(page).toMatch(/id="results" hidden/);
    });
});
