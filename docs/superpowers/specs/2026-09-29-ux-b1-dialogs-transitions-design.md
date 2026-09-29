# UX-B1 — In-App Dialogs + Page Transitions — Design

**Date:** 2026-09-29
**Status:** design approved in chat (2026-09-29), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **B1 + B5** of B (design-system consolidation). A, C1, C2 shipped.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` F11 (native dialogs) and F14 (every navigation is a hard reload).

## Why

- **98 native `alert` / `confirm` / `prompt` calls in 31 files** (measured 2026-09-29; budget pages hold 34). They block the whole page, look like the operating system rather than the app, show English OS buttons to Spanish-speaking families, and are especially jarring in the installed PWA.
- Two are inline HTML handlers (`onsubmit` on the permanent member delete form, `onclick` on the template delete link).
- Every navigation is a full-page reload with a white flash; the app never feels like an app.

**Goal:** no native dialog anywhere in the app; confirmations and text input happen in an app-styled, bilingual sheet; pages cross-fade.

**Decisions from the brainstorm:**
- `alert` → **toast** (non-blocking, the existing `lib/toast.ts`).
- `confirm` / `prompt` → **one shared in-app sheet**; destructive confirms use a **red button with a clear verb**; the existing "type the name to confirm" checks stay.
- **Quick cross-fade** page transitions; the bottom nav does not flash.
- Admin pages are included.

**Not in B1:** dark mode (B2), visual consistency / UI-kit adoption / tokens (B3), budget double navigation and number wording (B4), any backend change.

## The shared sheet

### API — `frontend/src/lib/dialogs.ts`

```ts
confirmSheet(opts: {
  title: string;
  body?: string;
  confirmLabel?: string;   // default "Aceptar" / "OK"
  cancelLabel?: string;    // default "Cancelar" / "Cancel"
  danger?: boolean;        // red confirm button, initial focus on Cancel
}): Promise<boolean>

promptSheet(opts: {
  title: string;
  body?: string;
  label?: string;          // accessible label for the input (defaults to title)
  defaultValue?: string;
  placeholder?: string;
  inputType?: "text" | "number";
  requireMatch?: string;   // confirm stays disabled until the trimmed input equals this (trimmed)
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}): Promise<string | null>  // null = cancelled; otherwise the input value (not trimmed, callers decide)
```

- Default labels follow `document.documentElement.lang` (`es` → Spanish, anything else → English).
- **Validation** (pure, unit-tested): with `requireMatch`, valid only when `value.trim() === requireMatch.trim()`; with `inputType: "number"`, valid only when the value parses to a finite number; otherwise always valid (an empty string is a legitimate answer — callers already handle it).
- **One at a time:** a call made while a sheet is open waits and opens after the current one resolves (FIFO).
- **Fail safe:** if the host element is missing (should not happen — Layout always mounts it), `confirmSheet` resolves `false` and `promptSheet` resolves `null`, so nothing destructive runs.

### Host — `frontend/src/components/ui/AppDialog.astro`

- One native `<dialog id="app-dialog">`, mounted once in `frontend/src/layouts/Layout.astro` right after `<ToastContainer />`. `showModal()` puts it in the browser's top layer, so it always sits above the bottom nav (no z-index juggling) and gives Esc handling and inert background for free.
- **Layout:** bottom sheet on phones (full width, rounded top, safe-area bottom padding); centered card (`max-w-sm`) from `sm` up. Uses the app's tokens (`bg-brand-cream`, `text-brand-ink`, brand borders/shadow), not native styling.
- **Content:** title (the dialog's accessible name via `aria-labelledby`), optional body, optional input, then buttons: Cancel (secondary) and Confirm (primary; `danger` → red).
- **Cancel paths:** Cancel button, Esc, tap on the backdrop → resolve `false` / `null`.
- **Focus:** confirm → Cancel when `danger`, otherwise Confirm; prompt → the input, with its text selected. On close, focus returns to the element that was focused before opening.
- **Enter** in the input confirms when the value is valid; the confirm button is `disabled` while invalid.
- **Reduced motion:** the sheet's slide/fade is removed under `prefers-reduced-motion: reduce`.

## Migrating the call sites

Every native call in `frontend/src` is replaced (98 calls, 31 files — the migration plan lists them per file):

| Native | Becomes |
|---|---|
| `alert(msg)` | `showToast(msg, type)` — `"error"` for failures (duration 6000 ms), `"success"` for completed actions, `"info"` otherwise |
| `if (!confirm(msg)) return;` | `if (!(await confirmSheet({ title, body?, confirmLabel, danger })) ) return;` — the enclosing handler becomes `async` |
| `const v = prompt(msg, def)` | `const v = await promptSheet({ title, defaultValue: def, … })` |

Rules:
- **Destructive confirms** (delete, remove, reset, reject, revoke, cancel a subscription, unlink) use `danger: true` and a verb label ("Eliminar", "Quitar", "Revocar", "Restablecer"…) instead of "Aceptar". The title names the thing ("¿Eliminar la categoría Comida?") when the old message did.
- **Copy stays bilingual** the way each page already does it (inline `es ? … : …` ternaries or `t()` keys); a page that only had English text in a native dialog gets the Spanish added.
- **Typed confirmations** keep their rule through `requireMatch`: budget settings' reset (the existing typed-word check) and the permanent member delete (type the member's exact name).
- **Inline handlers** move into the page's script:
  - `parent/members.astro` permanent delete: a `submit` listener prevents the default, awaits `promptSheet({ requireMatch: name, danger: true, … })`, writes the value into the hidden `confirm_name` input and calls `form.submit()`; cancel does nothing.
  - `TaskCreateModal.astro` template delete link: a click listener prevents navigation, awaits `confirmSheet({ danger: true, … })`, then follows the link.
- **Batch confirms** (e.g. "Aprobar todo" on `/parent/approvals`) keep their current semantics: one confirm before the loop.
- **Out of scope:** `google.accounts.id.prompt()` in `login.astro` is Google's sign-in API, not a native dialog — unchanged.

## Guard against regressions

`frontend/test/no-native-dialogs.test.ts` (vitest) walks `frontend/src/**/*.{astro,ts}` and fails when a file contains a native dialog call: `alert(`, `confirm(`, `prompt(` not preceded by a letter, digit, `_` or `.`, and `window.alert(` / `window.confirm(` / `window.prompt(`. It skips `// …` and `/* … */` comment text. The allowlist is explicit and minimal: `login.astro` for `google.accounts.id.prompt(` (matched with its receiver, so a bare `prompt(` in that file still fails).

## Page transitions

In `frontend/src/styles/global.css`:

```css
@view-transition { navigation: auto; }
::view-transition-old(root),
::view-transition-new(root) { animation-duration: 150ms; }
@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) { animation: none !important; }
}
```

- The bottom nav's root `<nav>` (`frontend/src/components/BottomNav.astro`) gets `style="view-transition-name: bottom-nav"` so it is captured separately and does not fade with the page.
- Browsers without cross-document view transitions (Firefox, older Safari) navigate exactly as today — no JS, no polyfill.
- The existing one-shot `astro:page-load` dispatch in `Layout.astro` is unaffected (cross-document transitions are still full navigations).

## Units and files

| File | Responsibility |
|------|----------------|
| `frontend/src/lib/dialogs.ts` (new) | `confirmSheet`, `promptSheet`, pure validation + default labels + queue |
| `frontend/src/components/ui/AppDialog.astro` (new) | the `<dialog>` host markup + its client script (binds to `lib/dialogs.ts`) |
| `frontend/src/layouts/Layout.astro` | mount `<AppDialog />` once |
| 31 files with native calls — budget pages ×4 (transactions, settings, index, reports), parent pages ×15, admin pages ×2 (coupons, families/[id]), other pages ×6 (chat, login, gigs/my-gigs, shopping, rewards, bank), components ×4 (ReceiptScanSheet, AssignFundsModal, TaskCreateModal, MoreSheet) | call-site migration |
| `frontend/src/styles/global.css` | view-transition rules |
| `frontend/src/components/BottomNav.astro` | `view-transition-name` |
| `frontend/test/dialogs.test.ts` (new) | pure logic of `lib/dialogs.ts` |
| `frontend/test/no-native-dialogs.test.ts` (new) | regression guard |

## Error handling

- A sheet never throws to its caller: any internal failure resolves as cancel (`false` / `null`).
- A toast replacing an error `alert` keeps the same message text (backend `detail` where the page showed it).
- Where an old `alert` was followed by navigation or reload, the plan checks the order; a toast that would be lost to an immediate reload is shown after the navigation only if the page had that pattern (none found in the 2026-09-29 scan).

## Testing

- **vitest** `dialogs.test.ts`: validation (`requireMatch` exact after trim, number parsing incl. `""`, `"1e3"`, `"abc"`), default labels per `lang`, FIFO queue ordering with a fake host, fail-safe results without a host. Every test mutation-checked.
- **vitest** `no-native-dialogs.test.ts`: passes on the migrated tree; a fixture string with each forbidden form is detected; the Google call is allowed; a bare `prompt(` in `login.astro` is not.
- `astro check` (0 errors) + `astro build`.
- **Manual on prod after deploy (demo family only — verify `family_id == b8312b5a…` first):** open and cancel a destructive confirm (e.g. delete a budget category → Cancelar), open the chat "edit message" prompt and cancel, check the sheet on a phone-width viewport (bottom sheet, above the nav) and desktop (centered), check the cross-fade between two pages. The only writes: create one saved budget filter through the name prompt, then delete it through the confirm.

## Rollout

One PR → CI → merge → `deploy-onprem.sh` (frontend only, no migration) → the manual checks above.
