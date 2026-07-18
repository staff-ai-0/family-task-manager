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

/**
 * Action-driven onboarding "mission" — unlike the passive driver.js welcome
 * tour above, a mission step only advances when the REAL UI action happens
 * (a genuine DOM event), not on a timer or a "Next" click. The runner that
 * consumes this (later task) listens for `ftm:mission` CustomEvents on
 * `window` whose `detail.signal` matches `advanceOn.signal`.
 */
export interface MissionStep {
    element: string;
    title: string;
    description: string;
    side?: "top" | "bottom" | "left" | "right";
    /** The real DOM signal (CustomEvent detail.signal) that completes this step. */
    advanceOn: { signal: string };
}

export interface Mission {
    id: string;
    steps: MissionStep[];
}

export function buildMission(id: "first-task" | "first-gig", lang: string): Mission {
    if (id === "first-task") {
        return {
            id,
            steps: [
                { element: '[data-tour="task-fab"]', advanceOn: { signal: "task-modal-open" },
                  title: t(lang, "m_task_open_title"), description: t(lang, "m_task_open_body"), side: "left" },
                { element: '[data-tour="task-template-grid"]', advanceOn: { signal: "task-template-selected" },
                  title: t(lang, "m_task_tpl_title"), description: t(lang, "m_task_tpl_body"), side: "top" },
                { element: '[data-tour="task-assign"]', advanceOn: { signal: "task-assignee-selected" },
                  title: t(lang, "m_task_assign_title"), description: t(lang, "m_task_assign_body"), side: "top" },
                { element: '[data-tour="task-submit"]', advanceOn: { signal: "task-created" },
                  title: t(lang, "m_task_create_title"), description: t(lang, "m_task_create_body"), side: "top" },
            ],
        };
    }
    return {
        id,
        steps: [
            { element: '[data-tour="gig-fab"]', advanceOn: { signal: "gig-modal-open" },
              title: t(lang, "m_gig_open_title"), description: t(lang, "m_gig_open_body"), side: "left" },
            { element: '[data-tour="gig-cadence"]', advanceOn: { signal: "gig-cadence-set" },
              title: t(lang, "m_gig_cadence_title"), description: t(lang, "m_gig_cadence_body"), side: "top" },
            { element: '[data-tour="gig-submit"]', advanceOn: { signal: "gig-created" },
              title: t(lang, "m_gig_create_title"), description: t(lang, "m_gig_create_body"), side: "top" },
        ],
    };
}
