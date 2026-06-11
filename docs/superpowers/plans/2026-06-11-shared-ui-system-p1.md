# Shared UI System — Sub-project 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 6 reusable Astro UI components (`PageHeader`, `PageLayout`, `BottomSheet`, `EmptyState`, `SectionHeader`, `FormField`), document design tokens, and validate by migrating `parent/tasks.astro`.

**Architecture:** New components live in `frontend/src/components/ui/` alongside existing `Button.astro`, `Card.astro`, etc. `PageLayout` composes `Layout` + `PageHeader` + `BottomNav` to eliminate ~25 lines of boilerplate per page. Verification is build-time (Astro type-checks props at `astro build`) plus a visual smoke-check on the PoC page.

**Tech Stack:** Astro 5 (SSR, file-based routing) · Tailwind CSS v4 (`@theme` design tokens in `global.css`) · TypeScript strict mode · No new npm deps.

---

## Context for the implementer

Key files to read before starting:
- `frontend/src/styles/global.css` — all design tokens (`--color-brand-*`, `--shadow-card`, `--radius-card`, etc.)
- `frontend/src/layouts/Layout.astro` — base layout wrapper (title, lang, theme, body)
- `frontend/src/components/BottomNav.astro` — props: `active`, `role`, `lang`; already includes its own spacer div
- `frontend/src/components/ui/Button.astro` — the pattern for Astro component props (`class: className` destructure, `...rest` spread)
- `frontend/src/components/ui/Card.astro` — tone map pattern
- `frontend/src/pages/parent/tasks.astro` — the page we will migrate in Task 8

Path alias in `frontend/tsconfig.json`: `@components/*` → `./src/components/*`. Use this in page imports.

The `BottomNav` component already renders its own spacer div before the `<nav>`, so **do NOT add `BottomSpacer` in PageLayout** — it would double-space the bottom.

---

## File Map

**Create:**
- `docs/design-tokens.md`
- `frontend/src/components/ui/PageHeader.astro`
- `frontend/src/components/ui/PageLayout.astro`
- `frontend/src/components/ui/BottomSheet.astro`
- `frontend/src/components/ui/EmptyState.astro`
- `frontend/src/components/ui/SectionHeader.astro`
- `frontend/src/components/ui/FormField.astro`

**Modify:**
- `frontend/src/pages/parent/tasks.astro` — PoC migration (Task 8)

---

## Task 1: Design token reference doc

**Files:**
- Create: `docs/design-tokens.md`

- [ ] **Step 1: Create the doc**

```markdown
# Design Tokens

Reference for all CSS custom properties defined in `frontend/src/styles/global.css`.
Use these in Tailwind utility classes (e.g. `bg-brand-sky`, `shadow-[var(--shadow-card)]`)
or in raw CSS with `var(--shadow-card)`.

---

## Colors

| Token | Value | Tailwind class |
|-------|-------|----------------|
| `--color-brand-sky` | `#4FB8E6` | `bg-brand-sky` / `text-brand-sky` / `border-brand-sky` |
| `--color-brand-sky-deep` | `#2E9BCC` | `bg-brand-sky-deep` / `text-brand-sky-deep` |
| `--color-brand-coral` | `#FF8A65` | `bg-brand-coral` / `text-brand-coral` |
| `--color-brand-coral-deep` | `#E96A45` | `bg-brand-coral-deep` |
| `--color-brand-mint` | `#5DD4A8` | `bg-brand-mint` / `text-brand-mint` |
| `--color-brand-mint-deep` | `#3DB689` | `bg-brand-mint-deep` |
| `--color-brand-sun` | `#FFC857` | `bg-brand-sun` / `text-brand-sun` |
| `--color-brand-sun-deep` | `#E5A91F` | `bg-brand-sun-deep` |
| `--color-brand-ink` | `#1F2937` | `bg-brand-ink` / `text-brand-ink` / `border-brand-ink` |
| `--color-brand-ink-soft` | `#3B4252` | `text-brand-ink-soft` |
| `--color-brand-cream` | `#FFF8F0` | `bg-brand-cream` |
| `--color-brand-cream-deep` | `#F4E9D8` | `bg-brand-cream-deep` |

---

## Shadows (hard ink-drop, no blur)

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-card` | `4px 4px 0 #1F2937` | Default card/button shadow |
| `--shadow-pop` | `6px 6px 0 #1F2937` | Elevated card (modal, feature highlight) |
| `--shadow-stamp` | `8px 8px 0 #1F2937` | Extra-emphasis (hero element) |

In Tailwind: `shadow-[var(--shadow-card)]`

---

## Border radii

| Token | Value | Tailwind |
|-------|-------|----------|
| `--radius-card` | `22px` | `rounded-[var(--radius-card)]` |
| `--radius-tile` | `28px` | `rounded-[var(--radius-tile)]` or `rounded-b-[var(--radius-tile)]` |
| `--radius-pill` | `999px` | `rounded-full` |

---

## Semantic aliases (CSS variables, not Tailwind tokens)

Set at `:root`, overridden by `[data-theme="dark"]`.

| Variable | Light | Dark |
|----------|-------|------|
| `--bg` | `#FFF8F0` (cream) | `#0F1A24` |
| `--fg` | `#1F2937` (ink) | `#FFF8F0` (cream) |
| `--fg-soft` | `#3B4252` (ink-soft) | `#A8C3D4` |
| `--surface` | `#FFF8F0` | `#15222F` |
| `--surface-deep` | `#F4E9D8` | `#1C2D3E` |

Use with `color: var(--fg)` in raw CSS; prefer Tailwind brand-* tokens in components.

---

## Typography

| Variable | Value |
|----------|-------|
| `--font-display` | Plus Jakarta Sans (headings, `.font-display`) |
| `--font-sans` | Nunito (body, default) |

Use `font-display` for h1/h2/h3 and brand labels. Use `font-sans` (default) for body text.
```

- [ ] **Step 2: Commit**

```bash
git add docs/design-tokens.md
git commit -m "docs: add design token reference"
```

---

## Task 2: `PageHeader.astro`

The `<header>` block that appears at the top of every page, extracted into a component.

**Files:**
- Create: `frontend/src/components/ui/PageHeader.astro`

- [ ] **Step 1: Create the component**

```astro
---
interface Props {
  title: string;
  tone?: "sky" | "coral" | "mint" | "sun" | "cream";
  backHref?: string;
  lang?: string;
  class?: string;
}
const {
  title,
  tone = "sky",
  backHref,
  lang = "en",
  class: className = "",
} = Astro.props;

const bg = ({
  sky:   "bg-brand-sky",
  coral: "bg-brand-coral",
  mint:  "bg-brand-mint",
  sun:   "bg-brand-sun",
  cream: "bg-brand-cream",
} as Record<string, string>)[tone] ?? "bg-brand-sky";
---

<header class={`${bg} text-brand-ink border-b-4 border-brand-ink pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)] ${className}`}>
  {backHref && (
    <a
      href={backHref}
      class="text-brand-ink-soft hover:text-brand-ink text-sm font-bold flex items-center gap-1 mb-3"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      {lang === "es" ? "Volver" : "Back"}
    </a>
  )}
  <div class="flex items-center justify-between gap-3">
    <h1 class="font-display text-2xl font-extrabold text-brand-ink">{title}</h1>
    <slot name="actions" />
  </div>
  <slot />
</header>
```

Save to `frontend/src/components/ui/PageHeader.astro`.

Slot notes:
- Named slot `"actions"`: renders into the right side of the title row (CTA button, toggle, etc.)
- Default slot: renders below the title row (subtitle `<p>`, stat line, etc.)

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output (zero build errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/PageHeader.astro
git commit -m "feat(ui): add PageHeader component"
```

---

## Task 3: `PageLayout.astro`

Wraps `Layout` + `PageHeader` + `<main>` + `BottomNav` in a single component. Reduces every page from ~25 lines of boilerplate to ~3 prop lines.

**Files:**
- Create: `frontend/src/components/ui/PageLayout.astro`

- [ ] **Step 1: Create the component**

```astro
---
import Layout from "../../layouts/Layout.astro";
import PageHeader from "./PageHeader.astro";
import BottomNav from "../BottomNav.astro";

interface Props {
  title: string;
  tone?: "sky" | "coral" | "mint" | "sun" | "cream";
  backHref?: string;
  description?: string;
  role?: string;
  active?: "tasks" | "rewards" | "profile" | "parent" | "budget" | "notifications" | "pet" | "chat" | "gigs";
  lang?: string;
  mainClass?: string;
}

const {
  title,
  tone = "sky",
  backHref,
  description,
  role,
  active,
  lang = "en",
  mainClass = "flex-1 px-4 py-6",
} = Astro.props;
---

<Layout title={`${title} - Family Task Manager`} lang={lang} description={description}>
  <div class="flex flex-col min-h-dvh">
    <PageHeader title={title} tone={tone} backHref={backHref} lang={lang}>
      <slot name="actions" slot="actions" />
      <slot name="header-extra" />
    </PageHeader>
    <main class={mainClass}>
      <slot />
    </main>
    <BottomNav active={active} role={role} lang={lang} />
  </div>
</Layout>
```

Save to `frontend/src/components/ui/PageLayout.astro`.

Slot notes:
- Named slot `"actions"`: forwarded to PageHeader's `"actions"` slot (right of title row)
- Named slot `"header-extra"`: forwarded to PageHeader's default slot (below title row, for subtitles)
- Default slot: page body rendered inside `<main>`

Note: `BottomNav` already renders its own spacer `<div>` above the fixed nav, so no `BottomSpacer` is needed here.

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/PageLayout.astro
git commit -m "feat(ui): add PageLayout component"
```

---

## Task 4: `BottomSheet.astro`

Slide-up modal shell with a custom-event JS API. Establishes the pattern for all future modals. Does not replace existing modals — those migrate in sub-projects 2-5.

**Files:**
- Create: `frontend/src/components/ui/BottomSheet.astro`

- [ ] **Step 1: Create the component**

```astro
---
interface Props {
  id: string;
  title: string;
  lang?: string;
}
const { id, title } = Astro.props;
---

<div
  id={`${id}-backdrop`}
  class="hidden fixed inset-0 bg-black/50 z-40 transition-opacity duration-300"
></div>

<div
  id={id}
  role="dialog"
  aria-modal="true"
  aria-label={title}
  class="fixed bottom-0 left-0 right-0 z-50 translate-y-full transition-transform duration-300 ease-out bg-brand-cream rounded-t-[var(--radius-tile)] border-t-2 border-x-2 border-brand-ink shadow-[var(--shadow-pop)] flex flex-col max-h-[90dvh]"
>
  <div class="flex justify-center pt-3 pb-1 flex-shrink-0">
    <div class="w-10 h-1 rounded-full bg-brand-ink/20"></div>
  </div>
  <div class="flex items-center justify-between px-6 py-3 border-b border-brand-ink/10 flex-shrink-0">
    <h2 class="font-display text-lg font-extrabold text-brand-ink">{title}</h2>
    <button
      id={`${id}-close`}
      class="text-brand-ink-soft hover:text-brand-ink p-1 rounded-lg"
      aria-label="Close"
    >
      <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  </div>
  <div class="flex-1 overflow-y-auto">
    <slot />
  </div>
</div>

<script define:vars={{ id }}>
(function () {
  var panel = document.getElementById(id);
  var backdrop = document.getElementById(id + "-backdrop");
  var closeBtn = document.getElementById(id + "-close");

  function open() {
    backdrop.classList.remove("hidden");
    panel.classList.remove("translate-y-full");
    document.body.style.overflow = "hidden";
  }
  function close() {
    panel.classList.add("translate-y-full");
    backdrop.classList.add("hidden");
    document.body.style.overflow = "";
  }

  document.addEventListener("open-" + id, open);
  document.addEventListener("close-" + id, close);
  backdrop.addEventListener("click", close);
  closeBtn.addEventListener("click", close);
})();
</script>
```

Save to `frontend/src/components/ui/BottomSheet.astro`.

**Usage on the calling page:**
```javascript
// Open:
document.dispatchEvent(new Event("open-my-sheet"))
// Close:
document.dispatchEvent(new Event("close-my-sheet"))
```

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/BottomSheet.astro
git commit -m "feat(ui): add BottomSheet component"
```

---

## Task 5: `EmptyState.astro`

Centered empty-state block used when a list is empty. Generalizes the pattern on tasks/rewards pages.

**Files:**
- Create: `frontend/src/components/ui/EmptyState.astro`

- [ ] **Step 1: Create the component**

```astro
---
interface Props {
  icon: string;
  title: string;
  subtitle?: string;
  ctaLabel?: string;
  ctaId?: string;
  ctaHref?: string;
  ctaTone?: "sky" | "coral" | "mint";
}
const {
  icon,
  title,
  subtitle,
  ctaLabel,
  ctaId,
  ctaHref,
  ctaTone = "sky",
} = Astro.props;

const ctaBg = ({
  sky:   "bg-brand-sky hover:bg-brand-sky-deep",
  coral: "bg-brand-coral hover:bg-brand-coral-deep",
  mint:  "bg-brand-mint hover:bg-brand-mint-deep",
} as Record<string, string>)[ctaTone] ?? "bg-brand-sky hover:bg-brand-sky-deep";

const ctaClass = `press inline-flex items-center px-5 py-2.5 ${ctaBg} text-brand-ink font-extrabold text-sm rounded-full border-2 border-brand-ink shadow-[var(--shadow-card)] transition-colors cursor-pointer`;
---

<div class="flex flex-col items-center justify-center py-10 text-center">
  <p class="text-4xl mb-3" aria-hidden="true">{icon}</p>
  <p class="font-display font-extrabold text-brand-ink mb-1">{title}</p>
  {subtitle && <p class="text-sm text-brand-ink-soft mb-4">{subtitle}</p>}
  {ctaLabel && ctaId && (
    <button id={`${ctaId}-empty-cta`} class={ctaClass}>{ctaLabel}</button>
  )}
  {ctaLabel && !ctaId && ctaHref && (
    <a href={ctaHref} class={ctaClass}>{ctaLabel}</a>
  )}
</div>

{ctaId && (
  <script define:vars={{ ctaId }}>
  (function () {
    document.addEventListener("astro:page-load", function () {
      var emptyCta = document.getElementById(ctaId + "-empty-cta");
      var target = document.getElementById(ctaId);
      if (emptyCta && target) {
        emptyCta.addEventListener("click", function () { target.click(); });
      }
    }, { once: true });
  })();
  </script>
)}
```

Save to `frontend/src/components/ui/EmptyState.astro`.

When both `ctaId` and `ctaHref` are provided, `ctaId` takes precedence (rendered as a button that clicks the target element).

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/EmptyState.astro
git commit -m "feat(ui): add EmptyState component"
```

---

## Task 6: `SectionHeader.astro`

Consistent `<h2>` with optional "See all" link, used before any list or grid in a page.

**Files:**
- Create: `frontend/src/components/ui/SectionHeader.astro`

- [ ] **Step 1: Create the component**

```astro
---
interface Props {
  title: string;
  href?: string;
  lang?: string;
}
const { title, href, lang = "en" } = Astro.props;
---

<div class="flex items-center justify-between mb-3">
  <h2 class="font-display text-lg font-extrabold text-brand-ink">{title}</h2>
  {href && (
    <a href={href} class="text-sm text-brand-sky-deep font-semibold hover:underline">
      {lang === "es" ? "Ver todo" : "See all"} →
    </a>
  )}
</div>
```

Save to `frontend/src/components/ui/SectionHeader.astro`.

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/SectionHeader.astro
git commit -m "feat(ui): add SectionHeader component"
```

---

## Task 7: `FormField.astro`

Label + input wrapper with inline error display. Use for any `<input>` field in forms.

**Files:**
- Create: `frontend/src/components/ui/FormField.astro`

- [ ] **Step 1: Create the component**

```astro
---
interface Props {
  label: string;
  name: string;
  type?: string;
  error?: string;
  required?: boolean;
  class?: string;
  inputClass?: string;
  [key: string]: any;
}
const {
  label,
  name,
  type = "text",
  error,
  required = false,
  class: className = "",
  inputClass = "",
  ...rest
} = Astro.props;
---

<div class={`flex flex-col gap-1 ${className}`}>
  <label for={name} class="text-sm font-semibold text-brand-ink">
    {label}{required && <span class="text-brand-coral ml-0.5" aria-hidden="true">*</span>}
  </label>
  <input
    id={name}
    name={name}
    type={type}
    required={required || undefined}
    class={`w-full border-2 border-brand-ink rounded-xl px-4 py-2.5 bg-brand-cream focus:outline-none focus:ring-2 focus:ring-brand-sky font-sans ${inputClass}`}
    {...rest}
  />
  {error && <p class="text-xs text-red-600 font-medium" role="alert">{error}</p>}
</div>
```

Save to `frontend/src/components/ui/FormField.astro`.

Note: `required={required || undefined}` — Astro renders `required` as a boolean attribute when truthy; passing `undefined` suppresses the attribute when false, which is correct HTML behavior.

- [ ] **Step 2: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/FormField.astro
git commit -m "feat(ui): add FormField component"
```

---

## Task 8: PoC migration — `parent/tasks.astro`

Validate the new component API by migrating the tasks page. The page logic is unchanged — only imports and markup structure change.

**Files:**
- Modify: `frontend/src/pages/parent/tasks.astro`

- [ ] **Step 1: Read the current file**

Read `frontend/src/pages/parent/tasks.astro` in full before editing.

- [ ] **Step 2: Update imports (frontmatter, lines 1-6)**

Replace:
```astro
import Layout from "../../layouts/Layout.astro";
import BottomNav from "../../components/BottomNav.astro";
import TaskCreateModal from "../../components/TaskCreateModal.astro";
import DifficultyChip from "../../components/DifficultyChip.astro";
import { apiFetch } from "../../lib/api";
import { t } from "../../lib/i18n";
```

With:
```astro
import PageLayout from "@components/ui/PageLayout.astro";
import EmptyState from "@components/ui/EmptyState.astro";
import TaskCreateModal from "../../components/TaskCreateModal.astro";
import DifficultyChip from "../../components/DifficultyChip.astro";
import { apiFetch } from "../../lib/api";
import { t } from "../../lib/i18n";
```

- [ ] **Step 3: Replace the outer Layout + header + main + BottomNav wrapper**

The current template structure (lines 92-293) is:
```astro
<Layout title={`${t(lang, "pt_title")} - Family Task Manager`}>
  <div class="w-full max-w-md md:max-w-4xl lg:max-w-6xl mx-auto bg-brand-cream-deep flex flex-col">
    <header class="bg-brand-sky text-brand-ink border-b-4 border-brand-ink pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]">
      <a href="/parent" class="text-brand-ink-soft hover:text-brand-ink text-sm font-bold flex items-center gap-1 mb-3">
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
        </svg>
        {t(lang, "back_parent")}
      </a>
      <div class="flex items-center justify-between gap-3">
        <h1 class="font-display text-2xl font-extrabold text-brand-ink">{t(lang, "pt_title")}</h1>
        <button
          id="tcm-trigger"
          class="press h-10 w-10 rounded-full bg-brand-sky-deep border-2 border-brand-ink shadow-[var(--shadow-card)] text-white flex items-center justify-center text-xl font-bold flex-shrink-0"
          aria-label={lang === "es" ? "Nueva tarea" : "New task"}
        >+</button>
      </div>
      <p class="text-brand-ink-soft text-sm mt-1 font-sans">
        {t(lang, "pt_templates_in_family")(templateList.length)}
      </p>
    </header>

    <main class="flex-1 px-4 py-6 space-y-6">
      ... page body ...
    </main>

    <BottomNav active="parent" role={user.role} lang={lang} />
  </div>
```

Replace with:
```astro
<PageLayout
  title={t(lang, "pt_title") as string}
  tone="sky"
  backHref="/parent"
  role={user.role}
  active="parent"
  lang={lang}
  mainClass="flex-1 px-4 py-6 space-y-6"
>
  <button
    slot="actions"
    id="tcm-trigger"
    class="press h-10 w-10 rounded-full bg-brand-sky-deep border-2 border-brand-ink shadow-[var(--shadow-card)] text-white flex items-center justify-center text-xl font-bold flex-shrink-0"
    aria-label={lang === "es" ? "Nueva tarea" : "New task"}
  >+</button>
  <p slot="header-extra" class="text-brand-ink-soft text-sm mt-1 font-sans">
    {t(lang, "pt_templates_in_family")(templateList.length)}
  </p>

  ... page body (unchanged) ...

</PageLayout>
```

Close the old `</div>` + `</Layout>` becomes just `</PageLayout>`.

- [ ] **Step 4: Replace the inline empty state with `<EmptyState>`**

Find this block inside the template list section (inside `{templateList.length === 0 ? (` branch):
```astro
<div class="text-center py-10">
  <p class="text-4xl mb-3">📋</p>
  <p class="font-semibold text-brand-ink mb-1">
    {lang === "es" ? "Ninguna tarea todavía" : "No tasks yet"}
  </p>
  <p class="text-sm text-brand-ink-soft mb-4">
    {lang === "es" ? "Crea la primera para empezar" : "Create the first one to get started"}
  </p>
  <button
    id="open-create-template"
    class="bg-brand-sky text-white font-semibold px-5 py-2 rounded-xl hover:bg-brand-sky-deep transition-colors"
  >
    {lang === "es" ? "+ Crear tarea" : "+ Create task"}
  </button>
</div>
```

Replace with:
```astro
<EmptyState
  icon="📋"
  title={lang === "es" ? "Ninguna tarea todavía" : "No tasks yet"}
  subtitle={lang === "es" ? "Crea la primera para empezar" : "Create the first one to get started"}
  ctaLabel={lang === "es" ? "+ Crear tarea" : "+ Create task"}
  ctaId="tcm-trigger"
/>
```

The existing `document.getElementById("open-create-template")?.addEventListener("click", ...)` script can be removed since `EmptyState` handles the delegation via `ctaId`.

- [ ] **Step 5: Remove the stale script line**

In the `<script>` block at the bottom of the file, find and remove:
```javascript
document.getElementById("open-create-template")?.addEventListener("click", () => {
    document.getElementById("tcm-trigger")?.click();
});
```

This is handled automatically by `EmptyState`'s `ctaId` prop.

- [ ] **Step 6: Verify build passes**

```bash
cd frontend && npm run build 2>&1 | grep -E "^.*error" | head -20
```

Expected: no output. If there are TypeScript errors about `t(lang, "pt_title")` returning `string | Function`, add `as string` cast.

- [ ] **Step 7: Visual smoke check**

Start the dev server (or use a running local stack) and navigate to `http://localhost:3003/parent/tasks` (logged in as a PARENT role user). Verify:
- Header renders with sky background, back arrow to `/parent`, title, + button on right
- Subtitle line (template count) appears below title
- If no templates exist: EmptyState renders with 📋 icon and "+ Create task" button that opens the task create modal
- If templates exist: list renders normally
- BottomNav at bottom with "Manage" tab highlighted

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/parent/tasks.astro
git commit -m "refactor(parent/tasks): migrate to PageLayout + EmptyState"
```
