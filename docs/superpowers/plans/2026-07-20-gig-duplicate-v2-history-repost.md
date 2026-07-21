# Gig Duplicate v2 — Repost from History + Icon-Reweight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a parent repost a gig that has already closed and dropped off the active list (visible only in History), and de-crowd the active-card action row per user feedback on the v1 Duplicate button.

**Architecture:** One backend route gets a previously-dead query param wired up so closed offerings become fetchable. The parent gigs page then fetches all offerings (active + inactive) once, keeps deriving the visible active-card list from that, and separately builds an id→offering lookup used only to attach a conditional "Repost" button to History rows whose gig has actually closed. Active cards get a visual reweight (icon-only secondary actions) — pure markup/CSS, no behavior change.

**Tech Stack:** FastAPI + SQLAlchemy (backend route), Astro 5 + Tailwind v4 + vanilla JS (frontend page, hoisted `<script>`).

## Global Constraints

- Default `include_inactive` behavior must not change for any existing caller (kid board `/gigs`, proposal review) — only the parent gigs page passes `true`.
- No new JS handler for the Repost button — it must reuse the exact `.duplicate-gig-btn` class and data-attribute set already shipped in PR #144, so the existing click-wiring covers it automatically.
- Repost only renders on a History row when that row's offering is actually inactive (`is_active === false`). A still-active gig's history rows render nothing extra — the active-card Duplicate button already covers that case.
- Icon-only secondary buttons (Duplicate/Archive on active cards) need an `aria-label` (and a `title` for hover tooltip) since their visible text label is removed.
- Backend route changes get a real pytest regression test (unlike the v1 plan, which was frontend-only). Frontend changes stay manual-browser-verified only, per this project's CLAUDE.md UI-change rule.
- Spec: `docs/superpowers/specs/2026-07-20-gig-duplicate-v2-history-repost-design.md`

---

### Task 1: Backend — wire `include_inactive` on `GET /api/gigs/offerings`

**Files:**
- Modify: `backend/app/api/routes/gigs.py:137-152` (`list_offerings`)
- Modify: `backend/tests/test_gig_board.py:92-115` (extend `test_edit_and_deactivate_offering`)

**Interfaces:**
- Consumes: `GigOfferingService.list_for_family(db, family_id, user_id, include_inactive: bool = False)` — already accepts this kwarg (`backend/app/services/gig_offering_service.py:17-22`), just wasn't being passed a non-default value from the route.
- Produces: `GET /api/gigs/offerings?include_inactive=true` now actually returns inactive offerings too. Task 2's frontend fetch depends on this.

- [ ] **Step 1: Wire the query param**

In `backend/app/api/routes/gigs.py`, `list_offerings` currently reads (lines 137-152):

```python
@router.get("/offerings", response_model=List[EnrichedOfferingResponse])
async def list_offerings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    items = await GigOfferingService.list_for_family(db, family_id, user_id)
    return [
        EnrichedOfferingResponse(
            offering=GigOfferingResponse.model_validate(item["offering"]),
            my_claim=GigClaimResponse.model_validate(item["my_claim"]) if item["my_claim"] else None,
            active_claimers=item.get("active_claimers", []),
        )
        for item in items
    ]
```

Replace it with:

```python
@router.get("/offerings", response_model=List[EnrichedOfferingResponse])
async def list_offerings(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    items = await GigOfferingService.list_for_family(
        db, family_id, user_id, include_inactive=include_inactive
    )
    return [
        EnrichedOfferingResponse(
            offering=GigOfferingResponse.model_validate(item["offering"]),
            my_claim=GigClaimResponse.model_validate(item["my_claim"]) if item["my_claim"] else None,
            active_claimers=item.get("active_claimers", []),
        )
        for item in items
    ]
```

`Query` is already imported at the top of this file (`from fastapi import APIRouter, Depends, Query, status, HTTPException`) — no new import needed.

- [ ] **Step 2: Extend the regression test**

In `backend/tests/test_gig_board.py`, `test_edit_and_deactivate_offering` currently ends with (lines 111-115):

```python
    # Deactivated offering no longer appears in list
    list_res = await client.get("/api/gigs/offerings", headers=parent_headers)
    ids = [i["offering"]["id"] for i in list_res.json()]
    assert gig_id not in ids
```

Append immediately after (still inside the same test function):

```python
    # Deactivated offering no longer appears in list
    list_res = await client.get("/api/gigs/offerings", headers=parent_headers)
    ids = [i["offering"]["id"] for i in list_res.json()]
    assert gig_id not in ids

    # ...but IS returned when include_inactive=true (needed so the frontend
    # can source a closed gig's fields to repost it from History)
    list_all_res = await client.get(
        "/api/gigs/offerings?include_inactive=true", headers=parent_headers
    )
    all_ids = [i["offering"]["id"] for i in list_all_res.json()]
    assert gig_id in all_ids
```

- [ ] **Step 3: Run the test**

If the local podman stack is up: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_board.py -v`

If podman is down, fall back to the bare-metal path this project uses (Homebrew Postgres on 5435 + local redis + `backend/.venv/bin/pytest --no-cov`), same as documented in this project's CLAUDE.md / `project_local_tests_sin_podman` notes.

Expected: all tests in `test_gig_board.py` pass, including the extended `test_edit_and_deactivate_offering`.

- [ ] **Step 4: Lint**

Run: `cd backend && ruff check app`
Expected: clean (zero-tolerance gate, per this project's CI).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/gigs.py backend/tests/test_gig_board.py
git commit -m "feat(gigs): wire include_inactive query param on offerings list"
```

---

### Task 2: Frontend — Repost from History + active-card icon-reweight

**Files:**
- Modify: `frontend/src/pages/parent/gigs.astro` (frontmatter data plumbing, active-card render block, history-card render block)

**Interfaces:**
- Consumes: `GET /api/gigs/offerings?include_inactive=true` (Task 1). Reuses the already-shipped `.duplicate-gig-btn` class and its click handler (`frontend/src/pages/parent/gigs.astro:511-524`, unmodified by this task) and `fillModalFromDataset`/`openModal`/`editIdInput` (unmodified).
- Produces: `activeOfferings`, `offeringById`, `historyEnriched` — frontmatter-only values, nothing outside this file depends on them.

- [ ] **Step 1: Fetch all offerings, derive active + lookup map**

Line 19 currently reads:

```ts
    apiFetch<any[]>("/api/gigs/offerings?include_inactive=false", { token }),
```

Change to:

```ts
    apiFetch<any[]>("/api/gigs/offerings?include_inactive=true", { token }),
```

Lines 25-26 currently read:

```ts
const offerings: any[] = offeringsRes.data ?? [];
const gt = gigTerm(familyRes.data?.gig_term ?? "gig", lang);
```

Replace with:

```ts
const offerings: any[] = offeringsRes.data ?? [];
const gt = gigTerm(familyRes.data?.gig_term ?? "gig", lang);
// include_inactive=true above (not "false") so closed gigs can still be
// reposted from History; activeOfferings filters back to the visible list.
const activeOfferings = offerings.filter((item: any) => (item.offering ?? item).is_active);
const offeringById = new Map(
    offerings.map((item: any) => {
        const o = item.offering ?? item;
        return [o.id, o];
    }),
);
```

- [ ] **Step 2: Enrich history rows with their offering**

Line 39 currently reads:

```ts
const historyKids = [...new Set(history.map((c: any) => c.claimer_name).filter(Boolean))] as string[];
```

Add immediately after it:

```ts
const historyKids = [...new Set(history.map((c: any) => c.claimer_name).filter(Boolean))] as string[];
const historyEnriched = history.map((c: any) => ({
    ...c,
    repostOffering: offeringById.get(c.gig_id) ?? null,
}));
```

- [ ] **Step 3: Switch the active-cards section to `activeOfferings` + icon-reweight the button row**

Lines 210-271 currently read:

```astro
            <!-- Gig offerings -->
            <div class="space-y-3">
                {offerings.length === 0 && (
                    <div class="bg-brand-cream rounded-2xl p-8 text-center border border-brand-ink/10 shadow-[var(--shadow-card)]">
                        <p class="text-brand-ink-soft text-sm">
                            {lang === "es" ? `No has publicado ninguna ${gt.one} aún. ¡Crea la primera!` : `No ${gt.many} posted yet. Create the first one!`}
                        </p>
                    </div>
                )}
                {offerings.map((item: any) => {
                    const o = item.offering ?? item;
                    return (
                        <div data-gig-card class="bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10">
                            <div class="flex justify-between items-start">
                                <div class="flex-1 pr-4">
                                    <h3 class="font-bold text-brand-ink">{o.title}</h3>
                                    {o.description && <p class="text-brand-ink-soft text-sm mt-0.5 line-clamp-2">{o.description}</p>}
                                    <div class="flex items-center gap-2 mt-2 flex-wrap">
                                        <DifficultyChip level={o.difficulty ?? 1} lang={lang} />
                                    </div>
                                </div>
                                <div class="text-right flex-shrink-0">
                                    <p class="text-xl font-extrabold text-emerald-600">${o.points} <span class="text-xs font-semibold text-brand-ink-soft">MXN</span></p>
                                </div>
                            </div>
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
                        </div>
                    );
                })}
            </div>
```

Replace with:

```astro
            <!-- Gig offerings -->
            <div class="space-y-3">
                {activeOfferings.length === 0 && (
                    <div class="bg-brand-cream rounded-2xl p-8 text-center border border-brand-ink/10 shadow-[var(--shadow-card)]">
                        <p class="text-brand-ink-soft text-sm">
                            {lang === "es" ? `No has publicado ninguna ${gt.one} aún. ¡Crea la primera!` : `No ${gt.many} posted yet. Create the first one!`}
                        </p>
                    </div>
                )}
                {activeOfferings.map((item: any) => {
                    const o = item.offering ?? item;
                    return (
                        <div data-gig-card class="bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10">
                            <div class="flex justify-between items-start">
                                <div class="flex-1 pr-4">
                                    <h3 class="font-bold text-brand-ink">{o.title}</h3>
                                    {o.description && <p class="text-brand-ink-soft text-sm mt-0.5 line-clamp-2">{o.description}</p>}
                                    <div class="flex items-center gap-2 mt-2 flex-wrap">
                                        <DifficultyChip level={o.difficulty ?? 1} lang={lang} />
                                    </div>
                                </div>
                                <div class="text-right flex-shrink-0">
                                    <p class="text-xl font-extrabold text-emerald-600">${o.points} <span class="text-xs font-semibold text-brand-ink-soft">MXN</span></p>
                                </div>
                            </div>
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
                                    class="duplicate-gig-btn shrink-0 w-11 py-2 text-base text-indigo-700 bg-indigo-100 rounded-xl hover:bg-indigo-200 transition-colors"
                                    aria-label={lang === "es" ? "Duplicar" : "Duplicate"}
                                    title={lang === "es" ? "Duplicar" : "Duplicate"}
                                    data-title={o.title}
                                    data-description={o.description ?? ""}
                                    data-points={o.points}
                                    data-difficulty={o.difficulty ?? 1}
                                    data-category={o.category ?? "other"}
                                    data-allow-multiple={o.allow_multiple ? "1" : "0"}
                                    data-payout-cadence={o.payout_cadence ?? "immediate"}
                                >
                                    📋
                                </button>
                                <button
                                    class="archive-gig-btn shrink-0 w-11 py-2 text-base text-brand-ink-soft bg-brand-cream-deep rounded-xl hover:bg-red-100 hover:text-red-700 transition-colors"
                                    aria-label={lang === "es" ? "Archivar" : "Archive"}
                                    title={lang === "es" ? "Archivar" : "Archive"}
                                    data-id={o.id}
                                >
                                    🗄️
                                </button>
                            </div>
                        </div>
                    );
                })}
            </div>
```

(Only 3 things changed vs. the original: `offerings.length`→`activeOfferings.length`, `offerings.map`→`activeOfferings.map`, and the Duplicate/Archive buttons shrank to icon-only with `aria-label`/`title` added. The Edit button, card body, and `.map()` callback's `o` variable are untouched.)

- [ ] **Step 4: Switch history render to `historyEnriched`, add the conditional Repost button**

The history section's `.map()` currently opens with (line 296):

```astro
                        {history.map((c: any) => (
```

Change to:

```astro
                        {historyEnriched.map((c: any) => (
```

Further down, currently (lines 338-343):

```astro
                                {c.approval_notes && (
                                    <p class="text-[11px] text-brand-ink-soft italic mt-1.5">
                                        💬 {c.approval_notes}
                                    </p>
                                )}
                                <div class="flex items-center gap-3 mt-2">
```

Replace with:

```astro
                                {c.approval_notes && (
                                    <p class="text-[11px] text-brand-ink-soft italic mt-1.5">
                                        💬 {c.approval_notes}
                                    </p>
                                )}
                                {c.repostOffering && !c.repostOffering.is_active && (
                                    <button
                                        class="duplicate-gig-btn w-full mt-2 py-2 text-sm font-semibold text-indigo-700 bg-indigo-100 rounded-xl hover:bg-indigo-200 transition-colors"
                                        data-title={c.repostOffering.title}
                                        data-description={c.repostOffering.description ?? ""}
                                        data-points={c.repostOffering.points}
                                        data-difficulty={c.repostOffering.difficulty ?? 1}
                                        data-category={c.repostOffering.category ?? "other"}
                                        data-allow-multiple={c.repostOffering.allow_multiple ? "1" : "0"}
                                        data-payout-cadence={c.repostOffering.payout_cadence ?? "immediate"}
                                    >
                                        {lang === "es" ? `↻ Repostar ${gt.one}` : `↻ Repost this ${gt.one}`}
                                    </button>
                                )}
                                <div class="flex items-center gap-3 mt-2">
```

This button has no `data-id`, matching the existing active-card Duplicate button — the already-shipped click handler (`frontend/src/pages/parent/gigs.astro:511-524`, untouched by this task) already clears `editIdInput.value` explicitly for exactly this reason, so no JS change is needed here at all.

- [ ] **Step 5: Verify Astro/TS still type-checks**

Run: `cd frontend && npm run check`
Expected: 0 errors (same baseline as before this change — see PR #144's verification, which reported 0 errors/222 files/90 pre-existing hints).

- [ ] **Step 6: Manual verification in the browser**

This scenario needs a gig that has BOTH a completed claim (so it shows in History) AND is now inactive (so Repost renders) — that combination likely doesn't exist yet in the demo family's seed data, so create it first.

Ensure the stack is up (`podman compose ps`; `podman compose up -d` if not — rebuild+recreate the backend/frontend containers if they were already running before this task's code changes, e.g. `podman compose up -d --build backend frontend`, same as needed in PR #144's Task 1 verification).

1. Get a parent token and a kid token via login (mirrors `e2e-tests/gigs.spec.js`'s `login()` helper):
   ```bash
   PARENT_TOKEN=$(curl -s -X POST http://localhost:8003/api/auth/login -H "Content-Type: application/json" -d '{"email":"mom@demo.com","password":"password123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   KID_TOKEN=$(curl -s -X POST http://localhost:8003/api/auth/login -H "Content-Type: application/json" -d '{"email":"emma@demo.com","password":"password123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   ```
2. Parent creates a single-claim gig:
   ```bash
   GIG_ID=$(curl -s -X POST http://localhost:8003/api/gigs/offerings -H "Authorization: Bearer $PARENT_TOKEN" -H "Content-Type: application/json" -d '{"title":"Repost test gig","points":15,"difficulty":1,"category":"other"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
   ```
3. Kid claims and completes it:
   ```bash
   CLAIM_ID=$(curl -s -X POST http://localhost:8003/api/gigs/offerings/$GIG_ID/claim -H "Authorization: Bearer $KID_TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
   curl -s -X POST http://localhost:8003/api/gigs/claims/$CLAIM_ID/complete -H "Authorization: Bearer $KID_TOKEN" -H "Content-Type: application/json" -d '{"proof_text":"done"}'
   ```
4. Parent approves it (auto-closes the offering since `allow_multiple` defaulted to false):
   ```bash
   curl -s -X POST http://localhost:8003/api/gigs/claims/$CLAIM_ID/approve -H "Authorization: Bearer $PARENT_TOKEN" -H "Content-Type: application/json" -d '{"approved":true}'
   ```
5. In the browser (use `claude-in-chrome` — load it via `ToolSearch` with `query: "select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp"` if not already loaded), log in as `mom@demo.com` / `password123`, go to `http://localhost:3003/parent/gigs`:
   - Confirm "Repost test gig" is **not** in the active "Gig offerings" section.
   - Confirm it **does** appear in History, with a "↻ Repostar Gig" / "↻ Repost this Gig" button.
   - Click it. Confirm the modal opens with title ending in `" (copia)"`/`" (copy)"`, points `15`, difficulty "Fácil"/"Easy" — use `read_page` to confirm actual field values, not just a screenshot.
   - Save. Confirm a new active card appears (the "(copia)" one); confirm the History row still shows the original completed entry with its Repost button still present (its own offering is still the same closed one).
6. Still on `/parent/gigs`, on any active card confirm the icon-reweight: Edit shows its label as before; the two small buttons next to it show 📋 and 🗄️ with no visible text. Click 📋 — confirm same Duplicate-prefill-modal behavior as before (unchanged handler). Click 🗄️ on a different card — confirm same Archive-confirm-and-remove behavior as before (unchanged handler). Use `read_page` to confirm the `aria-label` attribute is present on both icon buttons.

If any check fails, fix before continuing — do not proceed to commit.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/parent/gigs.astro
git commit -m "feat(gigs): repost gigs from history, icon-reweight active card actions"
```
