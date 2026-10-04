import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
    BANDS, PRIORITIES, REWARD_STYLES, SETUP_COPY, TOGGLABLE_MODULES, bandForBirthdate, canAdvanceKids, choreBody,
    createAll, draftRequest, gigBody, jarvisPrefill, kidRowsFromMembers, modulesBodyWithoutGigs, registerBody,
    reviewRows, rewardBody, type Poster, type Review, type WizardState,
} from "../src/lib/setupWizard";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");

const members = [
    { id: "s1", name: "Sofía", role: "child", is_active: true, approval_status: "approved" },
    { id: "d1", name: "Diego", role: "teen", is_active: true, approval_status: "approved" },
    { id: "m1", name: "Mariana", role: "parent", is_active: true, approval_status: "approved" },
    { id: "p1", name: "Pepe", role: "child", is_active: true, approval_status: "pending" },
    { id: "x1", name: "Gone", role: "child", is_active: false, approval_status: "approved" },
];

const state = (over: Partial<WizardState> = {}): WizardState => ({
    kids: [
        { key: "k0", name: "Sofía", band: "6-8", memberId: "s1", locked: true, included: true },
        { key: "k1", name: "Nuevo", band: "13+", memberId: null, locked: false, included: true },
        { key: "k2", name: "Skip", band: "3-5", memberId: null, locked: false, included: false },
    ],
    priorities: ["school"], note: "", rewardStyles: ["treats"], wantsGigs: true, ...over,
});

const draft = {
    source: "ai", ai_available: true, ai_failed: false,
    kids: [
        { name: "Sofía", age_band: "6-8", member_id: "s1", chores: [
            { title: "Feed the pet", points: 5, days: [0, 2], is_bonus: false, description: null, duplicate_of: "Feed the pet" },
            { title: "Homework", points: 10, days: [], is_bonus: true, description: "after lunch", duplicate_of: null },
        ] },
        { name: "Nuevo", age_band: "13+", member_id: null, chores: [{ title: "Cook", points: 20, days: [], is_bonus: false, description: null, duplicate_of: null }] },
    ],
    rewards: [{ title: "Pizza", points_cost: 40, category: "treats", description: null, duplicate_of: null }],
    gigs: [{ title: "Wash car", points: 50, difficulty: 2, category: "chores", duplicate_of: null }],
};

describe("constants", () => {
    it("bands, priorities and styles match the backend", () => {
        expect(BANDS).toEqual(["3-5", "6-8", "9-12", "13+"]);
        expect(PRIORITIES).toEqual(["routine", "school", "home", "kitchen", "pets", "self_care"]);
        expect(REWARD_STYLES).toEqual(["screen_time", "treats", "activities", "privileges", "toys"]);
        const py = read("../../backend/app/core/modules.py");
        for (const m of TOGGLABLE_MODULES) expect(py).toContain(`"${m}"`);
        expect(TOGGLABLE_MODULES).toHaveLength(7);
    });
    it("every copy key has both languages", () => {
        for (const [k, v] of Object.entries(SETUP_COPY)) expect(Object.keys(v), k).toEqual(["es", "en"]);
    });
});

describe("kids step", () => {
    it("kidRowsFromMembers keeps active approved kids only, band by role", () => {
        const rows = kidRowsFromMembers(members);
        expect(rows.map((r) => [r.name, r.band, r.memberId, r.locked])).toEqual([["Sofía", "6-8", "s1", true], ["Diego", "13+", "d1", true]]);
        expect(kidRowsFromMembers(null)).toEqual([]);
    });
    it("bandForBirthdate boundaries", () => {
        const today = new Date(2026, 9, 4);
        expect(bandForBirthdate("2021-10-05", today)).toBe("3-5");
        expect(bandForBirthdate("2020-10-04", today)).toBe("6-8");
        expect(bandForBirthdate("2017-10-04", today)).toBe("9-12");
        expect(bandForBirthdate("2013-10-04", today)).toBe("13+");
    });
    it("canAdvanceKids needs one included row with a name and a band", () => {
        expect(canAdvanceKids(state())).toBe(true);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: " ", band: "6-8", memberId: null, locked: false, included: true }] }))).toBe(false);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: "A", band: null, memberId: null, locked: false, included: true }] }))).toBe(false);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: "A", band: "6-8", memberId: null, locked: false, included: false }] }))).toBe(false);
    });
    it("draftRequest sends included rows only, trimmed", () => {
        const body = draftRequest(state({ note: "  dog  " }), "es");
        expect(body).toEqual({
            kids: [{ name: "Sofía", age_band: "6-8", member_id: "s1" }, { name: "Nuevo", age_band: "13+", member_id: null }],
            priorities: ["school"], note: "dog", reward_styles: ["treats"], wants_gigs: true, lang: "es",
        });
        expect(draftRequest(state({ note: "   " }), "en").note).toBeNull();
    });
});

describe("review", () => {
    it("reviewRows unticks duplicates and starts idle", () => {
        const r = reviewRows(draft);
        expect(r.kids).toHaveLength(2);
        expect(r.kids[0].chores[0]).toMatchObject({ title: "Feed the pet", included: false, duplicateOf: "Feed the pet", status: "idle", error: null, days: [0, 2] });
        expect(r.kids[0].chores[1]).toMatchObject({ included: true, isBonus: true, description: "after lunch" });
        expect(r.kids[1]).toMatchObject({ name: "Nuevo", memberId: null });
        expect(r.rewards[0]).toMatchObject({ title: "Pizza", pointsCost: 40, category: "treats", included: true });
        expect(r.gigs[0]).toMatchObject({ title: "Wash car", points: 50, difficulty: 2, included: true });
        expect(reviewRows(null)).toEqual({ kids: [], rewards: [], gigs: [] });
    });
    it("choreBody is FIXED to the kid when bound, AUTO otherwise; Spanish fills the es columns", () => {
        const row = reviewRows(draft).kids[0].chores[1];
        expect(choreBody(row, "s1", "en")).toEqual({
            title: "Homework", points: 10, is_bonus: true, days_of_week: null, interval_days: 1,
            assignment_type: "fixed", assigned_user_ids: ["s1"], description: "after lunch",
        });
        const auto = choreBody(reviewRows(draft).kids[0].chores[0], null, "es");
        expect(auto).toMatchObject({ assignment_type: "auto", assigned_user_ids: null, days_of_week: [0, 2], title_es: "Feed the pet", description_es: null });
    });
    it("rewardBody, gigBody, registerBody", () => {
        expect(rewardBody(reviewRows(draft).rewards[0])).toEqual({ title: "Pizza", points_cost: 40, category: "treats", description: null });
        expect(gigBody(reviewRows(draft).gigs[0])).toEqual({ title: "Wash car", points: 50, difficulty: 2, category: "chores" });
        expect(registerBody({ name: "Nuevo", band: "13+" }, "n@x.com", "secret123")).toEqual({ name: "Nuevo", email: "n@x.com", password: "secret123", role: "teen" });
        expect(registerBody({ name: "Peque", band: "3-5" }, "p@x.com", "secret123").role).toBe("child");
    });
    it("modulesBodyWithoutGigs keeps every other module", () => {
        expect(modulesBodyWithoutGigs(null)).toEqual({ enabled_modules: ["meals", "shopping", "calendar", "pet", "chat", "budget"] });
        expect(modulesBodyWithoutGigs(["budget", "gigs", "chat"])).toEqual({ enabled_modules: ["budget", "chat"] });
    });
});

describe("createAll", () => {
    const review = (): Review => reviewRows(draft);
    it("posts ticked rows in order and reports counts", async () => {
        const calls: string[] = [];
        const post: Poster = async (path) => { calls.push(path); return { ok: true, detail: null }; };
        const r = review();
        const counts = await createAll(r, "en", post);
        expect(calls).toEqual(["/api/task-templates/", "/api/task-templates/", "/api/rewards/", "/api/gigs/offerings"]);
        expect(counts).toEqual({ chores: 2, rewards: 1, gigs: 1 });
        expect(r.kids[0].chores[1].status).toBe("done");
        expect(r.kids[0].chores[0].status).toBe("idle"); // unticked duplicate untouched
    });
    it("createAll retries only failed rows", async () => {
        let n = 0;
        const post: Poster = async (path) => { n += 1; return path === "/api/rewards/" && n <= 3 ? { ok: false, detail: "nope" } : { ok: true, detail: null }; };
        const r = review();
        const first = await createAll(r, "en", post);
        expect(first).toEqual({ chores: 2, rewards: 0, gigs: 1 });
        expect(r.rewards[0]).toMatchObject({ status: "error", error: "nope" });
        const seen: string[] = [];
        const second = await createAll(r, "en", async (path) => { seen.push(path); return { ok: true, detail: null }; });
        expect(seen).toEqual(["/api/rewards/"]);
        expect(second).toEqual({ chores: 0, rewards: 1, gigs: 0 });
        expect(r.rewards[0]).toMatchObject({ status: "done", error: null });
    });
    it("marks chores created without a bound kid as createdAuto", async () => {
        const r = review();
        expect(r.kids[1].chores[0].createdAuto).toBe(false);
        await createAll(r, "en", async () => ({ ok: true, detail: null }));
        expect(r.kids[0].chores[1].createdAuto).toBe(false);
        expect(r.kids[1].chores[0].createdAuto).toBe(true);
    });
    it("a second run after everything was created posts nothing", async () => {
        const r = review();
        await createAll(r, "en", async () => ({ ok: true, detail: null }));
        const seen: string[] = [];
        const again = await createAll(r, "en", async (path) => { seen.push(path); return { ok: true, detail: null }; });
        expect(seen).toEqual([]);
        expect(again).toEqual({ chores: 0, rewards: 0, gigs: 0 });
    });
    it("a thrown post becomes the generic error and progress is reported", async () => {
        const r = review();
        const steps: Array<[number, number]> = [];
        await createAll(r, "es", async () => { throw new Error("net"); }, (i, t) => steps.push([i, t]));
        expect(steps).toEqual([[1, 4], [2, 4], [3, 4], [4, 4]]);
        expect(r.gigs[0].error).toBe(SETUP_COPY.createFailed.es);
    });
});

describe("jarvisPrefill", () => {
    it("names the kids, priorities and counts, within 2000 chars", () => {
        const s = jarvisPrefill(state(), { chores: 8, rewards: 4, gigs: 2 }, "en");
        for (const part of ["Sofía (6-8)", "Nuevo (13+)", "school", "8 chores", "4 rewards", "2 gigs"]) expect(s).toContain(part);
        expect(s).not.toContain("Skip");
        const long = state({ note: "x".repeat(5000) });
        expect(jarvisPrefill(long, { chores: 1, rewards: 1, gigs: 0 }, "es").length).toBeLessThanOrEqual(2000);
    });
});
