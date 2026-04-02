# UX Enhancements: View Transitions + Skeleton Loaders + Toast System

**Date:** 2026-04-01
**Status:** Approved
**Scope:** Frontend only — no backend changes

## Goal

Transform the app from full-page-reload navigation to SPA-like smoothness, add loading feedback, and replace `alert()` dialogs with a unified toast notification system.

## 1. View Transitions (ClientRouter)

### What

Add Astro's built-in `<ClientRouter />` to enable client-side page navigation with cross-fade animations and persistent UI elements.

### Changes

**`frontend/src/layouts/Layout.astro`:**
- Import and add `<ClientRouter />` in `<head>`
- Add `transition:persist` to `<BottomNav />` so it survives navigation without remounting
- Add `transition:animate="fade"` to the main content wrapper

**28 files with inline `<script>` event listeners** must wrap their DOM setup in `astro:page-load`:

```javascript
// Before
document.querySelector('#btn').addEventListener('click', handler);

// After
document.addEventListener('astro:page-load', () => {
  document.querySelector('#btn')?.addEventListener('click', handler);
});
```

Files requiring this change (from codebase grep):
- `frontend/src/pages/budget/reports/budget-analysis.astro`
- `frontend/src/pages/budget/accounts/[id].astro`
- `frontend/src/pages/budget/transactions.astro`
- `frontend/src/pages/budget/month/[year]/[month].astro`
- `frontend/src/pages/budget/settings/payees.astro`
- `frontend/src/pages/budget/settings/rules.astro`
- `frontend/src/pages/budget/categories/index.astro`
- `frontend/src/pages/budget/accounts/[id]/reconcile.astro`
- `frontend/src/pages/budget/settings/recurring.astro`
- `frontend/src/pages/budget/import.astro`
- `frontend/src/components/AssignFundsModal.astro`
- `frontend/src/pages/parent/finances/accounts/[id]/reconcile.astro`
- `frontend/src/pages/parent/finances/categories/index.astro`
- `frontend/src/pages/parent/finances/month/[year]/[month].astro`
- `frontend/src/components/RecycleBinTable.astro`
- `frontend/src/pages/register.astro`
- `frontend/src/pages/accept-invitation.astro`
- `frontend/src/components/InvitationModal.astro`
- `frontend/src/pages/parent/members.astro`
- `frontend/src/components/EditMemberModal.astro`
- `frontend/src/pages/login.astro`
- `frontend/src/layouts/Layout.astro`
- `frontend/src/pages/reset-password.astro`
- `frontend/src/pages/forgot-password.astro`
- `frontend/src/pages/index.astro`
- `frontend/src/pages/parent/tasks/[id]/edit.astro`
- `frontend/src/pages/payment.astro`
- `frontend/src/components/PointsConverter.astro`

### Approach

Each file's `<script>` block gets a simple mechanical transformation:
1. Find the outermost scope of DOM-dependent code
2. Wrap in `document.addEventListener('astro:page-load', () => { ... })`
3. Add optional chaining (`?.`) on querySelector calls for safety

Scripts that only define pure functions or import modules (no DOM access) do NOT need wrapping.

### Transition Animations

Use Astro's built-in `fade` animation (150ms cross-fade). No custom animations — keep it simple and fast.

## 2. Toast Notification System

### What

A lightweight toast system that replaces all `alert()` calls and inline success/error banners.

### New Files

**`frontend/src/lib/toast.ts`** — Toast API module:
```typescript
type ToastType = 'success' | 'error' | 'info';

export function showToast(message: string, type: ToastType = 'info', durationMs: number = 4000): void;
```

Behavior:
- Creates a toast element and appends to `#toast-container`
- Auto-removes after `durationMs` with a CSS progress bar countdown
- Click-to-dismiss
- Stacks multiple toasts vertically (max 3 visible, oldest dismissed first)
- Colors: green-600 (success), red-600 (error), blue-600 (info)

**`frontend/src/components/ToastContainer.astro`** — Mount point:
```html
<div id="toast-container" class="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm w-full pointer-events-none" transition:persist>
</div>
```

- Positioned top-right, above all other UI (z-100)
- `transition:persist` so it survives page navigation
- `pointer-events-none` on container, `pointer-events-auto` on individual toasts
- Added to `Layout.astro` once

### Toast HTML Structure (created by JS)

```html
<div class="toast pointer-events-auto bg-white border-l-4 border-green-600 shadow-lg rounded-lg p-4 flex items-start gap-3 animate-slide-in">
  <svg><!-- icon --></svg>
  <p class="text-sm text-slate-700 flex-1">Message text</p>
  <button class="text-slate-400 hover:text-slate-600">&times;</button>
  <div class="absolute bottom-0 left-0 h-0.5 bg-green-600 animate-countdown"></div>
</div>
```

### CSS Animations (in global.css)

```css
@keyframes slide-in { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
@keyframes countdown { from { width: 100%; } to { width: 0%; } }
.animate-slide-in { animation: slide-in 0.2s ease-out; }
.animate-countdown { animation: countdown var(--toast-duration, 4s) linear forwards; }
```

### alert() Replacements

20 `alert()` calls across these files need replacing:

| File | Current | Replacement |
|------|---------|-------------|
| `login.astro` | `alert(errorMsg)` | `showToast(errorMsg, 'error')` |
| `budget/import.astro` | `alert('select account...')` | `showToast(msg, 'error')` |
| `budget/settings/rules.astro` | `alert(err.detail)` | `showToast(err.detail, 'error')` |
| `budget/settings/recurring.astro` | `alert(err.detail)` | `showToast(err.detail, 'error')` |
| `budget/settings/payees.astro` | `alert(err.detail)` | `showToast(err.detail, 'error')` |
| `budget/settings/backups.astro` | `alert('coming soon')` | `showToast(msg, 'info')` |
| `parent/members.astro` | `alert('error')` | `showToast(msg, 'error')` |
| `payment.astro` | `alert('please log in')` | `showToast(msg, 'error')` |
| `PointsConverter.astro` | `alert(...)` | `showToast(msg, 'error')` |

Additionally, inline success/error banners that auto-hide after 3s (found in budget pages) should be converted to `showToast()` calls where appropriate.

## 3. Skeleton Loaders

### What

A reusable skeleton component for client-side loading states, plus an inline button spinner.

### New File

**`frontend/src/components/SkeletonLoader.astro`:**

Props: `variant: 'line' | 'card' | 'row'`, `count: number` (default 3)

```html
<!-- variant="line" -->
<div class="h-4 bg-slate-200 rounded animate-pulse w-3/4"></div>

<!-- variant="card" -->
<div class="h-24 bg-slate-200 rounded-lg animate-pulse"></div>

<!-- variant="row" -->
<div class="flex gap-4 items-center">
  <div class="h-4 bg-slate-200 rounded animate-pulse w-1/4"></div>
  <div class="h-4 bg-slate-200 rounded animate-pulse w-1/2"></div>
  <div class="h-4 bg-slate-200 rounded animate-pulse w-1/6"></div>
</div>
```

Uses Tailwind's built-in `animate-pulse`. No custom CSS needed.

### Button Spinner

**`frontend/src/components/ButtonSpinner.astro`:**

A small inline SVG spinner (16x16) for submit buttons:

```html
<svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/>
  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
</svg>
```

### Usage Pattern

For submit buttons across the app, replace the current `btn.textContent = '...'` pattern:

```javascript
// Before
submitBtn.disabled = true;
submitBtn.textContent = '...';

// After
const originalHTML = submitBtn.innerHTML;
submitBtn.disabled = true;
submitBtn.innerHTML = '<svg class="animate-spin h-4 w-4 mx-auto" ...></svg>';
// On complete:
submitBtn.innerHTML = originalHTML;
submitBtn.disabled = false;
```

The spinner SVG markup is small enough to inline. No component import needed in JS — just a constant string.

### Where Skeletons Are Used

Skeleton loaders are for **client-side fetched content** only. Since Astro SSR renders most pages server-side, skeletons apply to:

1. **Budget transaction list after filter/search** — show skeleton rows while re-fetching
2. **Budget month view after month navigation** — show skeleton cards while loading new month data
3. **Assignment completion feedback** — skeleton row for the updated assignment
4. **Bulk action results** — skeleton while bulk update/delete processes

Pages that render data server-side (dashboard, task list initial load) do NOT need skeletons — they arrive fully rendered.

## Out of Scope

- Desktop sidebar navigation (separate iteration)
- PWA / service worker / manifest
- Inline form validation
- Accessibility improvements (skip links, focus traps)
- Custom transition animations beyond `fade`

## File Summary

| Action | File |
|--------|------|
| **Create** | `frontend/src/lib/toast.ts` |
| **Create** | `frontend/src/components/ToastContainer.astro` |
| **Create** | `frontend/src/components/SkeletonLoader.astro` |
| **Create** | `frontend/src/components/ButtonSpinner.astro` |
| **Modify** | `frontend/src/layouts/Layout.astro` (ClientRouter + ToastContainer + persist BottomNav) |
| **Modify** | `frontend/src/styles/global.css` (toast animations) |
| **Modify** | 28 files with inline scripts (astro:page-load wrapper) |
| **Modify** | ~10 files with alert() calls (replace with showToast) |

## Testing

- Manual: navigate between pages — verify no white flash, bottom nav stays, scripts work
- Manual: trigger errors (bad login, failed API) — verify toast appears, auto-dismisses
- Manual: filter budget transactions — verify skeleton shows during load
- E2e: existing Playwright suite should still pass (DOM structure unchanged)
