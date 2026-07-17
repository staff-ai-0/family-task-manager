/**
 * Action-driven onboarding "mission" runner. Unlike the passive driver.js
 * welcome tour (tour.ts), a mission step only advances when the REAL UI
 * action happens — a genuine `ftm:mission` CustomEvent whose detail.signal
 * matches the step's advanceOn.signal — never on a timer or a "Next" click.
 *
 * If the expected signal doesn't fire within FALLBACK_MS, the step degrades
 * to a Next button so a moved/renamed target is never a dead end. If a
 * step's target element isn't present on the current page at all (e.g. the
 * user navigated away mid-flow) — or is present but not actually visible,
 * e.g. a CSS-hidden modal like TaskCreateModal.astro before it's opened —
 * the mission ends gracefully — the onboarding checklist's plain deep-link
 * remains the way forward.
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
 * True if `el` is present AND actually rendered — mirrors tour.ts's
 * present-steps visibility filter. A DOM-present-but-CSS-hidden target (e.g.
 * a modal that's always rendered and toggled via a "hidden" class, like
 * TaskCreateModal.astro before it's opened) must not be highlighted; it
 * should degrade exactly like a genuinely absent element.
 */
function isVisible(el: HTMLElement | null): boolean {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && el.offsetParent !== null;
}

/**
 * Reads the persisted step index. Guards against storage being unavailable
 * (private mode / disabled) and against a corrupted value — a non-numeric
 * string parses to NaN, which would otherwise sail past the caller's
 * `idx >= mission.steps.length` check (NaN comparisons are always false)
 * and later crash showStep() on `mission.steps[NaN].element`. Both NaN and
 * negative values fall back to 0 (start of mission); a valid-but-too-large
 * index is left as-is — the caller's length check treats that as "mission
 * already complete", which is the correct, non-throwing outcome for it.
 */
function readMissionIndex(key: string): number {
    let raw: string | null = null;
    try {
        raw = sessionStorage.getItem(key);
    } catch {
        /* private mode / storage disabled — start from the beginning */
    }
    const idx = Number(raw);
    return Number.isInteger(idx) && idx >= 0 ? idx : 0;
}

/** Best-effort persist — a mission still runs for the current page load even
 * if storage is unavailable; it just won't resume after a navigation. */
function writeMissionIndex(key: string, idx: number): void {
    try {
        sessionStorage.setItem(key, String(idx));
    } catch {
        /* private mode / storage disabled */
    }
}

/** Best-effort clear — see writeMissionIndex. */
function clearMissionIndex(key: string): void {
    try {
        sessionStorage.removeItem(key);
    } catch {
        /* private mode / storage disabled */
    }
}

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
    let idx = readMissionIndex(key);
    if (idx >= mission.steps.length) return;

    const d = driver({ showButtons: ["close"], allowClose: true });
    let fallbackTimer: number | undefined;
    let destroyed = false;

    const showStep = () => {
        const step = mission.steps[idx];
        const el = document.querySelector(step.element) as HTMLElement | null;
        if (!isVisible(el)) {
            // Target absent, or present but not actually visible (e.g. a
            // CSS-hidden modal) — end gracefully; checklist deep-link
            // remains the path forward.
            cleanup();
            return;
        }
        d.highlight({
            element: step.element,
            popover: {
                title: step.title, description: step.description, side: step.side,
                // Without an explicit showButtons here, driver.js's .highlight()
                // silently injects showButtons: [] into any popover that doesn't
                // set its own — which hides the close control for the whole
                // FALLBACK_MS window (only showFallbackNext's popover sets its
                // own showButtons). Setting it here keeps the mission skippable
                // from the very first render of each step.
                showButtons: ["close"],
            },
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
        writeMissionIndex(key, idx);
        if (idx >= mission.steps.length) {
            clearMissionIndex(key);
            // Route through cleanup() rather than a bare d.destroy() so the
            // "ftm:mission" listener removal is deterministic instead of
            // depending on driver.js's onDestroyed callback (gated by an
            // internal ~400ms animation timer) to eventually run it.
            // cleanup() is idempotent, so onDestroyed firing afterward
            // (it's wired to cleanup too) is a safe no-op, not a double destroy.
            cleanup();
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
        // Idempotent: advance()'s completion branch and driver.js's own
        // onDestroyed (also wired to cleanup, below) can both reach this —
        // the guard makes the second call a no-op instead of a double destroy.
        if (destroyed) return;
        destroyed = true;
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
