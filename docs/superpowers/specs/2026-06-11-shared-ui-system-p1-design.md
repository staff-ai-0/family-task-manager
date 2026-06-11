# Shared UI System — Sub-project 1: Component Library

## Goal

Build 6 missing reusable Astro components that eliminate the most pervasive copy-paste patterns across the app's 89 pages, document design tokens, and validate the new API by migrating one representative page (`parent/tasks.astro`).

Sub-projects 2-5 (page migrations) depend on this library being stable.

---

## Design Tokens Reference

`docs/design-tokens.md` — lightweight markdown doc listing all CSS variables defined in `frontend/src/styles/global.css` and their intended usage. Not a Storybook; just a reference table so contributors don't hunt through CSS to find token names.

Sections:
- Colors (`--color-brand-*`)
- Shadows (`--shadow-card`, `--shadow-pop`, `--shadow-stamp`)
- Radii (`--radius-card`, `--radius-tile`, `--radius-pill`)
- Semantic aliases (`--bg`, `--fg`, `--fg-soft`, `--surface`)

---

## New Components

All new components go in `frontend/src/components/ui/`. Existing components (`Button.astro`, `Card.astro`, `Badge.astro`, `RoleBadge.astro`) are unchanged.

---

### `PageHeader.astro`

Extracted from the copy-paste `<header class="bg-brand-sky ... pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]">` found in 8 pages.

```typescript
interface Props {
  title: string
  tone?: "sky" | "coral" | "mint" | "sun" | "cream"  // default: "sky"
  backHref?: string     // renders ← back link when provided
  lang?: string         // for back link label ("Volver" / "Back")
  class?: string        // extra classes on the outer <header>
}
// Named slot: "actions" — right-side element (CTA button, toggle, etc.)
```

Output structure:
```html
<header class="bg-brand-{tone} text-brand-ink border-b-4 border-brand-ink pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)] {class}">
  <!-- backHref renders ← back link -->
  <div class="flex items-center justify-between">
    <h1 class="font-display text-2xl font-extrabold text-brand-ink">{title}</h1>
    <slot name="actions" />
  </div>
</header>
```

Tone map: `sky → bg-brand-sky`, `coral → bg-brand-coral`, `mint → bg-brand-mint`, `sun → bg-brand-sun`, `cream → bg-brand-cream`.

---

### `PageLayout.astro`

Wraps `Layout` + `PageHeader` + `<main>` + `BottomNav` + `BottomSpacer`. Reduces page boilerplate from ~25 lines to ~3 lines.

```typescript
interface Props {
  // PageHeader props
  title: string
  tone?: "sky" | "coral" | "mint" | "sun" | "cream"
  backHref?: string
  // Layout props
  description?: string
  // BottomNav props
  role?: string
  active?: "tasks" | "rewards" | "profile" | "parent" | "budget" | "notifications" | "pet" | "chat" | "gigs"
  // Shared
  lang?: string
  // main element
  mainClass?: string    // extra classes on <main> (default: "flex-1 px-4 py-6")
}
// Named slot: "actions" — forwarded to PageHeader's "actions" slot
// Default slot: page body (rendered inside <main>)
```

Output structure:
```astro
<Layout title="{title} - Family Task Manager" lang={lang} description={description}>
  <div class="flex flex-col min-h-dvh">
    <PageHeader title={title} tone={tone} backHref={backHref} lang={lang}>
      <slot name="actions" slot="actions" />
    </PageHeader>
    <main class={mainClass ?? "flex-1 px-4 py-6"}>
      <slot />
    </main>
    <BottomNav active={active} role={role} lang={lang} />
    <BottomSpacer />
  </div>
</Layout>
```

Usage on a migrated page:
```astro
<PageLayout title="Tasks" tone="sky" backHref="/parent" role={user.role} active="parent" lang={lang}>
  <button slot="actions" id="tcm-trigger" class="press h-10 w-10 ...">+</button>
  <!-- page body -->
</PageLayout>
```

---

### `BottomSheet.astro`

Canonical shell for slide-up modals. Does not replace existing modal components — establishes the pattern for new code. Existing modals (`FABModal`, etc.) migrate in sub-projects 2-5.

```typescript
interface Props {
  id: string        // unique string; backdrop gets id="${id}-backdrop"
  title: string
  lang?: string
}
// Default slot: modal body content
```

Generates:
- Backdrop `<div id="${id}-backdrop">` — `fixed inset-0 bg-black/50 z-40`, hidden by default, opacity fade transition
- Panel `<div id="${id}" role="dialog" aria-modal="true">` — `fixed bottom-0 left-0 right-0 z-50`, translate-y-full → translate-y-0 transition
- Drag handle strip
- Title row with `×` close button (`id="${id}-close"`)
- `<slot />` for body

**JS (inline in component):** Listens for a custom event `open-${id}` on `document` to open; `close-${id}` to close. Backdrop click and × button trigger close. Callers dispatch:
```javascript
document.dispatchEvent(new Event("open-invite-modal"))
```

---

### `EmptyState.astro`

Generalizes the empty-state pattern added to `parent/tasks.astro` and `parent/rewards.astro`.

```typescript
interface Props {
  icon: string          // emoji: "📋", "🏆", "💸", etc.
  title: string
  subtitle?: string
  ctaLabel?: string     // renders CTA button when set
  ctaId?: string        // if set, CTA click dispatches click on element with this id
  ctaHref?: string      // if set, CTA renders as <a href>
  ctaTone?: "sky" | "coral" | "mint"  // default "sky"
}
```

Output: centered flex column, emoji, title, optional subtitle, optional CTA. Matches the `py-10 text-center` pattern established on tasks/rewards pages.

When both `ctaId` and `ctaHref` are set, `ctaId` takes precedence.

---

### `SectionHeader.astro`

Consistent `<h2>` used before lists or grids inside pages.

```typescript
interface Props {
  title: string
  href?: string       // renders "Ver todo / See all →" when set
  lang?: string
}
```

Output:
```html
<div class="flex items-center justify-between mb-3">
  <h2 class="font-display text-lg font-extrabold text-brand-ink">{title}</h2>
  <!-- href renders: -->
  <a href={href} class="text-sm text-brand-sky-deep font-semibold hover:underline">
    {lang === "es" ? "Ver todo" : "See all"} →
  </a>
</div>
```

---

### `FormField.astro`

Eliminates the `<div class="flex flex-col gap-1"><label>...<input class="...">` repetition across login/register/settings pages (~40 occurrences).

```typescript
interface Props {
  label: string
  name: string
  type?: string           // default "text"
  error?: string          // renders red error message when set
  required?: boolean
  placeholder?: string
  value?: string
  disabled?: boolean
  class?: string          // extra classes on wrapper div
  inputClass?: string     // extra classes on input element
  [key: string]: any      // remaining attrs passed to <input>
}
```

Output:
```html
<div class="flex flex-col gap-1 {class}">
  <label for="{name}" class="text-sm font-semibold text-brand-ink">
    {label}{required && <span class="text-brand-coral ml-0.5">*</span>}
  </label>
  <input
    id="{name}" name="{name}" type="{type}"
    class="w-full border-2 border-brand-ink rounded-xl px-4 py-2.5 bg-brand-cream
           focus:outline-none focus:ring-2 focus:ring-brand-sky {inputClass}"
    ...rest
  />
  {error && <p class="text-xs text-red-600 font-medium">{error}</p>}
</div>
```

---

## Proof-of-Concept Migration: `parent/tasks.astro`

After building all 6 components, migrate `parent/tasks.astro` to validate the API:

**Before (boilerplate):**
```astro
import Layout from "../../layouts/Layout.astro";
import BottomNav from "../../components/BottomNav.astro";
...
<Layout title="Tasks - Family Task Manager">
  <div class="flex flex-col min-h-dvh">
    <header class="bg-brand-sky text-brand-ink border-b-4 border-brand-ink pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]">
      <a href="/parent" class="text-brand-ink-soft ...">← Back</a>
      <div class="flex items-center justify-between">
        <h1 class="font-display text-2xl font-extrabold">Tasks</h1>
        <button id="tcm-trigger" ...>+</button>
      </div>
    </header>
    <main class="flex-1 px-4 py-6 space-y-6">
      ...page content...
    </main>
    <BottomNav active="parent" role={user.role} lang={lang} />
    <BottomSpacer />
  </div>
</Layout>
```

**After:**
```astro
import PageLayout from "@/components/ui/PageLayout.astro";
...
<PageLayout title="Tasks" tone="sky" backHref="/parent" role={user.role} active="parent" lang={lang} mainClass="flex-1 px-4 py-6 space-y-6">
  <button slot="actions" id="tcm-trigger" ...>+</button>
  ...page content...
</PageLayout>
```

Also replace the inline empty state with `<EmptyState>` component.

---

## File Map

**Create:**
- `frontend/src/components/ui/PageHeader.astro`
- `frontend/src/components/ui/PageLayout.astro`
- `frontend/src/components/ui/BottomSheet.astro`
- `frontend/src/components/ui/EmptyState.astro`
- `frontend/src/components/ui/SectionHeader.astro`
- `frontend/src/components/ui/FormField.astro`
- `docs/design-tokens.md`

**Modify:**
- `frontend/src/pages/parent/tasks.astro` — proof-of-concept migration

---

## Testing

- Frontend build passes after each component is added
- `parent/tasks.astro` renders identically before/after migration (visual check)
- No regressions in existing pages (build is the gate — Astro catches prop type errors at build time)

---

## Out of Scope (sub-projects 2-5)

- Migrating all other pages to `PageLayout`
- Refactoring existing modal components to use `BottomSheet`
- `FormField` adoption in auth pages
- Design token linting / enforcement
- Dark-mode component variants
- Storybook or visual regression testing
