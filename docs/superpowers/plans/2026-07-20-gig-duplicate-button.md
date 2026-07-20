# Gig Duplicate Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Duplicate" button to each active gig card on `/parent/gigs` that opens the existing create/edit modal prefilled from the source gig, so a parent can reuse a gig's fields instead of retyping them.

**Architecture:** Frontend-only change to one Astro page. The duplicate button reuses the page's existing `fillModalFromDataset()` helper and `#gig-modal`/`#gig-form`, but clears the hidden `gig_id` field so the existing submit handler's already-conditional POST/PUT branch creates a new offering instead of updating the source one.

**Tech Stack:** Astro 5 (SSR page, hoisted `<script>` island, TypeScript-checked inline), Tailwind CSS v4.

## Global Constraints

- Frontend-only — no backend/service/model/migration changes (reuses `POST /api/gigs/offerings` as-is).
- Scope is the active-offerings list only — no archived-gigs view.
- No new automated test — verify manually in the browser per this project's CLAUDE.md UI-change rule.
- Spec: `docs/superpowers/specs/2026-07-20-gig-duplicate-button-design.md`

---

### Task 1: Duplicate button (HTML + click handler) on `/parent/gigs`

**Files:**
- Modify: `frontend/src/pages/parent/gigs.astro:235-255` (card button row)
- Modify: `frontend/src/pages/parent/gigs.astro:492-497` (script: button-listener wiring, right after the existing `.edit-gig-btn` listener)

**Interfaces:**
- Consumes (already defined earlier in this same file, untouched): `fillModalFromDataset(b: HTMLElement): void` (script line ~481), `openModal(title: string): void` (script line ~457), `editIdInput: HTMLInputElement` (script line ~452), `termOne: string` (script line ~455), `lang: string` (script line ~448).
- Produces: `.duplicate-gig-btn` elements + their click handler. Nothing else in the codebase depends on this — no downstream tasks.

- [ ] **Step 1: Add the Duplicate button to the card markup**

In `frontend/src/pages/parent/gigs.astro`, the active-offerings card currently renders (lines 235-255):

```astro
                            <div class="flex gap-2 mt-4">
                                <button
                                    class="edit-gig-btn flex-1 py-2 text-sm font-semibold text-violet-700 bg-violet-100 rounded-xl hover:bg-violet-200 transition-colors"
                                    data-id={o.id}
                                    data-title={o.title}
                                    data-description={o.description ?? ""}
                                    data-points={o.points}
                                    data-difficulty={o.difficulty ?? 1}
                                    data-category={o.category ?? "other"}
                                    data-allow-multiple={o.allow_multiple ? "1" : "0"}
                                    data-payout-cadence={o.payout_cadence ?? "immediate"}
                                >
                                    {lang === "es" ? "Editar" : "Edit"}
                                </button>
                                <button
                                    class="archive-gig-btn flex-1 py-2 text-sm font-semibold text-brand-ink-soft bg-brand-cream-deep rounded-xl hover:bg-red-100 hover:text-red-700 transition-colors"
                                    data-id={o.id}
                                >
                                    {lang === "es" ? "Archivar" : "Archive"}
                                </button>
                            </div>
```

Replace it with (inserts a `.duplicate-gig-btn` between Edit and Archive, same `flex-1` row):

```astro
                            <div class="flex gap-2 mt-4">
                                <button
                                    class="edit-gig-btn flex-1 py-2 text-sm font-semibold text-violet-700 bg-violet-100 rounded-xl hover:bg-violet-200 transition-colors"
                                    data-id={o.id}
                                    data-title={o.title}
                                    data-description={o.description ?? ""}
                                    data-points={o.points}
                                    data-difficulty={o.difficulty ?? 1}
                                    data-category={o.category ?? "other"}
                                    data-allow-multiple={o.allow_multiple ? "1" : "0"}
                                    data-payout-cadence={o.payout_cadence ?? "immediate"}
                                >
                                    {lang === "es" ? "Editar" : "Edit"}
                                </button>
                                <button
                                    class="duplicate-gig-btn flex-1 py-2 text-sm font-semibold text-indigo-700 bg-indigo-100 rounded-xl hover:bg-indigo-200 transition-colors"
                                    data-title={o.title}
                                    data-description={o.description ?? ""}
                                    data-points={o.points}
                                    data-difficulty={o.difficulty ?? 1}
                                    data-category={o.category ?? "other"}
                                    data-allow-multiple={o.allow_multiple ? "1" : "0"}
                                    data-payout-cadence={o.payout_cadence ?? "immediate"}
                                >
                                    {lang === "es" ? "Duplicar" : "Duplicate"}
                                </button>
                                <button
                                    class="archive-gig-btn flex-1 py-2 text-sm font-semibold text-brand-ink-soft bg-brand-cream-deep rounded-xl hover:bg-red-100 hover:text-red-700 transition-colors"
                                    data-id={o.id}
                                >
                                    {lang === "es" ? "Archivar" : "Archive"}
                                </button>
                            </div>
```

Note: the new button has no `data-id` — that's deliberate (see Step 3, which must explicitly clear `editIdInput.value` for this reason).

- [ ] **Step 2: Verify Astro/TS still type-checks**

Run: `cd frontend && npm run check`
Expected: no new errors (the added button is plain markup with the same `data-*` attribute shapes already used by `.edit-gig-btn`).

- [ ] **Step 3: Add the click handler**

In the same file's `<script>` block, immediately after the existing `.edit-gig-btn` listener (lines 492-497):

```ts
document.querySelectorAll(".edit-gig-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        fillModalFromDataset(btn as HTMLElement);
        openModal(lang === "es" ? `Editar ${termOne}` : `Edit ${termOne}`);
    });
});
```

add:

```ts
document.querySelectorAll(".duplicate-gig-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        fillModalFromDataset(btn as HTMLElement);
        // fillModalFromDataset sets editIdInput.value from b.dataset.id, which
        // is undefined here (no data-id on this button) — undefined coerces
        // to the string "undefined" on an <input>.value setter, not "". Must
        // clear explicitly so the submit handler's `gigId ? PUT : POST`
        // branch takes the create (POST) path.
        editIdInput.value = "";
        const titleInput = document.getElementById("f-title") as HTMLInputElement;
        titleInput.value = titleInput.value + (lang === "es" ? " (copia)" : " (copy)");
        openModal(lang === "es" ? `Duplicar ${termOne}` : `Duplicate ${termOne}`);
    });
});
```

- [ ] **Step 4: Manual verification in the browser**

Start the stack (skip if already running): `podman compose up -d` then confirm `podman compose ps` shows frontend/backend healthy.

1. Go to `http://localhost:3003/login`, sign in as `mom@demo.com` / `password123`.
2. Go to `http://localhost:3003/parent/gigs`.
3. On any existing gig card, click **Duplicar**/**Duplicate**.
4. Confirm the modal opens titled "Duplicar Gig" / "Duplicate Gig", with Title/Description/Pay/Difficulty/Category/Cadence/"multiple kids" all prefilled from that card, and the title field ending in `" (copia)"` / `" (copy)"`.
5. Click Save. Confirm the page reloads with **two** cards for that gig (the new one with the suffixed title) and the original card unchanged.
6. Click **Editar**/**Edit** on the original card afterward — confirm it still opens with its own unsuffixed title and still updates in place (not duplicated) on Save, i.e. the edit path is unaffected.

If any check fails, fix before continuing — do not proceed to commit.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent/gigs.astro
git commit -m "feat(gigs): add duplicate button to parent gig cards"
```
