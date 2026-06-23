/**
 * Client-side welcome-tour runner. Thin wrapper over driver.js.
 *
 * Step definitions + copy are built server-side in tourSteps.ts (so the large
 * i18n module never ships to the client) and handed here as plain JSON via a
 * <script type="application/json"> tag. This module is the ONLY place that
 * imports driver.js, so the ~5KB lib + its CSS land only on pages that render
 * a tour entry point (the role home pages + replay buttons).
 */
import { driver } from "driver.js";
import "driver.js/dist/driver.css";
import "./tour-theme.css";

export interface TourStep {
    /** CSS selector for the highlighted element; omit for a centered modal step. */
    element?: string;
    title: string;
    description: string;
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
}

export interface TourButtons {
    next: string;
    prev: string;
    done: string;
    /** driver.js progress template, e.g. "{{current}} of {{total}}". */
    progress: string;
}

const GUARD_KEY = "ftm_tour_done";

/**
 * Mark the tour finished. Runs SYNCHRONOUSLY (no await) so the localStorage
 * fast-path guard is set the instant the tour is dismissed — even if the user
 * reloads immediately after. The backend per-user flag is sent via sendBeacon
 * so the request survives the page navigation/unload that a fetch() would lose
 * (fetch falls back with keepalive when sendBeacon is unavailable).
 */
function ackTour(): void {
    try {
        localStorage.setItem(GUARD_KEY, "1");
    } catch {
        /* private mode / storage disabled — backend flag still persists */
    }
    try {
        if (typeof navigator !== "undefined" && navigator.sendBeacon) {
            navigator.sendBeacon("/api/auth/ack-tour");
        } else {
            void fetch("/api/auth/ack-tour", { method: "POST", keepalive: true });
        }
    } catch {
        /* offline — the localStorage guard prevents an immediate re-show */
    }
}

/**
 * Drive the tour. Steps whose element is not present in the DOM are dropped
 * (e.g. the checklist widget after it's dismissed) so the tour never points at
 * nothing. Acks on finish, skip, close, ESC, or overlay click via
 * onDestroyStarted, which fires the moment teardown begins (before the exit
 * animation) so the guard lands even on an immediate reload.
 */
export function runTour(steps: TourStep[], btn: TourButtons): void {
    // Keep element-less steps (centered modals); for targeted steps, require the
    // element to be present AND actually visible — a nav item collapsed at the
    // current breakpoint (display:none / zero-size) would otherwise get an empty
    // or mis-placed spotlight.
    const present = steps.filter((s) => {
        if (!s.element) return true;
        const el = document.querySelector(s.element) as HTMLElement | null;
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && el.offsetParent !== null;
    });
    if (present.length === 0) return;

    const d = driver({
        showProgress: true,
        progressText: btn.progress,
        nextBtnText: btn.next,
        prevBtnText: btn.prev,
        doneBtnText: btn.done,
        allowClose: true,
        overlayColor: "#1e293b",
        steps: present.map((s) => ({
            element: s.element,
            popover: {
                title: s.title,
                description: s.description,
                side: s.side ?? "bottom",
                align: s.align ?? "center",
            },
        })),
        // Fires on every exit path (X, done, ESC, overlay) the instant teardown
        // starts. Overriding it means we own the destroy() call.
        onDestroyStarted: () => {
            ackTour();
            d.destroy();
        },
    });
    d.drive();
}

/** Clear the local guard so a replay starts fresh, then run. */
export function replayTour(steps: TourStep[], btn: TourButtons): void {
    try {
        localStorage.removeItem(GUARD_KEY);
    } catch {
        /* ignore */
    }
    runTour(steps, btn);
}

/** True if the tour was already finished/skipped on this device. */
export function tourGuardSet(): boolean {
    try {
        return localStorage.getItem(GUARD_KEY) === "1";
    } catch {
        return false;
    }
}
