/**
 * Per-module tour definitions.
 *
 * The failure these guard against is silent: a missing i18n key renders the key
 * itself as the popover copy ("tour_budget_parent_intro_title" in a box on the
 * user's screen), and nothing in the build or the type checker notices. Same for
 * an id that drifts from the backend allowlist — the tour then re-runs on every
 * visit forever, because its ack is rejected with a 422 nobody sees.
 */
import { describe, expect, it } from "vitest";

import {
    MODULE_TOUR_IDS,
    MODULE_TOUR_LABEL,
    MODULE_TOUR_MODULE,
    MODULE_TOUR_PATH,
    MODULE_TOUR_ROLE,
    availableModuleTours,
    buildModuleTour,
} from "../src/lib/tourSteps";

const LANGS = ["en", "es"] as const;

describe("module tour definitions", () => {
    it("builds every tour in both languages with real copy", () => {
        for (const lang of LANGS) {
            for (const id of MODULE_TOUR_IDS) {
                const tour = buildModuleTour(id, lang, "user-1");
                expect(tour.steps.length).toBeGreaterThanOrEqual(3);
                for (const step of tour.steps) {
                    // A missing key resolves to the key itself — that is the
                    // exact bug this catches.
                    expect(step.title).not.toMatch(/^tour_/);
                    expect(step.description).not.toMatch(/^tour_/);
                    expect(step.title.length).toBeGreaterThan(0);
                    expect(step.description.length).toBeGreaterThan(0);
                }
            }
        }
    });

    it("keeps copy short enough not to cover what it points at", () => {
        for (const lang of LANGS) {
            for (const id of MODULE_TOUR_IDS) {
                for (const step of buildModuleTour(id, lang).steps) {
                    expect(step.title.length).toBeLessThanOrEqual(40);
                    expect(step.description.length).toBeLessThanOrEqual(140);
                }
            }
        }
    });

    it("opens each tour with a centered step, then points at things", () => {
        for (const id of MODULE_TOUR_IDS) {
            const steps = buildModuleTour(id, "en").steps;
            expect(steps[0].element).toBeUndefined();
            expect(steps.slice(1).every((s) => !!s.element)).toBe(true);
        }
    });

    it("scopes the local guard per user AND per tour", () => {
        // A shared family tablet: one member finishing the budget tour must not
        // silence it for the next person, or for their other tours.
        const a = buildModuleTour("budget-parent", "en", "user-1").guardKey;
        const b = buildModuleTour("budget-parent", "en", "user-2").guardKey;
        const c = buildModuleTour("chores-parent", "en", "user-1").guardKey;
        expect(new Set([a, b, c]).size).toBe(3);
    });

    it("acks to the endpoint named by its own id", () => {
        for (const id of MODULE_TOUR_IDS) {
            expect(buildModuleTour(id, "en").ackUrl).toBe(
                `/api/onboarding/tours/${id}/complete`,
            );
        }
    });

    it("has role, module, path and label metadata for every tour", () => {
        for (const id of MODULE_TOUR_IDS) {
            expect(MODULE_TOUR_ROLE[id]).toMatch(/^(parent|kid)$/);
            expect(MODULE_TOUR_PATH[id]).toMatch(/^\//);
            expect(MODULE_TOUR_LABEL[id]).toMatch(/^tour_hub_/);
            expect(id in MODULE_TOUR_MODULE).toBe(true);
        }
    });
});

describe("which tours to offer", () => {
    it("only offers a viewer their own role's tours", () => {
        expect(availableModuleTours("parent", null)).not.toContain("gigs-kid");
        expect(availableModuleTours("kid", null)).not.toContain("budget-parent");
    });

    it("hides a tour for a module the family switched off", () => {
        const parent = availableModuleTours("parent", ["gigs"]);
        expect(parent).not.toContain("budget-parent");
        expect(parent).toContain("gigs-parent");
    });

    it("keeps core tours regardless of the module registry", () => {
        // Chores and rewards are never togglable, so an empty registry must
        // not hide them.
        expect(availableModuleTours("parent", [])).toContain("chores-parent");
        expect(availableModuleTours("kid", [])).toContain("rewards-kid");
    });

    it("treats a null registry as everything enabled", () => {
        // families.enabled_modules NULL means "all modules on".
        expect(availableModuleTours("parent", null)).toContain("budget-parent");
        expect(availableModuleTours("parent", undefined)).toContain("gigs-parent");
    });
});
