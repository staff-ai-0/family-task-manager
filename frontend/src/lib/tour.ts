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

/** Mark the tour finished: localStorage fast-path + backend per-user flag. */
async function ackTour(): Promise<void> {
    try {
        localStorage.setItem(GUARD_KEY, "1");
    } catch {
        /* private mode / storage disabled — backend flag still persists */
    }
    try {
        await fetch("/api/auth/ack-tour", { method: "POST" });
    } catch {
        /* offline — the localStorage guard prevents an immediate re-show */
    }
}

/**
 * Drive the tour. Steps whose element is not present in the DOM are dropped
 * (e.g. the checklist widget after it's dismissed) so the tour never points at
 * nothing. Fires ackTour() on finish, skip, or close (driver's onDestroyed).
 */
export function runTour(steps: TourStep[], btn: TourButtons): void {
    const present = steps.filter(
        (s) => !s.element || document.querySelector(s.element),
    );
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
        onDestroyed: () => {
            void ackTour();
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
