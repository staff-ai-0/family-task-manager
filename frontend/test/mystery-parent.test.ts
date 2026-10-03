import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const hub = read("../src/pages/parent/index.astro");
const strip = read("../src/components/home/DeliverStrip.astro");
const settings = read("../src/pages/parent/settings/family.astro");

describe("parent hub — surprises to deliver", () => {
    it("fetches the deliveries and renders the strip above the hub", () => {
        expect(hub).toMatch(/apiFetch<any\[\]>\("\/api\/progress\/mystery\/deliveries", \{ token \}\)/);
        expect(hub).toMatch(/<DeliverStrip items=\{deliveries\} lang=\{lang\} \/>/);
        expect(hub.indexOf("<DeliverStrip")).toBeLessThan(hub.indexOf("<ParentHub"));
    });
    it("the strip hides when empty, names the kid and the surprise, and marks delivered through the proxied route", () => {
        expect(strip).toMatch(/<section data-deliver-root[^>]*hidden=\{items\.length === 0\}/);
        expect(strip).toContain("Por entregar");
        expect(strip).toContain("To deliver");
        expect(strip).toContain("Entregada ✓");
        expect(strip).toContain("Delivered ✓");
        expect(strip).toMatch(/data-deliver-id=\{it\.id\}/);
        expect(strip).toMatch(/dayLabel\(it\.day, lang\)/);
        expect(strip).toMatch(/fetch\(`\/api\/progress\/mystery\/\$\{id\}\/delivered`, \{ method: "POST"/);
        expect(strip).toMatch(/showToast\(/);
        expect(strip).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(existsSync(path("../src/pages/api/progress/[...path].ts"))).toBe(true);
    });
});

describe("deliver strip day label", () => {
    it("says today, yesterday, or days ago, in both languages", async () => {
        const { dayLabel } = await import("../src/lib/mystery");
        const today = new Date();
        const iso = (d: Date) => d.toISOString().slice(0, 10);
        const back = (n: number) => { const d = new Date(today); d.setUTCDate(d.getUTCDate() - n); return iso(d); };
        expect(dayLabel(iso(today), "en", today)).toBe("today");
        expect(dayLabel(back(1), "es", today)).toBe("ayer");
        expect(dayLabel(back(3), "en", today)).toBe("3 days ago");
        expect(dayLabel(back(3), "es", today)).toBe("hace 3 días");
        expect(dayLabel("not-a-date", "en", today)).toBe("");
    });
});

describe("parent hub — mystery box opt-in card", () => {
    const banner = hub.match(/<div id="mystery-intro-banner"[\s\S]*?<\/div>\s*\)\}/)?.[0] ?? "";
    it("shows only to an undecided family and offers both answers", () => {
        expect(hub).toMatch(/\{family && family\.mystery_box_points == null && \(/);
        expect(banner).toContain("Nuevo: la caja sorpresa");
        expect(banner).toContain("New: the mystery box");
        expect(banner).toMatch(/id="mystery-intro-on"/);
        expect(banner).toMatch(/id="mystery-intro-off"/);
        expect(banner).toContain('href="/parent/settings/family#mystery-section"');
        expect(hub).toMatch(/JSON\.stringify\(\{ mystery_box_points: points \}\)/);
        expect(hub).toMatch(/mysteryIntroDecide\(20\)/);
        expect(hub).toMatch(/mysteryIntroDecide\(0\)/);
        expect(hub).toMatch(/if \(r\.ok\) document\.getElementById\("mystery-intro-banner"\)\?\.remove\(\);/);
    });
});

describe("family settings — mystery box section", () => {
    const section = settings.match(/<section[^>]*id="mystery-section"[\s\S]*?<\/section>/)?.[0] ?? "";
    it("sits after the teen check-in section and before modules", () => {
        expect(section).not.toBe("");
        expect(settings.indexOf('id="teen-checkin-section"')).toBeLessThan(settings.indexOf('id="mystery-section"'));
        expect(settings.indexOf('id="mystery-section"')).toBeLessThan(settings.indexOf('id="modules-section"'));
    });
    it("has the bounded points field, pre-filled, with zero meaning off", () => {
        const input = section.match(/<input[^>]*id="mystery-points"[^>]*>/s)?.[0] ?? "";
        expect(input).toMatch(/type="number"/);
        expect(input).toMatch(/min="0"/);
        expect(input).toMatch(/max="500"/);
        expect(input).toMatch(/value=\{family\?\.mystery_box_points \?\? ""\}/);
        expect(settings).toMatch(/mystery_box_points: value/);
        expect(settings).toMatch(/const raw = pointsInput\.value\.trim\(\);/);
    });
    it("renders the jar from the server and adds / removes through the proxied route", () => {
        expect(settings).toMatch(/apiFetch<any\[\]>\("\/api\/families\/surprises", \{ token \}\)/);
        expect(section).toMatch(/data-jar-list/);
        expect(section).toMatch(/data-jar-remove=\{s\.id\}/);
        expect(section).toMatch(/id="jar-title"[^>]*maxlength="60"/);
        expect(section).toMatch(/id="jar-emoji"[^>]*maxlength="4"/);
        expect(settings).toMatch(/fetch\("\/api\/families\/surprises", \{\s*method: "POST"/);
        expect(settings).toMatch(/fetch\(`\/api\/families\/surprises\/\$\{id\}`, \{ method: "DELETE"/);
        expect(settings).toMatch(/showToast\(/);
        expect(existsSync(path("../src/pages/api/families/surprises/[...path].ts"))).toBe(true);
    });
    it("explains the box in both languages", () => {
        expect(section).toContain("Cuando un hijo termina todas sus tareas del día, le aparece una caja sorpresa.");
        expect(section).toContain("When a kid finishes every chore of the day, a mystery box appears.");
    });
});
