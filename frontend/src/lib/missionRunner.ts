/**
 * Action-driven onboarding "mission" runner. Unlike the passive driver.js
 * welcome tour (tour.ts), a mission step only advances when the REAL UI
 * action happens — a genuine `ftm:mission` CustomEvent whose detail.signal
 * matches the step's advanceOn.signal — never on a timer or a "Next" click.
 *
 * If the expected signal doesn't fire within FALLBACK_MS, the step degrades
 * to a Next button so a moved/renamed target is never a dead end. If a
 * step's target element isn't present on the current page at all (e.g. the
 * user navigated away mid-flow), the mission ends gracefully — the
 * onboarding checklist's plain deep-link remains the way forward.
 *
 * Progress persists across page navigations via sessionStorage (cleared
 * when the tab closes, unlike the welcome tour's cross-session localStorage
 * guard) so a mission started on one page resumes once its next target's
 * page loads — see the resume blocks in parent/index.astro,
 * parent/tasks.astro, parent/gigs.astro, and dashboard.astro.
 *
 * This module is the ONLY place that imports the driver.js runtime for
 * missions; callers only ever need `runMission` + the `Mission` type.
 */
import { driver } from "driver.js";
import type { Mission } from "./tourSteps";

const FALLBACK_MS = 15000;

/**
 * Run (or resume) a mission from its persisted step.
 *
 * @param mission Steps + copy already resolved server-side by buildMission.
 * @param lang Unused by the runner itself (mission.steps already carry
 *   lang-resolved copy) — kept for interface symmetry with runTour/buildTour
 *   and in case a future step needs client-side copy.
 */
export function runMission(mission: Mission, lang: string): void {
    const key = "ftm_mission_" + mission.id;
    let idx = Number(sessionStorage.getItem(key) || "0");
    if (idx >= mission.steps.length) return;

    const d = driver({ showButtons: ["close"], allowClose: true });
    let fallbackTimer: number | undefined;

    const showStep = () => {
        const step = mission.steps[idx];
        const el = document.querySelector(step.element);
        if (!el) {
            // Target absent on this page — end gracefully; checklist deep-link
            // remains the path forward.
            cleanup();
            return;
        }
        d.highlight({
            element: step.element,
            popover: { title: step.title, description: step.description, side: step.side },
        });
        clearTimeout(fallbackTimer);
        fallbackTimer = window.setTimeout(showFallbackNext, FALLBACK_MS);
    };

    const showFallbackNext = () => {
        const step = mission.steps[idx];
        d.highlight({
            element: step.element,
            popover: {
                title: step.title, description: step.description, side: step.side,
                showButtons: ["next", "close"],
                onNextClick: () => advance(),
            },
        });
    };

    const advance = () => {
        clearTimeout(fallbackTimer);
        idx += 1;
        sessionStorage.setItem(key, String(idx));
        if (idx >= mission.steps.length) {
            sessionStorage.removeItem(key);
            d.destroy();
            window.dispatchEvent(new CustomEvent("ftm:mission-complete", { detail: { id: mission.id } }));
            return;
        }
        showStep();
    };

    const onSignal = (e: Event) => {
        const detail = (e as CustomEvent).detail;
        if (detail?.signal === mission.steps[idx]?.advanceOn.signal) advance();
    };

    const cleanup = () => {
        clearTimeout(fallbackTimer);
        window.removeEventListener("ftm:mission", onSignal);
        d.destroy();
    };

    window.addEventListener("ftm:mission", onSignal);
    d.setConfig({
        onDestroyed: cleanup,
        // driver.js's imperative `.highlight()` API (as opposed to the
        // steps-array + `.drive()` flow tour.ts uses) never wires a default
        // close-button handler — without this, the × rendered during the
        // fallback-Next state would be a dead click. ESC / overlay-click
        // already route through onDestroyed regardless; this just makes the
        // visible × button work too, so the mission is skippable via the
        // control a user actually sees.
        onCloseClick: cleanup,
    });
    showStep();
}
