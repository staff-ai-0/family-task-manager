# UX Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add view transitions, toast notifications, and skeleton loaders to transform page navigation from full-reload to SPA-like smoothness.

**Architecture:** Astro's built-in `<ClientRouter />` handles view transitions. A lightweight toast module (`toast.ts`) manages notifications via DOM manipulation. Skeleton loaders use Tailwind's `animate-pulse`. All changes are frontend-only.

**Tech Stack:** Astro 5.17, Tailwind CSS v4.2, TypeScript

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/lib/toast.ts` | Toast API: `showToast(msg, type, duration)` |
| Create | `frontend/src/components/ToastContainer.astro` | Fixed-position mount point for toasts |
| Create | `frontend/src/components/SkeletonLoader.astro` | Reusable skeleton with `line`/`card`/`row` variants |
| Modify | `frontend/src/layouts/Layout.astro` | Add `<ClientRouter />`, `<ToastContainer />`, persist BottomNav |
| Modify | `frontend/src/styles/global.css` | Toast slide-in + countdown animations |
| Modify | 28 `.astro` files with inline scripts | Wrap DOM listeners in `astro:page-load` |
| Modify | ~10 files with `alert()` | Replace with `showToast()` |

---

### Task 1: Create Toast Module

**Files:**
- Create: `frontend/src/lib/toast.ts`

- [ ] **Step 1: Create toast.ts**

```typescript
// frontend/src/lib/toast.ts

const SPINNER_SVG = `<svg class="animate-spin h-4 w-4 mx-auto" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>`;

type ToastType = 'success' | 'error' | 'info';

const ICONS: Record<ToastType, string> = {
  success: `<svg class="w-5 h-5 text-green-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`,
  error: `<svg class="w-5 h-5 text-red-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`,
  info: `<svg class="w-5 h-5 text-blue-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
};

const BORDER_COLORS: Record<ToastType, string> = {
  success: 'border-green-500',
  error: 'border-red-500',
  info: 'border-blue-500',
};

const BAR_COLORS: Record<ToastType, string> = {
  success: 'bg-green-500',
  error: 'bg-red-500',
  info: 'bg-blue-500',
};

const MAX_VISIBLE = 3;

export function showToast(message: string, type: ToastType = 'info', durationMs: number = 4000): void {
  const container = document.getElementById('toast-container');
  if (!container) return;

  // Enforce max visible
  while (container.children.length >= MAX_VISIBLE) {
    container.removeChild(container.firstChild!);
  }

  const toast = document.createElement('div');
  toast.className = `pointer-events-auto bg-white border-l-4 ${BORDER_COLORS[type]} shadow-lg rounded-lg p-4 flex items-start gap-3 animate-slide-in relative overflow-hidden`;
  toast.style.cssText = `--toast-duration: ${durationMs}ms`;
  toast.innerHTML = `
    ${ICONS[type]}
    <p class="text-sm text-slate-700 flex-1">${escapeHtml(message)}</p>
    <button class="text-slate-400 hover:text-slate-600 text-lg leading-none flex-shrink-0">&times;</button>
    <div class="absolute bottom-0 left-0 h-0.5 ${BAR_COLORS[type]} animate-countdown"></div>
  `;

  // Click to dismiss
  toast.querySelector('button')!.addEventListener('click', () => remove(toast));

  // Auto-dismiss
  const timer = setTimeout(() => remove(toast), durationMs);
  toast.addEventListener('mouseenter', () => clearTimeout(timer));

  container.appendChild(toast);
}

function remove(el: HTMLElement): void {
  el.style.opacity = '0';
  el.style.transform = 'translateX(100%)';
  el.style.transition = 'opacity 0.2s, transform 0.2s';
  setTimeout(() => el.remove(), 200);
}

function escapeHtml(s: string): string {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

/** Spinner HTML constant for button loading states */
export { SPINNER_SVG };
```

- [ ] **Step 2: Verify file was created**

Run: `ls -la frontend/src/lib/toast.ts`
Expected: file exists

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/toast.ts
git commit -m "feat: add toast notification module"
```

---

### Task 2: Create ToastContainer and SkeletonLoader Components

**Files:**
- Create: `frontend/src/components/ToastContainer.astro`
- Create: `frontend/src/components/SkeletonLoader.astro`

- [ ] **Step 1: Create ToastContainer.astro**

```astro
---
// ToastContainer.astro — fixed mount point for toast notifications.
// Add once in Layout.astro. Uses transition:persist to survive page navigation.
---
<div
  id="toast-container"
  class="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-80 pointer-events-none"
  transition:persist
>
</div>
```

- [ ] **Step 2: Create SkeletonLoader.astro**

```astro
---
// SkeletonLoader.astro — reusable loading placeholder.
// Uses Tailwind's built-in animate-pulse.
interface Props {
  variant?: 'line' | 'card' | 'row';
  count?: number;
}
const { variant = 'line', count = 3 } = Astro.props;
---

{variant === 'line' && (
  <div class="space-y-3">
    {Array.from({ length: count }).map((_, i) => (
      <div class={`h-4 bg-slate-200 rounded animate-pulse ${i % 2 === 0 ? 'w-3/4' : 'w-1/2'}`}></div>
    ))}
  </div>
)}

{variant === 'card' && (
  <div class="space-y-3">
    {Array.from({ length: count }).map(() => (
      <div class="h-24 bg-slate-200 rounded-lg animate-pulse"></div>
    ))}
  </div>
)}

{variant === 'row' && (
  <div class="space-y-2">
    {Array.from({ length: count }).map(() => (
      <div class="flex gap-4 items-center py-3">
        <div class="h-4 bg-slate-200 rounded animate-pulse w-24"></div>
        <div class="h-4 bg-slate-200 rounded animate-pulse flex-1"></div>
        <div class="h-4 bg-slate-200 rounded animate-pulse w-20"></div>
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ToastContainer.astro frontend/src/components/SkeletonLoader.astro
git commit -m "feat: add ToastContainer and SkeletonLoader components"
```

---

### Task 3: Add Toast Animations to Global CSS

**Files:**
- Modify: `frontend/src/styles/global.css`

- [ ] **Step 1: Add toast animations after existing styles**

Append after line 33 (closing brace of `.app-shell`):

```css
/* Toast notification animations */
@keyframes slide-in {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
@keyframes countdown {
  from { width: 100%; }
  to { width: 0%; }
}
.animate-slide-in {
  animation: slide-in 0.2s ease-out;
}
.animate-countdown {
  animation: countdown var(--toast-duration, 4s) linear forwards;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/styles/global.css
git commit -m "feat: add toast slide-in and countdown animations"
```

---

### Task 4: Wire Up Layout — ClientRouter, ToastContainer, Persist BottomNav

**Files:**
- Modify: `frontend/src/layouts/Layout.astro`

This is the core integration task. Three changes to Layout.astro:

- [ ] **Step 1: Add ClientRouter and ToastContainer imports to frontmatter**

In `frontend/src/layouts/Layout.astro`, change the frontmatter (lines 1-13) to add imports:

```astro
---
import "../styles/global.css";
import { ClientRouter } from "astro:transitions";
import { t } from "../lib/i18n";
import ToastContainer from "../components/ToastContainer.astro";
interface Props {
	title?: string;
	description?: string;
	lang?: string;
}
const lang = Astro.props.lang ?? Astro.cookies.get("lang")?.value ?? "en";
const {
	title = "Family Task Manager",
	description = t(lang, "meta_description") as string,
} = Astro.props;
```

(The `bannerCopy` block stays unchanged after this.)

- [ ] **Step 2: Add ClientRouter to head**

Change the `<head>` section (lines 31-39) to include `<ClientRouter />`:

```html
	<head>
		<meta charset="UTF-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1.0" />
		<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
		<link rel="icon" href="/favicon.ico" />
		<meta name="generator" content={Astro.generator} />
		<meta name="description" content={description} />
		<title>{title}</title>
		<ClientRouter />
	</head>
```

- [ ] **Step 3: Add ToastContainer to body and wrap main content with fade transition**

Change the body content (lines 40-62) to:

```html
<body class="bg-slate-50 text-slate-900 antialiased">
    <ToastContainer />

    <!-- Email verification banner (hidden by default, shown client-side if needed) -->
    <div
        id="verify-banner"
        class="hidden w-full bg-amber-50 border-b border-amber-200 px-4 py-2.5 text-sm text-amber-800 flex items-center justify-center gap-3"
    >
        <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{bannerCopy.msg}</span>
        <button
            id="resend-verify-btn"
            class="underline font-medium hover:text-amber-900 transition-colors whitespace-nowrap"
        >
            {bannerCopy.resend}
        </button>
    </div>

    <div class="app-shell" transition:animate="fade">
        <slot />
    </div>
    <slot name="overlays" />
```

- [ ] **Step 4: Wrap Layout.astro's own script in astro:page-load**

Change the script block (lines 64-88) to:

```html
    <script define:vars={{ sentLabel: bannerCopy.sent, resendLabel: bannerCopy.resend }}>
        document.addEventListener('astro:page-load', () => {
            (async () => {
                try {
                    const res = await fetch("/api/auth/me-status");
                    if (!res.ok) return;
                    const { verified } = await res.json();
                    if (!verified) {
                        document.getElementById("verify-banner")?.classList.remove("hidden");
                    }
                } catch { /* silently ignore */ }
            })();

            document.getElementById("resend-verify-btn")?.addEventListener("click", async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = "...";
                try {
                    await fetch("/api/auth/resend-verification", { method: "POST" });
                    btn.textContent = sentLabel;
                } catch {
                    btn.textContent = resendLabel;
                    btn.disabled = false;
                }
            });
        });
    </script>
</body>
```

- [ ] **Step 5: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds with no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/layouts/Layout.astro
git commit -m "feat: integrate ClientRouter, ToastContainer, and fade transitions"
```

---

### Task 5: Add transition:persist to BottomNav

**Files:**
- Modify: Every page that renders `<BottomNav>` — but BottomNav itself needs the attribute.

Since BottomNav is rendered by individual pages (not Layout.astro), we add `transition:persist` to the BottomNav component's root elements.

- [ ] **Step 1: Add transition:persist to BottomNav.astro**

In `frontend/src/components/BottomNav.astro`, add `transition:persist` to both the spacer and nav elements.

Change the spacer div (line 15):
```html
<div class="bottom-nav-spacer" aria-hidden="true" transition:persist="bottom-nav-spacer"></div>
```

Change the nav element (lines 17-18):
```html
<nav
    class="fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 safe-area-bottom z-50"
    transition:persist="bottom-nav"
>
```

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BottomNav.astro
git commit -m "feat: persist BottomNav across view transitions"
```

---

### Task 6: Wrap Inline Scripts in astro:page-load — Auth & Core Pages

**Files:**
- Modify: `frontend/src/pages/login.astro`
- Modify: `frontend/src/pages/register.astro`
- Modify: `frontend/src/pages/forgot-password.astro`
- Modify: `frontend/src/pages/reset-password.astro`
- Modify: `frontend/src/pages/accept-invitation.astro`
- Modify: `frontend/src/pages/index.astro`
- Modify: `frontend/src/pages/payment.astro`

For each file, the transformation is mechanical:

1. Find the `<script>` or `<script is:inline>` block
2. Wrap all DOM-dependent code inside `document.addEventListener('astro:page-load', () => { ... });`
3. Add optional chaining (`?.`) to `querySelector` / `getElementById` calls
4. Replace `alert()` calls with `showToast()` from `../lib/toast.ts`

**Important:** Scripts with `is:inline` cannot use ES module imports. For those files, change `<script is:inline>` to `<script>` (removing `is:inline`) so they can import `showToast`. If the script uses `define:vars`, keep `is:inline` and access `showToast` via `window.__showToast` (set by a separate module script).

- [ ] **Step 1: Update login.astro**

In `frontend/src/pages/login.astro`, replace the entire `<script is:inline>` block (lines 210-271) with:

```html
    <script>
        import { showToast } from '../lib/toast';

        window.handleGoogleLogin = async function(response) {
            try {
                const credential = response.credential;
                const result = await fetch('/api/oauth/google', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: credential, join_code: null }),
                });

                const data = await result.json();

                if (result.ok) {
                    window.location.href = '/dashboard';
                } else {
                    const errorMsg = data.message || data.detail || 'Login failed';
                    showToast(errorMsg, 'error');
                }
            } catch (error) {
                console.error('Google login error:', error);
                showToast('An error occurred during login', 'error');
            }
        };

        document.addEventListener('astro:page-load', () => {
            const loginForm = document.getElementById('login-form');
            if (loginForm) {
                loginForm.addEventListener('submit', async function(e) {
                    e.preventDefault();

                    const email = document.getElementById('email')?.value;
                    const password = document.getElementById('password')?.value;
                    const submitBtn = document.getElementById('login-submit-btn');
                    if (!submitBtn) return;
                    const originalHTML = submitBtn.innerHTML;

                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<svg class="animate-spin h-4 w-4 mx-auto" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>';

                    try {
                        const response = await fetch('/api/auth/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ email, password }),
                        });

                        const data = await response.json();

                        if (data.success && data.redirect) {
                            window.location.href = data.redirect;
                        } else {
                            showToast(data.error || 'Login failed', 'error');
                            submitBtn.disabled = false;
                            submitBtn.innerHTML = originalHTML;
                        }
                    } catch (error) {
                        console.error('Login error:', error);
                        showToast('An error occurred', 'error');
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = originalHTML;
                    }
                });
            }
        });
    </script>
```

- [ ] **Step 2: Update remaining auth pages**

For `register.astro`, `forgot-password.astro`, `reset-password.astro`, `accept-invitation.astro`, `index.astro`, and `payment.astro` — apply the same mechanical transformation:

1. Change `<script is:inline>` to `<script>` (if applicable)
2. Add `import { showToast } from '../lib/toast';` at the top of the script
3. Wrap DOM-dependent code in `document.addEventListener('astro:page-load', () => { ... });`
4. Replace every `alert(msg)` with `showToast(msg, 'error')` or `showToast(msg, 'info')` as appropriate
5. Replace `btn.textContent = '...'` with the spinner SVG pattern

- [ ] **Step 3: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/login.astro frontend/src/pages/register.astro frontend/src/pages/forgot-password.astro frontend/src/pages/reset-password.astro frontend/src/pages/accept-invitation.astro frontend/src/pages/index.astro frontend/src/pages/payment.astro
git commit -m "feat: wrap auth page scripts in astro:page-load, replace alert with toast"
```

---

### Task 7: Wrap Inline Scripts — Budget Pages

**Files:**
- Modify: `frontend/src/pages/budget/transactions.astro`
- Modify: `frontend/src/pages/budget/import.astro`
- Modify: `frontend/src/pages/budget/month/[year]/[month].astro`
- Modify: `frontend/src/pages/budget/accounts/[id].astro`
- Modify: `frontend/src/pages/budget/accounts/[id]/reconcile.astro`
- Modify: `frontend/src/pages/budget/categories/index.astro`
- Modify: `frontend/src/pages/budget/reports/budget-analysis.astro`

Same mechanical transformation as Task 6 for each file:

- [ ] **Step 1: Update each budget page script block**

For each file:
1. Change `<script is:inline>` to `<script>` where possible
2. Add `import { showToast } from '../../lib/toast';` (adjust path depth per file location)
3. Wrap DOM listeners in `document.addEventListener('astro:page-load', () => { ... });`
4. Replace `alert()` calls with `showToast()`
5. Replace `btn.textContent = '...'` with spinner SVG

**Path depth guide:**
- `pages/budget/*.astro` → `import { showToast } from '../../lib/toast';`
- `pages/budget/month/[year]/[month].astro` → `import { showToast } from '../../../../lib/toast';`
- `pages/budget/accounts/[id].astro` → `import { showToast } from '../../../lib/toast';`
- `pages/budget/accounts/[id]/reconcile.astro` → `import { showToast } from '../../../../lib/toast';`
- `pages/budget/categories/index.astro` → `import { showToast } from '../../../lib/toast';`
- `pages/budget/reports/*.astro` → `import { showToast } from '../../../lib/toast';`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/budget/
git commit -m "feat: wrap budget page scripts in astro:page-load, replace alert with toast"
```

---

### Task 8: Wrap Inline Scripts — Budget Settings Pages

**Files:**
- Modify: `frontend/src/pages/budget/settings/rules.astro`
- Modify: `frontend/src/pages/budget/settings/recurring.astro`
- Modify: `frontend/src/pages/budget/settings/payees.astro`
- Modify: `frontend/src/pages/budget/settings/backups.astro`

- [ ] **Step 1: Update each settings page**

Same transformation. Import path: `import { showToast } from '../../../lib/toast';`

Key `alert()` replacements:
- `rules.astro:485`: `alert(err.detail)` → `showToast(err.detail ?? 'Error', 'error')`
- `recurring.astro:581`: `alert(err.detail)` → `showToast(err.detail ?? 'Error', 'error')`
- `payees.astro:165`: `alert(err.detail)` → `showToast(err.detail || 'Error', 'error')`
- `backups.astro:175,180,185,192`: `alert("coming soon")` → `showToast(msg, 'info')`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/budget/settings/
git commit -m "feat: wrap budget settings scripts in astro:page-load, replace alert with toast"
```

---

### Task 9: Wrap Inline Scripts — Components

**Files:**
- Modify: `frontend/src/components/AssignFundsModal.astro`
- Modify: `frontend/src/components/RecycleBinTable.astro`
- Modify: `frontend/src/components/InvitationModal.astro`
- Modify: `frontend/src/components/EditMemberModal.astro`
- Modify: `frontend/src/components/PointsConverter.astro`

- [ ] **Step 1: Update each component**

Same transformation. Import path: `import { showToast } from '../lib/toast';`

Key `alert()` replacements:
- `PointsConverter.astro:260`: `alert(...)` → `showToast(msg, 'error')`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AssignFundsModal.astro frontend/src/components/RecycleBinTable.astro frontend/src/components/InvitationModal.astro frontend/src/components/EditMemberModal.astro frontend/src/components/PointsConverter.astro
git commit -m "feat: wrap component scripts in astro:page-load, replace alert with toast"
```

---

### Task 10: Wrap Inline Scripts — Parent Pages

**Files:**
- Modify: `frontend/src/pages/parent/members.astro`
- Modify: `frontend/src/pages/parent/tasks/[id]/edit.astro`
- Modify: `frontend/src/pages/parent/finances/accounts/[id]/reconcile.astro`
- Modify: `frontend/src/pages/parent/finances/categories/index.astro`
- Modify: `frontend/src/pages/parent/finances/month/[year]/[month].astro`

- [ ] **Step 1: Update each parent page**

Same transformation. Adjust import paths per file depth.

Key `alert()` replacements:
- `members.astro:505`: `alert(...)` → `showToast(msg, 'error')`
- `members.astro:525`: `alert(...)` → `showToast(msg, 'error')`
- `members.astro:529`: `alert(...)` → `showToast(msg, 'error')`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/parent/
git commit -m "feat: wrap parent page scripts in astro:page-load, replace alert with toast"
```

---

### Task 11: Add Skeleton Loaders to Key Pages

**Files:**
- Modify: `frontend/src/pages/budget/transactions.astro`

- [ ] **Step 1: Add skeleton to transaction list filter area**

In `frontend/src/pages/budget/transactions.astro`, find the transaction list container (the element that gets repopulated after filter/search). Add a skeleton that shows during client-side fetches.

Import the component in frontmatter:
```astro
import SkeletonLoader from '../../components/SkeletonLoader.astro';
```

Add a hidden skeleton div next to the transaction list:
```html
<div id="txn-skeleton" class="hidden">
    <SkeletonLoader variant="row" count={5} />
</div>
```

In the script block, before fetching filtered results:
```javascript
document.getElementById('txn-skeleton')?.classList.remove('hidden');
document.getElementById('txn-list')?.classList.add('hidden');
```

After results arrive:
```javascript
document.getElementById('txn-skeleton')?.classList.add('hidden');
document.getElementById('txn-list')?.classList.remove('hidden');
```

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/budget/transactions.astro frontend/src/components/SkeletonLoader.astro
git commit -m "feat: add skeleton loader to budget transaction list"
```

---

### Task 12: Final Build + Manual Smoke Test

- [ ] **Step 1: Full build**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds with zero errors

- [ ] **Step 2: Start services and smoke test**

Run: `docker compose up -d`

Manual checks:
1. Navigate between Dashboard → Rewards → Profile → Budget — verify smooth fade transition, no white flash
2. Verify bottom nav stays fixed and doesn't remount (active state persists correctly)
3. Try a bad login — verify toast appears top-right, auto-dismisses after 4s
4. Go to budget settings → backups → click export — verify "coming soon" toast
5. Filter budget transactions — verify skeleton shows during load
6. Click toast dismiss button — verify it slides out

- [ ] **Step 3: Run e2e tests**

Run: `cd e2e-tests && npm run test 2>&1 | tail -20`
Expected: Existing tests pass (DOM structure unchanged, only navigation behavior changed)

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address smoke test findings"
```
