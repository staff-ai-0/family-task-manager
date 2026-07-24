# Merge /dashboard (parent view) into /parent

**Date:** 2026-07-24 · **Approved by:** Juan

## Problem

`/parent` (parent hub) and `/dashboard` (personal today-tasks page) look nearly
identical to a parent — especially one with no self-assigned chores. Parents'
"Inicio" nav points at `/parent`; `/dashboard` for them is a redundant page.
Kids' entire experience (nav "Tareas", pet, payday, streak, module-off bounce)
lives on `/dashboard` and must not change.

## Decisions

1. **Parents never see `/dashboard`.** `dashboard.astro` frontmatter: when
   `user.role === "parent"`, 302 to `/parent`, forwarding `?module_off=1`
   (and any flash cookies survive — they're cookies, not params).
2. **Parent's own tasks move into `/parent`.** New "Mis tareas de hoy /
   My tasks today" section in `parent/index.astro`, fed by the same
   `GET /api/task-assignments/progress` payload dashboard uses. Rendered
   ONLY when the parent has ≥1 assignment today. Compact card per task:
   title, points, status chip, and a complete action posting to the same
   endpoint the dashboard uses. No pet/streak/photo-proof machinery.
3. **Role-aware module-off bounce.** `middleware.ts`: gated module deep link →
   parent bounces to `/parent?module_off=1`, kid to `/dashboard?module_off=1`
   (role read from the same cached `meUser` already fetched there).
   `parent/index.astro` gets the dismissible module-off banner dashboard has.
4. **Role-aware post-login redirects.** Login (password + Google) fallback
   destination: parent → `/parent`, kid → `/dashboard` (role available in the
   login/OAuth response). Explicit `?next=` still wins.
5. **Link sweep.** Any parent-context link/redirect to `/dashboard` → `/parent`.
   Kid-bound redirects (`role !== "parent" → /dashboard`) stay unchanged.

## Explicitly out of scope

- Extracting dashboard task-card markup into a shared component (kid-page
  regression risk pre-launch outweighs DRY).
- Any backend change.
- Kid-side UI changes of any kind.

## Testing

- `astro check` clean.
- Playwright: update/extend specs — parent hitting `/dashboard` lands on
  `/parent`; kid still lands on `/dashboard`; parent with a task today sees
  the new section; parent without tasks doesn't.
