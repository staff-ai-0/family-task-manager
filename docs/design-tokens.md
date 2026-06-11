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

## Illustration palette

Used for illustration components (avatars, character graphics) only. Do not use in general UI.

| Token | Value |
|-------|-------|
| `--color-brand-skin-1` | `#FBD3B2` |
| `--color-brand-skin-2` | `#E8B690` |
| `--color-brand-skin-3` | `#C68A60` |
| `--color-brand-skin-4` | `#8E5B3D` |
| `--color-brand-hair-1` | `#1F1A17` |
| `--color-brand-hair-2` | `#4E3A2A` |

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
| `--radius-pill` | `999px` | `rounded-full` (or use `rounded-[var(--radius-pill)]` if you need to override) |

**Note on `--radius-pill`**: Native Tailwind `rounded-full` is equivalent. Use `rounded-[var(--radius-pill)]` only if you need to override the radius value.

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

### Fonts

| Variable | Value |
|----------|-------|
| `--font-display` | Plus Jakarta Sans (headings, `.font-display`) |
| `--font-sans` | Nunito (body, default) |
| `--font-mono` | ui-monospace, SFMono-Regular, Menlo, monospace |

Use `font-display` for h1/h2/h3 and brand labels. Use `font-sans` (default) for body text. Use `font-mono` for code snippets and numeric displays.

### Type scale

| Token | Size | Line height | Letter spacing |
|-------|------|-------------|----------------|
| `--text-display-1` | 84px | 0.95 | -0.03em |
| `--text-display-2` | 56px | 1.02 | -0.02em |
| `--text-title` | 40px | 1.05 | -0.02em |

Apply these via CSS: `font-size: var(--text-display-1); line-height: var(--text-display-1--line-height); letter-spacing: var(--text-display-1--letter-spacing);` (or use the individual variables `--text-display-1--line-height` and `--text-display-1--letter-spacing`).

---

## Layout

### Breakpoints

| Token | Value |
|-------|-------|
| `--breakpoint-3xl` | `1920px` |
