# Task Template UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 14-field inline task creation form with a two-step preset-picker modal that lets parents create common chores in ≤ 3 taps.

**Architecture:** Hardcoded preset library in `task-presets.ts`. New `TaskCreateModal.astro` component handles the two-step flow (preset grid → mini-form) with client-side fetch for API calls. `tasks.astro` drops the SSR create form and uses the modal instead. Auto-translate (EN→ES) fires silently in the background after creation.

**Tech Stack:** Astro 5 · TypeScript · Tailwind CSS v4 · existing `/api/task-templates/` endpoints (no backend changes)

---

## File Map

| Action | File |
|--------|------|
| Create | `frontend/src/lib/task-presets.ts` |
| Create | `frontend/src/pages/api/task-templates/[...path].ts` |
| Create | `frontend/src/components/TaskCreateModal.astro` |
| Modify | `frontend/src/pages/parent/tasks.astro` |

---

## Task 1: API proxy for task-templates

The modal uses client-side `fetch("/api/task-templates/…")`. The browser can't reach the backend directly (different port / Docker network). An Astro wildcard proxy is needed — identical pattern to the existing `api/budget/[...path].ts`.

**Files:**
- Create: `frontend/src/pages/api/task-templates/[...path].ts`

- [ ] **Step 1: Create the proxy file**

```typescript
// frontend/src/pages/api/task-templates/[...path].ts
import type { APIRoute } from "astro";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8000";

async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}/api/task-templates/${path}${url.search}`;

    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    if (!forwardHeaders.has("Authorization")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            forwardHeaders.set("Authorization", `Bearer ${decodeURIComponent(match[1])}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    async function doFetch(targetUrl: string): Promise<Response> {
        const backendRes = await fetch(targetUrl, {
            method: request.method,
            headers: forwardHeaders,
            body,
            redirect: "manual",
        });

        if (backendRes.status >= 300 && backendRes.status < 400) {
            const location = backendRes.headers.get("location");
            if (location) {
                const redirectUrl = location.startsWith("http") ? location : `${BACKEND_URL}${location}`;
                return doFetch(redirectUrl);
            }
        }

        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            if (key.toLowerCase() === "transfer-encoding") continue;
            responseHeaders.set(key, value);
        }
        return new Response(backendRes.body, {
            status: backendRes.status,
            statusText: backendRes.statusText,
            headers: responseHeaders,
        });
    }

    try {
        return await doFetch(backendUrl);
    } catch (e: any) {
        console.error(`[api/task-templates proxy] ${e?.message ?? e}`);
        return new Response(
            JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
            { status: 502, headers: { "Content-Type": "application/json" } }
        );
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const PUT: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
```

- [ ] **Step 2: Commit**

```bash
git add "frontend/src/pages/api/task-templates/[...path].ts"
git commit -m "feat(tasks): add Astro proxy for /api/task-templates/* (enables client-side fetch)"
```

---

## Task 2: Preset library constant


**Files:**
- Create: `frontend/src/lib/task-presets.ts`

- [ ] **Step 1: Create the file**

```typescript
// frontend/src/lib/task-presets.ts

export interface TaskPreset {
  emoji: string;
  title: string;
  effort_level: 1 | 2 | 3;
  interval_days: 1 | 3 | 7;
}

export const TASK_PRESETS: TaskPreset[] = [
  { emoji: "🍽️", title: "Wash Dishes",          effort_level: 1, interval_days: 1 },
  { emoji: "🗑️", title: "Take Out Trash",        effort_level: 1, interval_days: 7 },
  { emoji: "🧹", title: "Sweep Floor",            effort_level: 1, interval_days: 1 },
  { emoji: "🛏️", title: "Make Bed",               effort_level: 1, interval_days: 1 },
  { emoji: "🧴", title: "Wipe Kitchen Counter",   effort_level: 1, interval_days: 1 },
  { emoji: "🌿", title: "Water Plants",            effort_level: 1, interval_days: 3 },
  { emoji: "🐕", title: "Walk Dog",               effort_level: 1, interval_days: 1 },
  { emoji: "🐾", title: "Feed Pets",              effort_level: 1, interval_days: 1 },
  { emoji: "🧺", title: "Do Laundry",             effort_level: 2, interval_days: 7 },
  { emoji: "🧽", title: "Clean Bathroom",          effort_level: 2, interval_days: 7 },
  { emoji: "🏠", title: "Vacuum Living Room",      effort_level: 2, interval_days: 7 },
  { emoji: "🍳", title: "Help Cook Dinner",        effort_level: 2, interval_days: 1 },
  { emoji: "📚", title: "Study / Homework",        effort_level: 2, interval_days: 1 },
  { emoji: "🛒", title: "Help Grocery Shopping",   effort_level: 2, interval_days: 7 },
  { emoji: "🪟", title: "Clean Windows",           effort_level: 2, interval_days: 7 },
  { emoji: "🚗", title: "Wash Car",               effort_level: 3, interval_days: 7 },
  { emoji: "🌿", title: "Mow Lawn",               effort_level: 3, interval_days: 7 },
  { emoji: "📦", title: "Organize Closet",         effort_level: 3, interval_days: 7 },
  { emoji: "🧹", title: "Clean Garage",            effort_level: 3, interval_days: 7 },
];
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/task-presets.ts
git commit -m "feat(tasks): add hardcoded task preset library (20 chores)"
```

---

## Task 3: TaskCreateModal component

**Files:**
- Create: `frontend/src/components/TaskCreateModal.astro`

This component owns the modal HTML (backdrop + dialog) and all client-side JS. The trigger button lives in `tasks.astro`, not here. The component receives `token`, `lang`, and `memberList` as props. The preset grid is SSR-rendered; clicking a card reads its `data-preset` JSON attribute to populate Step 2.

- [ ] **Step 1: Create the component**

```astro
---
// frontend/src/components/TaskCreateModal.astro
import { TASK_PRESETS } from "@lib/task-presets";

interface Props {
    lang: "en" | "es";
    token: string;
    memberList: Array<{ id: string; name: string; role: string }>;
}

const { lang, token, memberList } = Astro.props;
const es = lang === "es";
---

<!-- Backdrop -->
<div
    id="tcm-backdrop"
    class="fixed inset-0 bg-black/50 z-40 hidden opacity-0 transition-opacity duration-300"
></div>

<!-- Modal -->
<div
    id="tcm-modal"
    role="dialog"
    aria-modal="true"
    class="fixed inset-0 z-50 hidden items-center justify-center p-4"
>
    <div class="bg-brand-cream w-full max-w-sm rounded-[var(--radius-card)] shadow-[var(--shadow-pop)] border-2 border-brand-ink max-h-[90vh] flex flex-col">

        <!-- Header -->
        <div class="px-5 pt-5 pb-3 border-b border-brand-ink/10 flex items-center justify-between flex-shrink-0">
            <h2 class="font-display text-lg font-extrabold text-brand-ink">
                {es ? "Nueva tarea" : "New Task"}
            </h2>
            <button id="tcm-close" class="text-brand-ink-soft hover:text-brand-ink p-1">
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>

        <!-- Step 1: Preset Grid -->
        <div id="tcm-step-1" class="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            <input
                id="tcm-search"
                type="text"
                placeholder={es ? "Buscar tareas..." : "Search chores..."}
                class="w-full px-3 py-2 rounded-lg border border-brand-ink/20 text-sm focus:ring-2 focus:ring-brand-sky-deep outline-none"
            />
            <div id="tcm-preset-grid" class="grid grid-cols-3 gap-2">
                {TASK_PRESETS.map((p) => (
                    <button
                        class="tcm-preset-card flex flex-col items-center p-2.5 bg-brand-mint/10 hover:bg-brand-mint/25 border-2 border-transparent hover:border-brand-mint rounded-xl transition-all text-center"
                        data-preset={JSON.stringify(p)}
                    >
                        <span class="text-2xl leading-none">{p.emoji}</span>
                        <span class="text-[10px] font-bold text-brand-ink mt-1 leading-tight line-clamp-2">{p.title}</span>
                        <span class="text-[9px] text-brand-ink-soft mt-0.5">
                            {p.effort_level === 1 ? (es ? "Fácil" : "Easy") : p.effort_level === 2 ? (es ? "Medio" : "Med") : (es ? "Difícil" : "Hard")}
                            {" · "}
                            {p.interval_days === 1 ? (es ? "diario" : "daily") : p.interval_days === 3 ? "3d" : (es ? "semanal" : "wkly")}
                        </span>
                    </button>
                ))}
                <!-- Custom option -->
                <button
                    class="tcm-preset-card flex flex-col items-center p-2.5 bg-brand-sky/10 hover:bg-brand-sky/25 border-2 border-transparent hover:border-brand-sky-deep rounded-xl transition-all text-center"
                    data-preset={JSON.stringify({ emoji: "✏️", title: "", effort_level: 1, interval_days: 1 })}
                >
                    <span class="text-2xl leading-none">✏️</span>
                    <span class="text-[10px] font-bold text-brand-sky-deep mt-1 leading-tight">{es ? "Personalizada" : "Custom"}</span>
                    <span class="text-[9px] text-brand-ink-soft mt-0.5">{es ? "en blanco" : "blank form"}</span>
                </button>
            </div>
        </div>

        <!-- Step 2: Mini-form -->
        <div id="tcm-step-2" class="hidden flex-1 overflow-y-auto px-5 py-4 space-y-4">

            <!-- Task name -->
            <div>
                <label class="text-xs font-semibold text-brand-ink-soft uppercase tracking-wider mb-1 block">
                    {es ? "Nombre" : "Task Name"}
                </label>
                <input
                    id="tcm-name"
                    type="text"
                    required
                    class="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:ring-2 focus:ring-brand-sky-deep outline-none"
                />
            </div>

            <!-- Effort chips -->
            <div>
                <label class="text-xs font-semibold text-brand-ink-soft uppercase tracking-wider mb-2 block">
                    {es ? "Dificultad" : "Difficulty"}
                </label>
                <div class="flex gap-2" data-chipgroup="effort">
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="1">
                        {es ? "Fácil ×1" : "Easy ×1"}
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="2">
                        {es ? "Medio ×1.5" : "Med ×1.5"}
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="3">
                        {es ? "Difícil ×2" : "Hard ×2"}
                    </button>
                </div>
            </div>

            <!-- Frequency chips -->
            <div>
                <label class="text-xs font-semibold text-brand-ink-soft uppercase tracking-wider mb-2 block">
                    {es ? "Frecuencia" : "How Often"}
                </label>
                <div class="flex gap-2" data-chipgroup="interval">
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="1">
                        {es ? "Diario" : "Daily"}
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="3">
                        {es ? "Cada 3d" : "Every 3d"}
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="7">
                        {es ? "Semanal" : "Weekly"}
                    </button>
                </div>
            </div>

            <!-- Assignment chips -->
            <div>
                <label class="text-xs font-semibold text-brand-ink-soft uppercase tracking-wider mb-2 block">
                    {es ? "Asignar a" : "Assign To"}
                </label>
                <div class="flex gap-2" data-chipgroup="assignment">
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="auto">
                        Auto
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="fixed">
                        Fixed
                    </button>
                    <button class="tcm-chip flex-1 py-2 text-xs font-bold rounded-full border-2" data-value="rotate">
                        Rotate
                    </button>
                </div>
                <div id="tcm-members" class="hidden mt-2 space-y-1 p-3 bg-brand-cream-deep rounded-lg border border-brand-ink/10">
                    {memberList.map((m) => (
                        <label class="flex items-center gap-2 cursor-pointer hover:bg-brand-cream px-2 py-1 rounded text-sm">
                            <input type="checkbox" class="tcm-member-cb w-4 h-4 rounded border-brand-ink/20" value={m.id} />
                            <span class="text-brand-ink">{m.name}</span>
                            <span class="text-xs text-brand-ink-soft ml-auto">{m.role.toLowerCase()}</span>
                        </label>
                    ))}
                </div>
            </div>

            <!-- Bonus toggle -->
            <label class="flex items-center gap-3 p-3 bg-brand-sun/10 border border-brand-sun/30 rounded-xl cursor-pointer">
                <input id="tcm-bonus" type="checkbox" class="sr-only peer" />
                <div class="w-9 h-5 bg-brand-cream-deep rounded-full peer peer-checked:bg-brand-sun-deep transition-colors relative after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full flex-shrink-0"></div>
                <span class="text-sm font-semibold text-brand-ink">⭐ {es ? "Tarea bonus (otorga puntos)" : "Bonus task (earns points)"}</span>
            </label>

            <!-- Advanced -->
            <details class="bg-brand-cream-deep/50 rounded-lg border border-brand-ink/10">
                <summary class="px-3 py-2.5 text-sm font-semibold text-brand-ink cursor-pointer list-none flex items-center gap-2">
                    <svg class="h-4 w-4 text-brand-ink-soft" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    {es ? "Opciones avanzadas" : "Advanced options"}
                </summary>
                <div class="px-3 pb-3 pt-2 space-y-3">
                    <div>
                        <label class="text-xs font-medium text-brand-ink-soft mb-1 block">{es ? "Descripción" : "Description"}</label>
                        <textarea id="tcm-desc" rows={2} class="w-full px-3 py-2 rounded-lg border border-brand-ink/20 text-sm outline-none resize-none focus:ring-2 focus:ring-brand-sky-deep"></textarea>
                    </div>
                    <div>
                        <label class="text-xs font-medium text-brand-ink-soft mb-1 block">{es ? "Roles permitidos" : "Allowed roles"}</label>
                        <div class="flex gap-4 flex-wrap p-2 bg-brand-cream rounded-lg">
                            {["parent","teen","child"].map(role => (
                                <label class="flex items-center gap-1.5 text-sm cursor-pointer capitalize">
                                    <input type="checkbox" class="tcm-role-cb w-4 h-4 rounded border-brand-ink/20" value={role} />
                                    {role}
                                </label>
                            ))}
                        </div>
                    </div>
                    <div>
                        <label class="text-xs font-medium text-brand-ink-soft mb-1 block">{es ? "Modo gig" : "Gig mode"}</label>
                        <select id="tcm-gig" class="w-full px-3 py-2 rounded-lg border border-brand-ink/20 text-sm bg-brand-cream outline-none">
                            <option value="claim">{es ? "Reservar (default)" : "Claim (default)"}</option>
                            <option value="competition">🏆 {es ? "Competencia" : "Competition"}</option>
                            <option value="rotation">🔄 {es ? "Rotación" : "Rotation"}</option>
                            <option value="collaboration">🤝 {es ? "Colaboración" : "Collaboration"}</option>
                        </select>
                    </div>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input id="tcm-blocks-rewards" type="checkbox" class="w-4 h-4 rounded border-brand-ink/20" />
                        <span class="text-sm text-brand-ink">🔒 {es ? "Bloquea recompensas" : "Blocks rewards"}</span>
                    </label>
                </div>
            </details>

            <!-- Error -->
            <div id="tcm-error" class="hidden text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2"></div>

        </div>

        <!-- Footer -->
        <div class="px-5 py-4 border-t border-brand-ink/10 flex gap-3 flex-shrink-0">
            <button id="tcm-back" class="hidden flex-1 py-2.5 border-2 border-brand-ink/20 rounded-full text-sm font-bold text-brand-ink-soft hover:bg-brand-cream-deep transition-colors">
                ← {es ? "Atrás" : "Back"}
            </button>
            <button id="tcm-submit" class="hidden flex-1 py-2.5 bg-brand-sky-deep hover:bg-brand-ink text-white font-bold text-sm rounded-full transition-colors shadow-[var(--shadow-card)] disabled:opacity-60">
                ✓ {es ? "Crear tarea" : "Create Task"}
            </button>
        </div>

    </div>
</div>

<script define:vars={{ token }}>
(function initTaskCreateModal() {

    // --- Elements ---
    const backdrop  = document.getElementById("tcm-backdrop");
    const modal     = document.getElementById("tcm-modal");
    const closeBtn  = document.getElementById("tcm-close");
    const step1     = document.getElementById("tcm-step-1");
    const step2     = document.getElementById("tcm-step-2");
    const backBtn   = document.getElementById("tcm-back");
    const submitBtn = document.getElementById("tcm-submit");
    const searchEl  = document.getElementById("tcm-search");
    const nameEl    = document.getElementById("tcm-name");
    const bonusEl   = document.getElementById("tcm-bonus");
    const descEl    = document.getElementById("tcm-desc");
    const gigEl     = document.getElementById("tcm-gig");
    const blocksEl  = document.getElementById("tcm-blocks-rewards");
    const membersEl = document.getElementById("tcm-members");
    const errorEl   = document.getElementById("tcm-error");
    const triggerBtn = document.getElementById("tcm-trigger");

    if (!modal || !backdrop) return;

    // --- Chip state ---
    const chipState = { effort: "1", interval: "1", assignment: "auto" };

    function activateChip(group, value) {
        chipState[group] = value;
        const container = document.querySelector(`[data-chipgroup="${group}"]`);
        if (!container) return;
        container.querySelectorAll(".tcm-chip").forEach(btn => {
            const active = btn.dataset.value === value;
            btn.classList.toggle("bg-brand-sky-deep",  active);
            btn.classList.toggle("text-white",          active);
            btn.classList.toggle("border-brand-sky-deep", active);
            btn.classList.toggle("bg-brand-cream-deep", !active);
            btn.classList.toggle("text-brand-ink-soft", !active);
            btn.classList.toggle("border-transparent",  !active);
        });
        if (group === "assignment") {
            membersEl?.classList.toggle("hidden", value === "auto");
        }
    }

    function initChips() {
        document.querySelectorAll("[data-chipgroup]").forEach(group => {
            const field = group.dataset.chipgroup;
            group.querySelectorAll(".tcm-chip").forEach(btn => {
                btn.addEventListener("click", () => activateChip(field, btn.dataset.value));
            });
        });
    }

    // --- Open / Close ---
    function openModal() {
        backdrop.classList.remove("hidden");
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        requestAnimationFrame(() => backdrop.classList.replace("opacity-0", "opacity-100"));
        showStep(1);
        searchEl?.focus();
    }

    function closeModal() {
        backdrop.classList.replace("opacity-100", "opacity-0");
        setTimeout(() => {
            backdrop.classList.add("hidden");
            modal.classList.add("hidden");
            modal.classList.remove("flex");
            resetForm();
        }, 250);
    }

    function resetForm() {
        if (nameEl)  nameEl.value = "";
        if (descEl)  descEl.value = "";
        if (gigEl)   gigEl.value = "claim";
        if (bonusEl)    bonusEl.checked = false;
        if (blocksEl)   blocksEl.checked = false;
        if (errorEl) { errorEl.textContent = ""; errorEl.classList.add("hidden"); }
        if (searchEl)   searchEl.value = "";
        document.querySelectorAll(".tcm-member-cb").forEach(cb => cb.checked = false);
        document.querySelectorAll(".tcm-role-cb").forEach(cb => cb.checked = false);
        filterPresets("");
        activateChip("effort", "1");
        activateChip("interval", "1");
        activateChip("assignment", "auto");
    }

    function showStep(n) {
        step1?.classList.toggle("hidden", n !== 1);
        step2?.classList.toggle("hidden", n !== 2);
        backBtn?.classList.toggle("hidden", n !== 2);
        submitBtn?.classList.toggle("hidden", n !== 2);
    }

    // --- Preset search filter ---
    function filterPresets(query) {
        const q = query.toLowerCase();
        document.querySelectorAll(".tcm-preset-card").forEach(card => {
            const title = card.querySelector("span:nth-child(2)")?.textContent?.toLowerCase() || "";
            card.classList.toggle("hidden", q !== "" && !title.includes(q));
        });
    }

    // --- Preset card → Step 2 ---
    document.querySelectorAll(".tcm-preset-card").forEach(card => {
        card.addEventListener("click", () => {
            const preset = JSON.parse(card.dataset.preset || "{}");
            if (nameEl) nameEl.value = preset.title || "";
            activateChip("effort",   String(preset.effort_level   ?? 1));
            activateChip("interval", String(preset.interval_days  ?? 1));
            activateChip("assignment", "auto");
            showStep(2);
            setTimeout(() => nameEl?.focus(), 100);
        });
    });

    // --- Create ---
    async function handleCreate() {
        if (!nameEl?.value.trim()) {
            showError("Task name is required.");
            return;
        }
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.textContent = "...";
        hideError();

        const assignedUserIds = [...document.querySelectorAll(".tcm-member-cb:checked")].map(cb => cb.value);
        const allowedRoles    = [...document.querySelectorAll(".tcm-role-cb:checked")].map(cb => cb.value);

        const payload = {
            title:            nameEl.value.trim(),
            description:      descEl?.value.trim() || null,
            title_es:         null,
            description_es:   null,
            points:           bonusEl?.checked ? 10 : 0,
            effort_level:     Number(chipState.effort),
            interval_days:    Number(chipState.interval),
            is_bonus:         bonusEl?.checked ?? false,
            blocks_rewards:   blocksEl?.checked ?? false,
            gig_mode:         gigEl?.value || "claim",
            collaboration_min_count: 2,
            auto_late_penalty: false,
            late_restriction_type: null,
            late_severity: null,
            late_duration_days: 1,
            assignment_type:  chipState.assignment,
            assigned_user_ids: assignedUserIds.length > 0 ? assignedUserIds : null,
            allowed_roles:    allowedRoles.length > 0 ? allowedRoles : null,
        };

        try {
            const res = await fetch("/api/task-templates/", {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Error ${res.status}`);
            }
            const created = await res.json();
            closeModal();
            refreshTemplateList();
            autoTranslate(created.id, payload.title, payload.description);
        } catch (err) {
            showError(err.message || "Failed to create task.");
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    }

    // --- Auto-translate (silent background) ---
    async function autoTranslate(templateId, title, description) {
        try {
            const tRes = await fetch(`/api/task-templates/${templateId}/translate`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ source_lang: "en", target_lang: "es" }),
            });
            if (!tRes.ok) return;
            const translated = await tRes.json();
            await fetch(`/api/task-templates/${templateId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({
                    title_es: translated.title || null,
                    description_es: translated.description || null,
                }),
            });
            // Re-refresh list now that ES is available
            refreshTemplateList();
        } catch (_) { /* silent — "ES missing" badge handles this gracefully */ }
    }

    // --- Refresh template list without page reload ---
    async function refreshTemplateList() {
        const container = document.getElementById("template-list-container");
        if (!container) return;
        try {
            const res = await fetch("/api/task-templates/", {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) return;
            const templates = await res.json();
            container.innerHTML = templates.length === 0
                ? `<p class="text-brand-ink-soft text-sm text-center py-6">No templates yet.</p>`
                : templates.map(tmpl => renderTemplateCard(tmpl)).join("");
        } catch (_) { /* leave stale list on network error */ }
    }

    function renderTemplateCard(tmpl) {
        const freqLabel = tmpl.interval_days === 1 ? "Daily" : tmpl.interval_days === 7 ? "Weekly" : `Every ${tmpl.interval_days}d`;
        const effortLabel = tmpl.effort_level === 3 ? "×2" : tmpl.effort_level === 2 ? "×1.5" : "×1";
        const esMissing = !tmpl.title_es
            ? `<span class="inline-block ml-2 text-[10px] font-normal px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 border border-orange-200">ES missing</span>`
            : "";
        const inactiveBadge = !tmpl.is_active
            ? `<span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-red-100 text-red-600">Inactive</span>`
            : "";
        const bonusBadge = `<span class="text-xs font-semibold px-2 py-0.5 rounded-full ${tmpl.is_bonus ? "bg-brand-sun/20 text-brand-sun-deep" : "bg-brand-sky/15 text-brand-sky-deep"}">${tmpl.is_bonus ? "Bonus" : "Regular"}</span>`;
        const freqBadge  = `<span class="text-xs font-medium px-2 py-0.5 rounded-full bg-brand-cream-deep text-brand-ink-soft">${freqLabel}</span>`;
        const effectivePts = Math.round((tmpl.points || 0) * (tmpl.effort_level === 3 ? 2 : tmpl.effort_level === 2 ? 1.5 : 1));
        return `
<div class="bg-brand-cream rounded-2xl p-4 shadow-[var(--shadow-card)] border ${tmpl.is_active ? "border-brand-ink/10" : "border-brand-ink/10 opacity-60"}">
  <div class="flex items-start justify-between gap-3">
    <div class="flex-1">
      <div class="flex items-center gap-2 flex-wrap mb-1">
        <h3 class="font-bold text-brand-ink text-sm">${tmpl.title}${esMissing}</h3>
        ${bonusBadge} ${freqBadge} ${inactiveBadge}
      </div>
      ${tmpl.description ? `<p class="text-xs text-brand-ink-soft line-clamp-1">${tmpl.description}</p>` : ""}
      <p class="text-xs text-brand-sun-deep font-semibold mt-1">+${effectivePts} pts <span class="text-brand-ink-soft font-normal">${tmpl.effort_level > 1 ? `(${tmpl.points} ${effortLabel})` : ""}</span></p>
    </div>
    <div class="flex gap-1.5 flex-shrink-0">
      <form method="POST"><input type="hidden" name="action" value="toggle"><input type="hidden" name="template_id" value="${tmpl.id}">
        <button type="submit" class="h-8 w-8 rounded-lg flex items-center justify-center transition-colors ${tmpl.is_active ? "bg-brand-mint/20 text-brand-mint-deep hover:bg-brand-mint" : "bg-brand-cream-deep text-brand-ink-soft hover:bg-brand-mint/20"}">
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${tmpl.is_active ? "M5 13l4 4L19 7" : "M12 4v16m8-8H4"}"/></svg>
        </button>
      </form>
      <a href="/parent/tasks/${tmpl.id}/edit" class="h-8 w-8 rounded-lg bg-brand-cream-deep hover:text-brand-sky-deep text-brand-ink-soft flex items-center justify-center transition-colors">
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
      </a>
      <form method="POST" onsubmit="return confirm('Delete this template?')"><input type="hidden" name="action" value="delete"><input type="hidden" name="template_id" value="${tmpl.id}">
        <button type="submit" class="h-8 w-8 rounded-lg bg-brand-cream-deep hover:bg-red-100 text-brand-ink-soft hover:text-red-500 flex items-center justify-center transition-colors">
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
        </button>
      </form>
    </div>
  </div>
</div>`;
    }

    // --- Error helpers ---
    function showError(msg) {
        if (errorEl) { errorEl.textContent = msg; errorEl.classList.remove("hidden"); }
    }
    function hideError() {
        if (errorEl) { errorEl.textContent = ""; errorEl.classList.add("hidden"); }
    }

    // --- Wire up events ---
    triggerBtn?.addEventListener("click", openModal);
    closeBtn?.addEventListener("click", closeModal);
    backdrop?.addEventListener("click", closeModal);
    backBtn?.addEventListener("click", () => showStep(1));
    submitBtn?.addEventListener("click", handleCreate);
    searchEl?.addEventListener("input", e => filterPresets(e.target.value));
    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && !backdrop.classList.contains("hidden")) closeModal();
    });

    initChips();
    document.addEventListener("astro:after-swap", initTaskCreateModal);
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TaskCreateModal.astro
git commit -m "feat(tasks): add two-step task creation modal with preset library"
```

---

## Task 4: Wire modal into tasks.astro

**Files:**
- Modify: `frontend/src/pages/parent/tasks.astro`

Three changes: (1) import and render `<TaskCreateModal>`, (2) add FAB trigger button `id="tcm-trigger"` to the header, (3) wrap the template list `<div>` in `id="template-list-container"` so the modal can re-render it, (4) remove the SSR `<!-- Create Template Form -->` section.

- [ ] **Step 1: Add import at top of frontmatter**

In `frontend/src/pages/parent/tasks.astro`, find the existing imports block (lines 1-6) and add:

```astro
import TaskCreateModal from "../../components/TaskCreateModal.astro";
```

- [ ] **Step 2: Add "+" button to header**

Find the header `<h1>` block (around line 140-141):

```astro
<h1 class="font-display text-2xl font-extrabold text-brand-ink">{t(lang, "pt_title")}</h1>
```

Replace with:

```astro
<div class="flex items-center justify-between gap-3">
    <h1 class="font-display text-2xl font-extrabold text-brand-ink">{t(lang, "pt_title")}</h1>
    <button
        id="tcm-trigger"
        class="press h-10 w-10 rounded-full bg-brand-sky-deep border-2 border-brand-ink shadow-[var(--shadow-card)] text-white flex items-center justify-center text-xl font-bold flex-shrink-0"
        aria-label={lang === "es" ? "Nueva tarea" : "New task"}
    >+</button>
</div>
```

- [ ] **Step 3: Remove the SSR create form section**

Delete the entire `<!-- Create Template Form -->` section from tasks.astro (lines 203–423 in the original — the `<section>` block starting with `bg-brand-cream rounded-2xl` containing the `<form method="POST">` with `action="create"`). Also remove the `create` action handler in the frontmatter (lines 25–59).

- [ ] **Step 4: Wrap template list in refresh target**

Find the template list section (the `<section>` with `<h2>…pt_all_templates…</h2>`):

```astro
<section>
    <h2 class="font-bold text-brand-ink mb-3 px-1">{t(lang, "pt_all_templates")}</h2>
    <div class="space-y-3">
```

Replace inner `<div class="space-y-3">` with:

```astro
    <div id="template-list-container" class="space-y-3">
```

- [ ] **Step 5: Render TaskCreateModal component**

Add just before the closing `</Layout>` tag (after the shuffle preview modal `</div>` and the `<script>` block):

```astro
<TaskCreateModal lang={lang} token={token} memberList={memberList} />
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/parent/tasks.astro
git commit -m "feat(tasks): wire TaskCreateModal into tasks page, remove old SSR form"
```

---

## Task 5: Smoke test

- [ ] **Step 1: Start dev environment**

```bash
docker compose up -d
```

Verify frontend at http://localhost:3003 and backend at http://localhost:8003/docs.

- [ ] **Step 2: Test preset flow**

1. Log in as `mom@demo.com / password123` (PARENT role)
2. Navigate to http://localhost:3003/parent/tasks
3. Click the `+` button in the header
4. Verify modal opens with preset grid
5. Type "dish" in search → only "Wash Dishes" visible
6. Click "Wash Dishes" preset → Step 2 appears with title pre-filled and Easy + Daily chips active
7. Click "Create Task"
8. Verify modal closes and new template appears in list without page reload
9. Wait ~5 seconds → verify "ES missing" badge disappears (auto-translate completed)

- [ ] **Step 3: Test Custom flow**

1. Click `+` → click ✏️ Custom card
2. Step 2 appears with blank title, Easy + Daily defaults
3. Type a title → Create Task → template appears in list

- [ ] **Step 4: Test advanced options**

1. Create a task → Step 2 → expand "Advanced options"
2. Verify description, allowed roles, gig mode, blocks rewards all present and functional

- [ ] **Step 5: Verify edit page unchanged**

Navigate to any template's edit link → confirm full edit form still shows all fields including bilingual.

- [ ] **Step 6: Verify toggle and delete still work**

Toggle a template active/inactive, delete one. Both use SSR form POST and should still work after the list refresh re-renders them.
