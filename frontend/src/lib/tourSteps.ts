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

// ─── Per-module tours ────────────────────────────────────────────────────
// The welcome tour above is one flat pass over the bottom nav: it says a module
// exists, never how it works. These are the per-module walkthroughs, each run
// once on first visit to its own page and replayable from the hub on /help.
//
// Ids are shared with the backend allowlist (TOUR_IDS in
// backend/app/api/routes/onboarding.py) and with users.completed_tours. Adding
// one here without adding it there makes its tour re-run forever.

export type ModuleTourId =
    | "budget-parent"
    | "gigs-parent"
    | "gigs-kid"
    | "chores-parent"
    | "rewards-kid";

export const MODULE_TOUR_IDS: readonly ModuleTourId[] = [
    "budget-parent",
    "gigs-parent",
    "gigs-kid",
    "chores-parent",
    "rewards-kid",
];

/** Which module each tour belongs to, for families.enabled_modules filtering. */
export const MODULE_TOUR_MODULE: Record<ModuleTourId, string | null> = {
    "budget-parent": "budget",
    "gigs-parent": "gigs",
    "gigs-kid": "gigs",
    // Chores and rewards are core surfaces — never togglable, so never filtered.
    "chores-parent": null,
    "rewards-kid": null,
};

/** Who each tour is written for. */
export const MODULE_TOUR_ROLE: Record<ModuleTourId, TourRole> = {
    "budget-parent": "parent",
    "gigs-parent": "parent",
    "gigs-kid": "kid",
    "chores-parent": "parent",
    "rewards-kid": "kid",
};

/** Where a tour runs — the hub links here with ?tour=<id>. */
export const MODULE_TOUR_PATH: Record<ModuleTourId, string> = {
    "budget-parent": "/budget",
    "gigs-parent": "/parent/gigs",
    "gigs-kid": "/gigs",
    "chores-parent": "/parent/tasks",
    "rewards-kid": "/rewards",
};

/** Hub card label key for each tour. */
export const MODULE_TOUR_LABEL: Record<ModuleTourId, string> = {
    "budget-parent": "tour_hub_budget",
    "gigs-parent": "tour_hub_gigs_parent",
    "gigs-kid": "tour_hub_gigs_kid",
    "chores-parent": "tour_hub_chores",
    "rewards-kid": "tour_hub_rewards_kid",
};

/**
 * Step skeletons: [i18n key prefix, selector].
 *
 * A null selector is a centered modal step — used for the opening step, which
 * frames what the module is for before pointing at anything. Selectors are
 * resolved at run time and missing ones are dropped by runTour(), so a step
 * whose target is not on screen at this breakpoint is skipped rather than
 * spotlighting empty space.
 */
const MODULE_TOUR_STEPS: Record<
    ModuleTourId,
    ReadonlyArray<readonly [string, string | null, ("top" | "bottom" | "left" | "right")?]>
> = {
    "budget-parent": [
        ["tour_budget_parent_intro", null],
        // Accounts, categories and payees all live behind the drawer, so the
        // step points at the way in rather than at a panel that is off-screen.
        ["tour_budget_parent_accounts", '[data-tour="budget-menu"]', "bottom"],
        ["tour_budget_parent_categories", '[data-tour="budget-categories"]', "top"],
        ["tour_budget_parent_assign", '[data-tour="budget-to-assign"]', "bottom"],
        ["tour_budget_parent_scan", "#fab-button", "top"],
        ["tour_budget_parent_reports", '[data-tour="budget-tab-reports"]', "bottom"],
    ],
    "gigs-parent": [
        ["tour_gigs_parent_intro", null],
        ["tour_gigs_parent_post", '[data-tour="gig-fab"]', "left"],
        ["tour_gigs_parent_claim", '[data-tour="gig-board"]', "top"],
        ["tour_gigs_parent_approve", '[data-tour="gig-approvals"]', "top"],
        ["tour_gigs_parent_bank", '[data-nav-key="bank"]', "top"],
    ],
    "gigs-kid": [
        ["tour_gigs_kid_intro", null],
        ["tour_gigs_kid_board", '[data-tour="gig-board"]', "bottom"],
        // Proof and payout both happen on /gigs/my-gigs, so both steps point
        // at the way there rather than at a claimed card that may not exist yet.
        ["tour_gigs_kid_proof", '[data-tour="gig-mine"]', "bottom"],
        ["tour_gigs_kid_paid", '[data-tour="gig-mine"]', "bottom"],
    ],
    "chores-parent": [
        ["tour_chores_parent_intro", null],
        ["tour_chores_parent_templates", '[data-tour="task-template-grid"]', "bottom"],
        ["tour_chores_parent_assign", '[data-tour="task-fab"]', "left"],
        ["tour_chores_parent_review", '[data-nav-key="approvals"]', "top"],
        ["tour_chores_parent_rewards", '[data-nav-key="rewards"]', "top"],
    ],
    "rewards-kid": [
        ["tour_rewards_kid_intro", null],
        ["tour_rewards_kid_catalog", '[data-tour="rewards-catalog"]', "bottom"],
        ["tour_rewards_kid_redeem", '[data-tour="rewards-points"]', "bottom"],
    ],
};

export interface ModuleTourData extends TourData {
    id: ModuleTourId;
    /** Endpoint the runner acks to when the tour ends. */
    ackUrl: string;
}

export function buildModuleTour(
    id: ModuleTourId,
    lang: string,
    userId?: string,
): ModuleTourData {
    const btn: TourButtons = {
        next: t(lang, "tour_next"),
        prev: t(lang, "tour_prev"),
        done: t(lang, "tour_done"),
        progress: t(lang, "tour_progress"),
    };

    const steps: TourStep[] = MODULE_TOUR_STEPS[id].map(([key, element, side]) => ({
        ...(element ? { element } : {}),
        title: t(lang, `${key}_title`),
        description: t(lang, `${key}_body`),
        ...(side ? { side } : {}),
    }));

    return {
        id,
        role: MODULE_TOUR_ROLE[id],
        steps,
        btn,
        // Per-user AND per-tour, so one member finishing the budget tour on a
        // shared tablet does not silence it for everyone else.
        guardKey: userId ? `ftm_tour_${id}_${userId}` : `ftm_tour_${id}`,
        ackUrl: `/api/onboarding/tours/${id}/complete`,
    };
}

/** Tours worth offering to this viewer: right role, module switched on. */
export function availableModuleTours(
    role: TourRole,
    enabledModules: unknown,
): ModuleTourId[] {
    return MODULE_TOUR_IDS.filter((id) => {
        if (MODULE_TOUR_ROLE[id] !== role) return false;
        const mod = MODULE_TOUR_MODULE[id];
        if (!mod) return true; // core surface, never togglable
        // NULL enabled_modules means "all modules on" (families.enabled_modules).
        if (!Array.isArray(enabledModules)) return true;
        return enabledModules.includes(mod);
    });
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
