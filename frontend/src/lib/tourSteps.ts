/**
 * Server-side builder for welcome-tour steps. Used in Astro frontmatter
 * (WelcomeTour.astro, TourReplayButton.astro) to resolve i18n copy and emit a
 * plain JSON payload for the client runner (tour.ts). Keeping this server-only
 * means the i18n module is never bundled into the client.
 */
import { t } from "./i18n";
import type { TourStep, TourButtons } from "./tour";

export type TourRole = "parent" | "kid";

export interface TourData {
    role: TourRole;
    steps: TourStep[];
    btn: TourButtons;
    /** localStorage guard key — per-user so a second member on a shared device
     *  still gets their own tour. */
    guardKey: string;
}

export function buildTour(
    role: TourRole,
    lang: string,
    userId?: string,
): TourData {
    const btn: TourButtons = {
        next: t(lang, "tour_next"),
        prev: t(lang, "tour_prev"),
        done: t(lang, "tour_done"),
        progress: t(lang, "tour_progress"),
    };

    const parentSteps: TourStep[] = [
        {
            title: t(lang, "tour_p_welcome_title"),
            description: t(lang, "tour_p_welcome_body"),
        },
        {
            element: '[data-nav-key="parent"]',
            title: t(lang, "tour_p_manage_title"),
            description: t(lang, "tour_p_manage_body"),
            side: "top",
        },
        {
            element: "#onboarding-widget",
            title: t(lang, "tour_p_checklist_title"),
            description: t(lang, "tour_p_checklist_body"),
            side: "bottom",
        },
        {
            element: '[data-nav-key="gigs"]',
            title: t(lang, "tour_p_gigs_title"),
            description: t(lang, "tour_p_gigs_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="budget"]',
            title: t(lang, "tour_p_budget_title"),
            description: t(lang, "tour_p_budget_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="rewards"]',
            title: t(lang, "tour_p_rewards_title"),
            description: t(lang, "tour_p_rewards_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="chat"]',
            title: t(lang, "tour_p_chat_title"),
            description: t(lang, "tour_p_chat_body"),
            side: "top",
        },
        {
            title: t(lang, "tour_p_help_title"),
            description: t(lang, "tour_p_help_body"),
        },
    ];

    const kidSteps: TourStep[] = [
        {
            title: t(lang, "tour_k_welcome_title"),
            description: t(lang, "tour_k_welcome_body"),
        },
        {
            element: '[data-tour="today-tasks"]',
            title: t(lang, "tour_k_tasks_title"),
            description: t(lang, "tour_k_tasks_body"),
            side: "bottom",
        },
        {
            element: "[data-points-badge]",
            title: t(lang, "tour_k_points_title"),
            description: t(lang, "tour_k_points_body"),
            side: "bottom",
        },
        {
            element: '[data-nav-key="rewards"]',
            title: t(lang, "tour_k_rewards_title"),
            description: t(lang, "tour_k_rewards_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="gigs"]',
            title: t(lang, "tour_k_gigs_title"),
            description: t(lang, "tour_k_gigs_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="pet"]',
            title: t(lang, "tour_k_pet_title"),
            description: t(lang, "tour_k_pet_body"),
            side: "top",
        },
        {
            element: '[data-nav-key="chat"]',
            title: t(lang, "tour_k_chat_title"),
            description: t(lang, "tour_k_chat_body"),
            side: "top",
        },
    ];

    return {
        role,
        steps: role === "parent" ? parentSteps : kidSteps,
        btn,
        guardKey: userId ? `ftm_tour_done_${userId}` : "ftm_tour_done",
    };
}
