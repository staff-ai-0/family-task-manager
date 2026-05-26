# Task Template Creation UX — Design Spec

**Date:** 2026-05-26  
**Status:** Approved  
**Scope:** Frontend-only — no backend changes, no migrations

---

## Problem

The current task template creation form (`/parent/tasks`) is painful:

1. **14 fields visible at once** — bilingual title/description, points, effort level, frequency, assignment type, member selection, allowed roles, bonus toggle, gig mode, blocks-rewards toggle, late penalty section.
2. **No preset library** — parents type "Wash Dishes" and every other common chore from scratch every time.
3. **Bilingual entry blocks** — EN + ES fields required before saving; the auto-translate endpoint exists but is only accessible after creation via the edit page.

---

## Solution

Replace the inline create form with a **two-step modal** triggered by a "+" button:

- **Step 1** — Grid of 20 preset chore cards (+ Custom option). Parent taps one to continue.
- **Step 2** — Mini-form with 5 essential fields pre-filled from the preset. Advanced options collapsed under `<details>`. Save triggers auto-translate silently in the background.

---

## User Flow

```
Parent on /parent/tasks
  → taps "+" button
  → modal opens: Step 1 (preset grid)
  → taps a preset (or Custom)
  → modal advances: Step 2 (mini-form, pre-filled)
  → adjusts fields if needed
  → taps "Create Task"
  → modal closes immediately, success toast shown
  → template list refreshes via fetch (no full reload)
  → background: POST translate → PUT update adds title_es silently
```

---

## Step 1 — Preset Grid

- 3-column grid of preset cards (emoji + EN name + effort + frequency)
- Client-side search/filter input at top
- "Custom" card (✏️) skips to Step 2 with blank title, effort_level=1, interval_days=1
- Scrollable if viewport is short

## Step 2 — Mini-form (5 required fields)

| Field | Control | Default from preset |
|-------|---------|-------------------|
| Task name | Text input (editable) | Preset EN title |
| Difficulty | Chip group: Easy / Medium / Hard | Preset effort_level |
| How often | Chip group: Daily / Every 3d / Weekly | Preset interval_days |
| Assign to | Chip group: Auto / Fixed / Rotate (Fixed/Rotate reveal member checkboxes) | Auto |
| Bonus task? | Toggle | Off |

**Advanced section** (collapsed `<details>` at bottom):
- Description textarea
- Allowed roles checkboxes (parent / teen / child)
- Gig mode select
- Blocks rewards toggle
- Late penalty (existing `<details>` pattern)

No Spanish fields shown to parent. Auto-translate handles it after creation.

---

## Preset Library

Hardcoded in `frontend/src/lib/task-presets.ts`. No DB, no migration.

```typescript
export interface TaskPreset {
  emoji: string;
  title: string;       // EN
  effort_level: 1 | 2 | 3;
  interval_days: 1 | 3 | 7;
}
```

### 20 Presets

| Emoji | Title (EN) | Effort | Freq |
|-------|-----------|--------|------|
| 🍽️ | Wash Dishes | 1 | daily |
| 🗑️ | Take Out Trash | 1 | weekly |
| 🧹 | Sweep Floor | 1 | daily |
| 🛏️ | Make Bed | 1 | daily |
| 🧴 | Wipe Kitchen Counter | 1 | daily |
| 🌿 | Water Plants | 1 | 3 days |
| 🐕 | Walk Dog | 1 | daily |
| 🐾 | Feed Pets | 1 | daily |
| 🧺 | Do Laundry | 2 | weekly |
| 🧽 | Clean Bathroom | 2 | weekly |
| 🏠 | Vacuum Living Room | 2 | weekly |
| 🍳 | Help Cook Dinner | 2 | daily |
| 📚 | Study / Homework | 2 | daily |
| 🛒 | Help Grocery Shopping | 2 | weekly |
| 🪟 | Clean Windows | 2 | weekly |
| 🚗 | Wash Car | 3 | weekly |
| 🌿 | Mow Lawn | 3 | weekly |
| 📦 | Organize Closet | 3 | weekly |
| 🧹 | Clean Garage | 3 | weekly |
| ✏️ | Custom (blank form) | — | — |

---

## Auto-translate Flow

Three sequential API calls, all after modal closes:

```
POST /api/task-templates/           → returns { id }
POST /api/task-templates/{id}/translate  { source_lang: "en", target_lang: "es" }
                                    → returns { title, description }
PUT  /api/task-templates/{id}       { title_es, description_es }
```

If translate or PUT fails silently: template still exists with EN only. "ES missing" badge visible in list, parent can translate manually via edit page. No error shown to parent unless the initial POST fails.

---

## Component Architecture

### New files

| File | Purpose |
|------|---------|
| `frontend/src/lib/task-presets.ts` | 20 preset objects (TS constant) |
| `frontend/src/components/TaskCreateModal.astro` | Two-step modal component |

### Modified files

| File | Change |
|------|--------|
| `frontend/src/pages/parent/tasks.astro` | Replace inline create form with `<TaskCreateModal>` + trigger button; shift create action to client-side fetch |

### No changes to

- `backend/` — all 3 API endpoints already exist
- `frontend/src/pages/parent/tasks/[id]/edit.astro` — full form unchanged
- DB schema — no migration needed

---

## Client-side Behaviour

- Modal opens/closes without page navigation (no Astro routing change)
- After successful create: template list section re-fetches `GET /api/task-templates/` and re-renders in place
- Chip groups (effort / frequency / assign) are single-select; clicking a chip deselects others
- "Fixed" or "Rotate" assign chips reveal member checkboxes (same logic as existing `toggleUserSelection`)
- Back button in Step 2 returns to Step 1 (preset grid stays visible, selection highlighted)
- Search in Step 1 filters preset cards client-side (case-insensitive match on title)

---

## Out of Scope

- Budget transaction UX (separate spec/plan)
- Editing presets / family-customizable preset library (hardcoded for now)
- Bulk task creation
- Drag-to-reorder templates

---

## Success Criteria

- Parent creates a common chore in ≤ 3 taps + 1 button click
- No full page reload on create
- Spanish translation appears on template within ~5 seconds of creation (background)
- Advanced options (gig mode, blocks rewards, late penalty) still accessible via collapse
- Zero backend changes required
