# UX-B3 Visual Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app look like one product: one header shape colored by section, readable text everywhere (WCAG AA ≥ 4.5:1), one icon rule, no half-built dark theme — and a CI guard that keeps it that way.

**Architecture:** Two tiny libs become the single source of look (`lib/headerTone.ts` for header fills, `lib/buttonClasses.ts` for buttons); four new text-safe color tokens replace the `-deep` shades as text colors. A pure source scanner (`test/support/visual-scan.ts`) plus a tree-walking vitest guard enforces eight rules; while the migration lands, each rule carries an exact remaining ALLOWANCE that tasks ratchet to 0, and the last task deletes the allowance so every rule is strict.

**Tech Stack:** Astro 5 (SSR, vanilla script islands), Tailwind CSS v4 (`@theme` tokens in `src/styles/global.css`), TypeScript, vitest 4 (node environment, `frontend/test/**/*.test.ts`).

**Spec:** `docs/superpowers/specs/2026-09-29-ux-b3-visual-consistency-design.md`

## Global Constraints

- All paths below are relative to `frontend/` unless they start with `docs/` or `e2e-tests/`. Run every command from `frontend/`.
- Brand fill colors do NOT change value: `--color-brand-sky #4FB8E6`, `-mint #5DD4A8`, `-coral #FF8A65`, `-sun #FFC857`, `-cream #FFF8F0`, `-cream-deep #F4E9D8`, `-ink #1F2937`, `-ink-soft #3B4252`, and all `-deep` shades.
- New tokens, exact values: `--color-brand-sky-text: #1A6F99; --color-brand-mint-text: #1E7552; --color-brand-coral-text: #B8431F; --color-brand-sun-text: #8A5A00;`
- Text on a brand fill (`bg-brand-{sky,mint,coral,sun}` or `-deep`, any variant prefix, any `/NN` alpha) is `text-brand-ink`, never `text-white`.
- Every text inside a tone header is ink (`text-brand-ink`); secondary text may be smaller or lighter weight, never a lighter color or `opacity-*` below 100. (`ink-soft` is 4.47:1 on sky and 4.35:1 on coral — below AA.)
- Section → tone map (spec, verbatim): **sky** = doing things; **mint** = money; **sun** = earning & winning; **coral** = treats, care & home; **cream** = talk & settings. Per-page assignment is in Tasks 4 and 5.
- Parent hub hero = `bg-brand-ink text-white`. Kid hero: teen skin `bg-[#1E2230] text-white`; child skin `headerToneClass("sky")`.
- Icons: chrome (nav, More sheet, header titles + actions, toolbars, list-row action buttons) = line icons; emoji only for big action tiles, empty states, celebrations/toasts, user-picked content. No emoji inside `<h1>`.
- Out of scope — never edit for B3 (they are exempt in the guard): `src/pages/{login,register,index,tdah,privacidad,terminos,forgot-password,reset-password,verify-email,accept-invitation,404,500,kiosk}.astro`, `src/pages/admin/**`, `src/components/ui/AdminShell.astro` (only its `theme="light"` prop is removed in Task 3), `src/components/GuideShell.astro`.
- Never use native `alert`/`confirm`/`prompt` (existing guard `test/no-native-dialogs.test.ts`).
- Tooling hygiene: run `npm`/`npx` with `</dev/null` and a `timeout` (an interactive npm prompt once hung `astro check` for 90 min). Never run `npm audit fix`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Light text left inside a header after its fill turned light** (slot `header-extra`/`actions` children, custom-hero innards, ChatShell `slot="header"` fragments) — a reasonable person expects every header word readable. Pinned by rule `light-text-in-header` (Task 2 unit tests) + Tasks 4/5 fix steps; ChatShell fragments get an explicit per-file check step in Task 5.
2. **A `-text` shade landing on a dark surface after the codemod** (ink cards, teen skin, `bg-brand-ink` buttons with colored text) — expects colored text still readable on dark. Pinned by Task 6 Step 4 (dark-surface sweep command) and Task 6's unit test that the codemod regex leaves non-`text-` utilities alone.
3. **Client-rendered HTML** (template literals in `<script>`, `innerHTML`, `lib/toast.ts`) keeping white-on-fill or faint text — expects the same readability as SSR markup. Pinned by the scanner scanning `.ts` and `<script>` bodies (Task 2 unit test "flags class strings inside template literals").
4. **An invalid tone reaching `headerToneClass` at runtime** (a cast, a typo in a `define:vars` script) — expects a readable cream header, not an unstyled one. Pinned by Task 1 unit test "unknown tone falls back to cream".
5. **Phone in OS dark mode after dark-mode removal** — expects a light app with a light status bar, no dark overscroll. Pinned by rule `dark-theme` (flags `prefers-color-scheme: dark`, including the Head.astro meta `media` attribute) — Task 2 unit test + Task 3.

---

### Task 1: Foundations — text tokens, contrast test, `headerTone`, `buttonClasses`

**Files:**
- Create: `test/support/contrast.ts`, `test/contrast.test.ts`, `src/lib/headerTone.ts`, `test/header-tone.test.ts`, `src/lib/buttonClasses.ts`, `test/button-classes.test.ts`
- Modify: `src/styles/global.css` (the `@theme` palette block, after `--color-brand-cream-deep`), `src/components/ui/Button.astro`

**Interfaces:**
- Produces: `type HeaderTone = "sky" | "mint" | "sun" | "coral" | "cream"`; `HEADER_TONES: readonly HeaderTone[]`; `headerToneClass(tone: HeaderTone): string` (from `src/lib/headerTone.ts`).
- Produces: `type ButtonVariant = "primary" | "secondary" | "mint" | "sun" | "ghost"`; `type ButtonSize = "sm" | "md" | "lg" | "icon"`; `buttonClass(variant?: ButtonVariant, size?: ButtonSize): string` (from `src/lib/buttonClasses.ts`).
- Produces: Tailwind utilities `text-brand-{sky,mint,coral,sun}-text`.
- Produces: `contrastRatio(a: string, b: string): number` (from `test/support/contrast.ts`).

- [ ] **Step 1: Install deps in the worktree**

Run: `timeout 600 npm ci </dev/null > /tmp/b3-npm-ci.log 2>&1; echo exit=$?; tail -3 /tmp/b3-npm-ci.log`
Expected: `exit=0`.

- [ ] **Step 2: Write the contrast helper and failing contrast test**

`test/support/contrast.ts`:

```ts
/** WCAG 2.x relative luminance + contrast ratio for #RRGGBB colors. */
function channel(v: number): number {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
    const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
    if (!m) throw new Error(`not a #RRGGBB color: ${hex}`);
    const n = parseInt(m[1], 16);
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}
```

`test/contrast.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { contrastRatio } from "./support/contrast";

const CSS = readFileSync(fileURLToPath(new URL("../src/styles/global.css", import.meta.url)), "utf8");
const AA = 4.5;
const WHITE = "#FFFFFF";

/** First definition of --color-brand-<name> in global.css (the @theme block). */
function token(name: string): string {
    const m = new RegExp(`--color-brand-${name}:\\s*(#[0-9A-Fa-f]{6})\\s*;`).exec(CSS);
    if (!m) throw new Error(`token --color-brand-${name} not found in global.css`);
    return m[1];
}

describe("contrastRatio", () => {
    it("is 21 for black on white and 1 for a color on itself", () => {
        expect(contrastRatio("#000000", WHITE)).toBeCloseTo(21, 5);
        expect(contrastRatio("#4FB8E6", "#4FB8E6")).toBeCloseTo(1, 5);
    });
    it("is symmetric", () => {
        expect(contrastRatio("#1F2937", "#4FB8E6")).toBeCloseTo(contrastRatio("#4FB8E6", "#1F2937"), 10);
    });
});

describe("brand token contrast (WCAG AA, UX-B3)", () => {
    const ink = () => token("ink");

    it.each(["sky", "mint", "sun", "coral", "cream"])("ink text on the %s header tone", (tone) => {
        expect(contrastRatio(ink(), token(tone))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky-deep", "mint-deep", "sun-deep", "coral-deep"])("ink text on the %s hover fill", (fill) => {
        expect(contrastRatio(ink(), token(fill))).toBeGreaterThanOrEqual(AA);
    });

    const surfaces = () => [["white", WHITE], ["cream", token("cream")], ["cream-deep", token("cream-deep")]] as const;
    it.each(["sky-text", "mint-text", "coral-text", "sun-text"])("%s on white, cream and cream-deep", (shade) => {
        for (const [, bg] of surfaces()) {
            expect(contrastRatio(token(shade), bg)).toBeGreaterThanOrEqual(AA);
        }
    });

    it("white text on the ink parent-hub hero", () => {
        expect(contrastRatio(WHITE, ink())).toBeGreaterThanOrEqual(AA);
    });
});
```

- [ ] **Step 3: Run it — RED**

Run: `timeout 300 npx vitest run test/contrast.test.ts </dev/null`
Expected: FAIL — the four `*-text` cases throw `token --color-brand-sky-text not found in global.css` (and siblings); every other case passes.

- [ ] **Step 4: Add the tokens**

In `src/styles/global.css`, directly after the line `  --color-brand-cream-deep: #F4E9D8;` insert:

```css

  /* Text-safe shades (UX-B3): ≥ 4.5:1 on white, cream and cream-deep.
     Use these for colored TEXT; the -deep shades are fills/hovers only. */
  --color-brand-sky-text:   #1A6F99;
  --color-brand-mint-text:  #1E7552;
  --color-brand-coral-text: #B8431F;
  --color-brand-sun-text:   #8A5A00;
```

- [ ] **Step 5: Run it — GREEN**

Run: `timeout 300 npx vitest run test/contrast.test.ts </dev/null`
Expected: PASS (all cases).

- [ ] **Step 6: Write the failing headerTone test**

`test/header-tone.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { HEADER_TONES, headerToneClass, type HeaderTone } from "../src/lib/headerTone";

describe("headerToneClass", () => {
    it("lists exactly the five section tones", () => {
        expect([...HEADER_TONES]).toEqual(["sky", "mint", "sun", "coral", "cream"]);
    });

    it.each(["sky", "mint", "sun", "coral", "cream"] as HeaderTone[])("%s → flat brand fill, ink outline, ink text", (tone) => {
        const cls = headerToneClass(tone).split(/\s+/);
        expect(cls).toContain(`bg-brand-${tone}`);
        expect(cls).toContain("border-b-4");
        expect(cls).toContain("border-brand-ink");
        expect(cls).toContain("text-brand-ink");
    });

    it("never produces white text or a gradient", () => {
        for (const tone of HEADER_TONES) {
            expect(headerToneClass(tone)).not.toMatch(/text-white|bg-gradient/);
        }
    });

    it("unknown tone falls back to cream", () => {
        expect(headerToneClass("violet" as HeaderTone)).toBe(headerToneClass("cream"));
    });
});
```

- [ ] **Step 7: Run it — RED**

Run: `timeout 300 npx vitest run test/header-tone.test.ts </dev/null`
Expected: FAIL — `Failed to resolve import "../src/lib/headerTone"`.

- [ ] **Step 8: Implement `src/lib/headerTone.ts`**

```ts
/**
 * Section header colors (UX-B3) — the ONE place a header's fill is decided.
 * Color means the section: sky = doing things, mint = money, sun = earning &
 * winning, coral = treats/care/home, cream = talk & settings. Every tone is a
 * flat brand fill with an ink outline and ink text (≥ 6.3:1 on every tone).
 * Used by PageHeader, ChatShell and the custom hero headers.
 */
export type HeaderTone = "sky" | "mint" | "sun" | "coral" | "cream";

export const HEADER_TONES: readonly HeaderTone[] = ["sky", "mint", "sun", "coral", "cream"];

const FILL: Record<HeaderTone, string> = {
    sky: "bg-brand-sky",
    mint: "bg-brand-mint",
    sun: "bg-brand-sun",
    coral: "bg-brand-coral",
    cream: "bg-brand-cream",
};

/** Fill + ink bottom outline + ink text for a section header. */
export function headerToneClass(tone: HeaderTone): string {
    return `${FILL[tone] ?? FILL.cream} border-b-4 border-brand-ink text-brand-ink`;
}
```

- [ ] **Step 9: Run it — GREEN**

Run: `timeout 300 npx vitest run test/header-tone.test.ts </dev/null`
Expected: PASS.

- [ ] **Step 10: Write the failing buttonClasses test**

`test/button-classes.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { buttonClass, type ButtonSize, type ButtonVariant } from "../src/lib/buttonClasses";

const VARIANTS: ButtonVariant[] = ["primary", "secondary", "mint", "sun", "ghost"];
const SIZES: ButtonSize[] = ["sm", "md", "lg", "icon"];

describe("buttonClass", () => {
    it("defaults to primary / md", () => {
        expect(buttonClass()).toBe(buttonClass("primary", "md"));
    });

    it.each(VARIANTS)("%s has ink text, ink outline, hard shadow — never white text", (v) => {
        const cls = buttonClass(v);
        expect(cls.split(/\s+/)).toEqual(expect.arrayContaining(["text-brand-ink", "border-2", "border-brand-ink"]));
        expect(cls).toContain("shadow-[var(--shadow-card)]");
        expect(cls).not.toContain("text-white");
    });

    it("maps each fill variant to its brand color and -deep hover", () => {
        expect(buttonClass("primary")).toMatch(/\bbg-brand-coral\b.*hover:bg-brand-coral-deep/);
        expect(buttonClass("secondary")).toMatch(/\bbg-brand-sky\b.*hover:bg-brand-sky-deep/);
        expect(buttonClass("mint")).toMatch(/\bbg-brand-mint\b.*hover:bg-brand-mint-deep/);
        expect(buttonClass("sun")).toMatch(/\bbg-brand-sun\b.*hover:bg-brand-sun-deep/);
    });

    it.each(SIZES)("size %s is applied", (s) => {
        expect(buttonClass("primary", s)).not.toBe(buttonClass("primary", s === "md" ? "sm" : "md"));
    });

    it("unknown variant/size fall back to primary/md", () => {
        expect(buttonClass("violet" as ButtonVariant, "xl" as ButtonSize)).toBe(buttonClass("primary", "md"));
    });

    it("Button.astro renders through buttonClass (single source)", () => {
        const src = readFileSync(fileURLToPath(new URL("../src/components/ui/Button.astro", import.meta.url)), "utf8");
        expect(src).toMatch(/import \{ buttonClass[^}]*\} from "\.\.\/\.\.\/lib\/buttonClasses"/);
        expect(src).not.toMatch(/const variants\s*=/);
    });
});
```

- [ ] **Step 11: Run it — RED**

Run: `timeout 300 npx vitest run test/button-classes.test.ts </dev/null`
Expected: FAIL — `Failed to resolve import "../src/lib/buttonClasses"`.

- [ ] **Step 12: Implement `src/lib/buttonClasses.ts` and point `Button.astro` at it**

`src/lib/buttonClasses.ts`:

```ts
/**
 * Button classes (UX-B3) — the ONE source for the kit "sticker" button:
 * bright brand fill, ink text, ink outline, hard shadow, -deep hover.
 * Button.astro renders through this; page scripts that build button HTML
 * import it too. is:inline / define:vars scripts cannot import — they copy
 * the literal string and the visual-consistency guard keeps them honest.
 */
export type ButtonVariant = "primary" | "secondary" | "mint" | "sun" | "ghost";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

const BASE =
    "press inline-flex items-center justify-center gap-2 font-display font-extrabold " +
    "border-2 border-brand-ink rounded-full shadow-[var(--shadow-card)] " +
    "tracking-tight whitespace-nowrap select-none cursor-pointer";

const SIZES: Record<ButtonSize, string> = {
    sm: "px-4 py-2 text-sm",
    md: "px-5 py-3 text-base",
    lg: "px-7 py-4 text-lg",
    icon: "h-10 w-10 p-0 text-xl",
};

const VARIANTS: Record<ButtonVariant, string> = {
    primary: "bg-brand-coral text-brand-ink hover:bg-brand-coral-deep",
    secondary: "bg-brand-sky text-brand-ink hover:bg-brand-sky-deep",
    mint: "bg-brand-mint text-brand-ink hover:bg-brand-mint-deep",
    sun: "bg-brand-sun text-brand-ink hover:bg-brand-sun-deep",
    ghost: "bg-transparent text-brand-ink hover:bg-brand-cream-deep",
};

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
    return `${BASE} ${SIZES[size] ?? SIZES.md} ${VARIANTS[variant] ?? VARIANTS.primary}`;
}
```

`src/components/ui/Button.astro` — replace the frontmatter below the doc comment so it reads:

```astro
---
/**
 * Button — the press-down hard-shadow button. Classes come from
 * lib/buttonClasses.ts (single source, also used by page scripts).
 *
 * @prop variant  "primary" | "secondary" | "mint" | "sun" | "ghost"  default "primary"
 *                primary   = coral fill (kid/teen CTA — see brand guide)
 *                secondary = sky fill
 *                mint      = mint fill
 *                sun       = sun fill
 *                ghost     = transparent + ink outline
 * @prop size     "sm" | "md" | "lg" | "icon"  default "md"
 *                icon = h-10 w-10 round icon-only button (pair with aria-label)
 * @prop href     Render as <a> instead of <button>.
 */
import { buttonClass, type ButtonSize, type ButtonVariant } from "../../lib/buttonClasses";

interface Props {
  variant?: ButtonVariant;
  size?: ButtonSize;
  href?: string;
  type?: "button" | "submit" | "reset";
  class?: string;
  [key: string]: any;
}
const {
  variant = "primary",
  size = "md",
  href,
  type = "button",
  class: className = "",
  ...rest
} = Astro.props;

const cls = `${buttonClass(variant, size)} ${className}`;
const Tag = href ? "a" : "button";
---

<Tag class={cls} href={href} type={!href ? type : undefined} {...rest}>
  <slot />
</Tag>
```

- [ ] **Step 13: Run it — GREEN, then the whole vitest suite**

Run: `timeout 300 npx vitest run test/button-classes.test.ts </dev/null`
Expected: PASS.
Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -5`
Expected: all test files pass (206 pre-existing + the new ones).

- [ ] **Step 14: Commit**

```bash
git add src/styles/global.css src/lib/headerTone.ts src/lib/buttonClasses.ts src/components/ui/Button.astro test/support/contrast.ts test/contrast.test.ts test/header-tone.test.ts test/button-classes.test.ts
git commit -m "feat(ux-b3): text-safe color tokens, headerTone + buttonClasses single sources, contrast test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Visual-consistency scanner + guard with a ratcheting allowance

**Files:**
- Create: `test/support/visual-scan.ts`, `test/visual-scan.test.ts`, `test/visual-consistency.test.ts`

**Interfaces:**
- Produces: `type RuleId = "header-gradient" | "light-text-in-header" | "white-on-brand-fill" | "deep-text" | "faint-text" | "h1-emoji" | "dark-theme" | "header-class-prop"`; `RULE_IDS: readonly RuleId[]`; `interface Hit { rule: RuleId; line: number; match: string }`; `scanVisual(text: string): Hit[]` (from `test/support/visual-scan.ts`).
- Produces: `ALLOWANCE: Record<RuleId, number>` constant in `test/visual-consistency.test.ts` — every later task lowers the entries for the rules it fixes; the guard asserts `offenders.length === ALLOWANCE[rule]` exactly, so a fix without lowering the allowance fails too.

- [ ] **Step 1: Write the failing scanner unit tests**

`test/visual-scan.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { scanVisual, type RuleId } from "./support/visual-scan";

const rules = (src: string, rule: RuleId) => scanVisual(src).filter((h) => h.rule === rule);

describe("scanVisual — header-gradient", () => {
    it("flags a gradient on a <header>, multi-line tags included", () => {
        const src = [
            '<header class="bg-gradient-to-br from-violet-700 to-violet-500 text-white">',
            "</header>",
            "<header",
            '    slot="header"',
            '    class="bg-gradient-to-br from-slate-800 to-slate-700">',
            "</header>",
        ].join("\n");
        expect(rules(src, "header-gradient").map((h) => h.line)).toEqual([1, 3]);
    });
    it("ignores gradients on non-header elements", () => {
        expect(rules('<div class="bg-gradient-to-r from-brand-sun to-brand-coral"></div>', "header-gradient")).toEqual([]);
    });
});

describe("scanVisual — light-text-in-header", () => {
    it("flags white / pale text inside a light header block", () => {
        const src = [
            '<header class={headerToneClass("mint")}>',
            '  <p class="text-white/80 text-sm">x</p>',
            '  <span class="text-violet-100">y</span>',
            '  <b class="text-brand-ink">ok</b>',
            "</header>",
        ].join("\n");
        expect(rules(src, "light-text-in-header").map((h) => [h.line, h.match])).toEqual([
            [2, "text-white/80"],
            [3, "text-violet-100"],
        ]);
    });
    it("allows light text in dark heroes (bg-brand-ink or an arbitrary dark hex)", () => {
        const src = [
            '<header class="bg-brand-ink text-white pt-12"><p class="text-slate-300">d</p></header>',
            '<header class="bg-[#1E2230] text-white"><p class="text-white/80">t</p></header>',
        ].join("\n");
        expect(rules(src, "light-text-in-header")).toEqual([]);
    });
    it("flags light text on a header-extra / actions slot element", () => {
        const src = [
            '<p slot="header-extra" class="text-amber-100 text-sm">sub</p>',
            '<div slot="actions" class="flex gap-2 text-brand-ink">ok</div>',
        ].join("\n");
        expect(rules(src, "light-text-in-header").map((h) => h.line)).toEqual([1]);
    });
});

describe("scanVisual — white-on-brand-fill", () => {
    it("flags white text with a brand fill in the same class string, any prefix or alpha", () => {
        const src = [
            '<button class="bg-brand-sky-deep text-white px-4">Guardar</button>',
            '<span class="rounded-full bg-brand-mint/20 hover:text-white">x</span>',
            '<a class="hover:bg-brand-coral-deep text-white">y</a>',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1, 2, 3]);
    });
    it("flags class strings inside template literals (client-rendered HTML)", () => {
        const src = "el.innerHTML = `<button class=\"${on ? 'bg-brand-sun text-white' : 'bg-white'}\">`;";
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("does not pair classes from different strings or dark fills", () => {
        const src = [
            '<b class={on ? "bg-brand-sky text-brand-ink" : "bg-white text-white"}>x</b>',
            '<button class="bg-brand-ink text-white">ok</button>',
            '<p class="bg-red-600 text-white">danger</p>',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill")).toEqual([]);
    });
});

describe("scanVisual — deep-text / faint-text", () => {
    it("flags -deep shades used as text color, with variants", () => {
        const src = '<a class="text-brand-sky-deep hover:text-brand-mint-deep">x</a>';
        expect(rules(src, "deep-text").map((h) => h.match)).toEqual(["text-brand-sky-deep", "hover:text-brand-mint-deep"]);
    });
    it("leaves -deep fills, borders, rings and the new -text shades alone", () => {
        const src = '<a class="bg-brand-sky-deep border-brand-mint-deep ring-brand-coral-deep text-brand-sky-text">x</a>';
        expect(rules(src, "deep-text")).toEqual([]);
    });
    it("flags faint slate/gray 400/500 text only", () => {
        const src = '<p class="text-slate-500 text-gray-400 text-slate-700 hover:text-slate-600">x</p>';
        expect(rules(src, "faint-text").map((h) => h.match)).toEqual(["text-slate-500", "text-gray-400"]);
    });
});

describe("scanVisual — h1-emoji", () => {
    it("flags emoji inside an <h1>, including multi-line and expression text", () => {
        const src = [
            '<h1 class="text-2xl">🏦 {user.name}</h1>',
            "<h1>",
            '  {es ? "💬 Chat" : "💬 Chat"}',
            "</h1>",
            '<h1 class="text-2xl">{name}</h1>',
            "<h2>🎯 goal</h2>",
        ].join("\n");
        expect(rules(src, "h1-emoji").map((h) => h.line)).toEqual([1, 2]);
    });
});

describe("scanVisual — dark-theme / header-class-prop", () => {
    it("flags dark-theme CSS and media queries, not the Google button option", () => {
        const src = [
            '[data-theme="dark"] { color-scheme: dark; }',
            '<meta name="theme-color" content="#0F1A24" media="(prefers-color-scheme: dark)" />',
            '<div data-theme="outline"></div>',
        ].join("\n");
        expect(rules(src, "dark-theme").map((h) => h.line)).toEqual([1, 2]);
    });
    it("flags a headerClass= prop", () => {
        expect(rules('<PageLayout headerClass="bg-gradient-to-br from-a to-b">', "header-class-prop")).toHaveLength(1);
    });
});

describe("scanVisual — comments", () => {
    it("skips pure comment lines", () => {
        const src = [
            "// text-brand-sky-deep in a comment",
            " * @prop headerClass Gradient/bg classes",
            "<!-- bg-brand-sky text-white -->",
            "{/* text-slate-500 */}",
        ].join("\n");
        expect(scanVisual(src)).toEqual([]);
    });
});
```

- [ ] **Step 2: Run it — RED**

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null`
Expected: FAIL — `Failed to resolve import "./support/visual-scan"`.

- [ ] **Step 3: Implement `test/support/visual-scan.ts`**

```ts
/**
 * Visual-consistency scanner (UX-B3). Pure: one file's text in, rule hits out.
 * The tree walk, exemptions and allowances live in visual-consistency.test.ts.
 *
 * Class tokens are matched with their variant prefixes (hover:, md:, group-hover:)
 * and optional /NN alpha. Pairing rules (white text + brand fill) only pair
 * tokens inside ONE quoted string on one line, so a ternary's two branches are
 * never mixed up.
 */
export type RuleId =
    | "header-gradient"
    | "light-text-in-header"
    | "white-on-brand-fill"
    | "deep-text"
    | "faint-text"
    | "h1-emoji"
    | "dark-theme"
    | "header-class-prop";

export const RULE_IDS: readonly RuleId[] = [
    "header-gradient",
    "light-text-in-header",
    "white-on-brand-fill",
    "deep-text",
    "faint-text",
    "h1-emoji",
    "dark-theme",
    "header-class-prop",
];

export interface Hit {
    rule: RuleId;
    line: number;
    match: string;
}

const START = "(?<![\\w-])"; // token must not continue a longer word
const V = "(?:[a-z-]+:)*"; // variant prefixes
const BRAND_FILL = new RegExp(`${START}${V}bg-brand-(?:sky|mint|coral|sun)(?:-deep)?(?:/\\d+)?(?![\\w-])`);
const WHITE_TEXT = new RegExp(`${START}${V}text-white(?:/\\d+)?(?![\\w-])`);
const DEEP_TEXT = new RegExp(`${START}${V}text-brand-(?:sky|mint|coral|sun)-deep(?![\\w-])`, "g");
const FAINT_TEXT = new RegExp(`${START}${V}text-(?:slate|gray)-(?:400|500)(?![\\w-])`, "g");
const LIGHT_TEXT = new RegExp(`${START}${V}text-(?:white(?:/\\d+)?|[a-z]+-(?:50|100|200|300))(?![\\w-])`, "g");
const QUOTED = /"([^"\n]*)"|'([^'\n]*)'|`([^`\n]*)`/g;
const DARK_THEME = /\[data-theme=["']?dark["']?\]|prefers-color-scheme:\s*dark/;
const HEADER_CLASS = /\bheaderClass\s*=/;
const SLOT_LINE = /slot="(?:header-extra|actions)"/;
const DARK_HERO = /\bbg-brand-ink\b|\bbg-\[#/;
const HEADER_BLOCK = /<header\b([^>]*)>([\s\S]*?)<\/header>/g;
const H1_BLOCK = /<h1\b[^>]*>([\s\S]*?)<\/h1>/g;
const EMOJI = /\p{Extended_Pictographic}/u;
const COMMENT_LINE = /^\s*(?:\/\/|\/\*|\*|<!--|\{\/\*)/;

function lineAt(text: string, index: number): number {
    let n = 1;
    for (let i = 0; i < index; i++) if (text.charCodeAt(i) === 10) n++;
    return n;
}

/** Blank out pure comment lines, keeping line numbers stable. */
function stripCommentLines(text: string): string {
    return text
        .split("\n")
        .map((l) => (COMMENT_LINE.test(l) ? "" : l))
        .join("\n");
}

export function scanVisual(raw: string): Hit[] {
    const text = stripCommentLines(raw);
    const hits: Hit[] = [];

    text.split("\n").forEach((l, i) => {
        const line = i + 1;
        for (const q of l.matchAll(QUOTED)) {
            const s = q[1] ?? q[2] ?? q[3] ?? "";
            if (WHITE_TEXT.test(s) && BRAND_FILL.test(s)) {
                hits.push({ rule: "white-on-brand-fill", line, match: q[0] });
            }
        }
        for (const m of l.matchAll(DEEP_TEXT)) hits.push({ rule: "deep-text", line, match: m[0] });
        for (const m of l.matchAll(FAINT_TEXT)) hits.push({ rule: "faint-text", line, match: m[0] });
        if (DARK_THEME.test(l)) hits.push({ rule: "dark-theme", line, match: DARK_THEME.exec(l)![0] });
        if (HEADER_CLASS.test(l)) hits.push({ rule: "header-class-prop", line, match: "headerClass=" });
        if (SLOT_LINE.test(l)) {
            for (const m of l.matchAll(LIGHT_TEXT)) hits.push({ rule: "light-text-in-header", line, match: m[0] });
        }
    });

    for (const m of text.matchAll(HEADER_BLOCK)) {
        const start = m.index ?? 0;
        const attrs = m[1];
        if (/bg-gradient-to-/.test(attrs)) {
            hits.push({ rule: "header-gradient", line: lineAt(text, start), match: "bg-gradient-to-" });
        }
        if (!DARK_HERO.test(attrs)) {
            const block = m[0];
            for (const t of block.matchAll(LIGHT_TEXT)) {
                hits.push({ rule: "light-text-in-header", line: lineAt(text, start + (t.index ?? 0)), match: t[0] });
            }
        }
    }

    for (const m of text.matchAll(H1_BLOCK)) {
        if (EMOJI.test(m[1])) hits.push({ rule: "h1-emoji", line: lineAt(text, m.index ?? 0), match: "<h1>" });
    }

    return hits.sort((a, b) => a.line - b.line || a.rule.localeCompare(b.rule));
}
```

- [ ] **Step 4: Run it — GREEN**

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null`
Expected: PASS. If a case fails, fix the scanner (not the test) — each case encodes a spec rule.

- [ ] **Step 5: Write the tree guard with a zeroed allowance**

`test/visual-consistency.test.ts`:

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { RULE_IDS, scanVisual, type RuleId } from "./support/visual-scan";

const SRC = fileURLToPath(new URL("../src", import.meta.url));

/** Out of B3 scope (spec "Not in B3"). A trailing "/" exempts a directory. */
const EXEMPT: { path: string; why: string }[] = [
    { path: "pages/login.astro", why: "auth page, no app header" },
    { path: "pages/register.astro", why: "auth page, no app header" },
    { path: "pages/forgot-password.astro", why: "auth page, no app header" },
    { path: "pages/reset-password.astro", why: "auth page, no app header" },
    { path: "pages/verify-email.astro", why: "auth page, no app header" },
    { path: "pages/accept-invitation.astro", why: "auth page, no app header" },
    { path: "pages/index.astro", why: "public landing page" },
    { path: "pages/tdah.astro", why: "public landing page" },
    { path: "pages/privacidad.astro", why: "legal page" },
    { path: "pages/terminos.astro", why: "legal page" },
    { path: "pages/404.astro", why: "error page" },
    { path: "pages/500.astro", why: "error page" },
    { path: "pages/kiosk.astro", why: "shared-device full-screen board" },
    { path: "pages/admin/", why: "operator console, own neutral styling" },
    { path: "components/ui/AdminShell.astro", why: "operator console shell" },
    { path: "components/GuideShell.astro", why: "help-guide document styling" },
];

/** These apply everywhere, exemptions included. */
const GLOBAL_RULES: RuleId[] = ["dark-theme", "header-class-prop"];

/**
 * Remaining offenders per rule while B3 lands. The guard asserts EXACT
 * equality: a new offender fails, and so does a fix that forgets to lower
 * its number. Every entry reaches 0; the last task deletes this map.
 */
const ALLOWANCE: Record<RuleId, number> = {
    "header-gradient": 0,
    "light-text-in-header": 0,
    "white-on-brand-fill": 0,
    "deep-text": 0,
    "faint-text": 0,
    "h1-emoji": 0,
    "dark-theme": 0,
    "header-class-prop": 0,
};

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return walk(path);
        return /\.(astro|ts|css)$/.test(name) ? [path] : [];
    });
}

const isExempt = (file: string) =>
    EXEMPT.some((e) => (e.path.endsWith("/") ? file.startsWith(e.path) : file === e.path));

const hits = walk(SRC).flatMap((abs) => {
    const file = relative(SRC, abs).split(sep).join("/");
    return scanVisual(readFileSync(abs, "utf8"))
        .filter((h) => GLOBAL_RULES.includes(h.rule) || !isExempt(file))
        .map((h) => `${file}:${h.line} ${h.match}`.concat(` [${h.rule}]`));
});

describe("visual consistency guard (UX-B3)", () => {
    it.each([...RULE_IDS])("%s: offenders match the allowance", (rule) => {
        const offenders = hits.filter((h) => h.endsWith(`[${rule}]`));
        expect(offenders.length, `${rule} offenders:\n${offenders.join("\n")}`).toBe(ALLOWANCE[rule]);
    });

    it("every exemption still exists (no stale entries)", () => {
        const files = walk(SRC).map((abs) => relative(SRC, abs).split(sep).join("/"));
        for (const e of EXEMPT) {
            expect(files.some((f) => (e.path.endsWith("/") ? f.startsWith(e.path) : f === e.path)), e.path).toBe(true);
        }
    });
});
```

- [ ] **Step 6: Run it — RED, record the baseline**

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -E 'offenders match|expected [0-9]+ to be' | head -30`
Expected: FAIL on every rule with offenders (approximate counts from the 2026-09-29 scan: header-gradient ≈ 13, light-text-in-header > 0, white-on-brand-fill ≈ 95, deep-text ≈ 400, faint-text ≈ 2, h1-emoji = 6, dark-theme ≈ 4, header-class-prop ≈ 35). The assertion message prints the actual count (`expected N to be 0`).

- [ ] **Step 7: Set ALLOWANCE to the actual counts — GREEN**

Replace each `0` in `ALLOWANCE` with the actual count printed for that rule in Step 6 (rules that printed no failure stay `0`). Do not change any other code.
Run: `timeout 300 npx vitest run test/visual-consistency.test.ts test/visual-scan.test.ts </dev/null`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add test/support/visual-scan.ts test/visual-scan.test.ts test/visual-consistency.test.ts
git commit -m "test(ux-b3): visual-consistency scanner + guard with ratcheting allowance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Remove the dark theme; prune unused kit components

**Files:**
- Modify: `src/layouts/Layout.astro` (Props `theme`, default `theme = "system"`, `<html … data-theme=…>`, the `{theme === "system" && (<script is:inline>…)}` block), `src/styles/global.css` (the `[data-theme="dark"] { … }` block inside `@layer base`), `src/components/meta/Head.astro` (lines with `name="theme-color"`), `src/components/ui/AdminShell.astro` (`theme="light"` attribute only), `test/visual-consistency.test.ts` (ALLOWANCE)
- Delete: `src/components/ui/BottomSheet.astro`, `src/components/ui/FormField.astro`

**Interfaces:**
- Consumes: `ALLOWANCE["dark-theme"]` from Task 2.
- Produces: `Layout` no longer accepts a `theme` prop (any caller passing it fails `astro check`).

- [ ] **Step 1: Ratchet the rule — RED**

In `test/visual-consistency.test.ts` set `"dark-theme": 0`.
Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -A8 'dark-theme'`
Expected: FAIL listing `styles/global.css`, `layouts/Layout.astro`, `components/meta/Head.astro` offenders.

- [ ] **Step 2: Remove the scaffold**

- `src/layouts/Layout.astro`: delete the `theme?: "light" | "dark" | "system";` prop line (and its doc comment line if any), delete `theme = "system",` from the destructure, change `<html lang={lang} data-theme={theme === "dark" ? "dark" : undefined}>` to `<html lang={lang}>`, and delete the whole block

```astro
		{theme === "system" && (
			<script is:inline>
				try {
					const m = window.matchMedia("(prefers-color-scheme: dark)");
					if (m.matches) document.documentElement.setAttribute("data-theme", "dark");
					m.addEventListener("change", (e) => {
						document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
					});
				} catch (_) {}
			</script>
		)}
```

- `src/styles/global.css`: delete the whole `[data-theme="dark"] { … }` block (from `  [data-theme="dark"] {` through its closing `  }`); keep the `:root { color-scheme: light; … }` block untouched.
- `src/components/meta/Head.astro`: replace the two `theme-color` meta lines with the single line `<meta name="theme-color" content="#4FB8E6" />`.
- `src/components/ui/AdminShell.astro`: change `<Layout title={`Admin · ${title}`} theme="light" noindex>` to `<Layout title={`Admin · ${title}`} noindex>`.
- Delete `src/components/ui/BottomSheet.astro` and `src/components/ui/FormField.astro` (`git rm`). Confirm first: `grep -rn "BottomSheet\|FormField" src` must print nothing but those two files' own lines.

- [ ] **Step 3: GREEN + type check**

Run: `timeout 300 npx vitest run </dev/null 2>&1 | tail -4`
Expected: all pass.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?; tail -4 /tmp/b3-check.log`
Expected: `exit=0`, `0 errors`.

- [ ] **Step 4: Commit**

```bash
git add -A src/layouts/Layout.astro src/styles/global.css src/components/meta/Head.astro src/components/ui/AdminShell.astro src/components/ui/BottomSheet.astro src/components/ui/FormField.astro test/visual-consistency.test.ts
git commit -m "refactor(ux-b3): remove half-built dark theme; delete unused BottomSheet/FormField

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `PageHeader`/`PageLayout` tone API + every `PageLayout` page on its section tone

**Files:**
- Modify: `src/components/ui/PageHeader.astro`, `src/components/ui/PageLayout.astro`, `src/components/ui/BudgetShell.astro` (doc comment only), the 35 pages in the table below, `test/visual-consistency.test.ts` (ALLOWANCE)
- Create: `test/section-tones.test.ts`

**Interfaces:**
- Consumes: `headerToneClass`, `HeaderTone` (Task 1); `ALLOWANCE` (Task 2).
- Produces: `PageLayout`/`PageHeader` props `tone?: HeaderTone` (default `"cream"`), `backHref?`, `backLabel?`, `lang?`; props `headerClass`, `dark`, `backClass` REMOVED. `test/section-tones.test.ts` exports nothing; Task 5 appends a second map to it.

Page → tone (spec "Section → color map"):

| Page (`src/pages/…`) | tone |
|---|---|
| `calendar.astro`, `calendar/scan.astro`, `parent/approvals.astro`, `parent/day.astro`, `parent/kiosk.astro`, `parent/routines.astro`, `routines.astro`, `parent/tasks.astro`, `parent/tasks/[id]/edit.astro` | `sky` |
| `parent/payouts.astro`, `parent/settings/envelopes.astro`, `parent/settings/family-bank.astro` | `mint` |
| `gigs/my-gigs.astro`, `parent/gigs.astro`, `family-cup.astro` | `sun` |
| `meals.astro`, `parent/consequences.astro`, `parent/rewards.astro`, `parent/rewards/[id]/edit.astro`, `pet.astro`, `pet/quests.astro`, `pet/shop.astro`, `rewards.astro`, `shopping.astro` | `coral` |
| `dm.astro`, `notifications.astro`, `parent/jarvis-schedules.astro`, `parent/settings/family.astro`, `parent/settings/index.astro`, `parent/settings/mcp-tokens.astro`, `parent/settings/referrals.astro`, `parent/settings/subscription.astro`, `parent/starter-packs.astro`, `parent/members.astro`, `parent/analytics.astro` | `cream` |

**Light-content replacement table** (apply to every element passed in `slot="actions"` / `slot="header-extra"` on these pages and to their children):

| Before | After |
|---|---|
| `text-white`, `text-white/NN`, `text-<hue>-50…300` (e.g. `text-violet-100`, `text-amber-100`, `text-slate-300`) | `text-brand-ink` |
| `opacity-60…90` on text | remove |
| `bg-white/NN` (glass chips/buttons) | `bg-brand-ink/10` |
| `hover:bg-white/NN` | `hover:bg-brand-ink/10` |
| `border-white/NN` | `border-brand-ink/20` |
| `bg-white text-<hue>-600…800` (white pill in a dark header) | `bg-white text-brand-ink border-2 border-brand-ink` |
| `placeholder-white/NN`, `placeholder:text-white/NN` | `placeholder:text-brand-ink-soft` |
| `ring-white`, `focus:ring-white` | `ring-brand-ink`, `focus:ring-brand-ink` |

- [ ] **Step 1: Write the failing section-tone test**

`test/section-tones.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { HeaderTone } from "../src/lib/headerTone";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

/** Pages rendered through PageLayout → PageHeader (spec "Section → color map"). */
const PAGE_LAYOUT_TONES: Record<string, HeaderTone> = {
    "pages/calendar.astro": "sky",
    "pages/calendar/scan.astro": "sky",
    "pages/parent/approvals.astro": "sky",
    "pages/parent/day.astro": "sky",
    "pages/parent/kiosk.astro": "sky",
    "pages/parent/routines.astro": "sky",
    "pages/routines.astro": "sky",
    "pages/parent/tasks.astro": "sky",
    "pages/parent/tasks/[id]/edit.astro": "sky",
    "pages/parent/payouts.astro": "mint",
    "pages/parent/settings/envelopes.astro": "mint",
    "pages/parent/settings/family-bank.astro": "mint",
    "pages/gigs/my-gigs.astro": "sun",
    "pages/parent/gigs.astro": "sun",
    "pages/family-cup.astro": "sun",
    "pages/meals.astro": "coral",
    "pages/parent/consequences.astro": "coral",
    "pages/parent/rewards.astro": "coral",
    "pages/parent/rewards/[id]/edit.astro": "coral",
    "pages/pet.astro": "coral",
    "pages/pet/quests.astro": "coral",
    "pages/pet/shop.astro": "coral",
    "pages/rewards.astro": "coral",
    "pages/shopping.astro": "coral",
    "pages/dm.astro": "cream",
    "pages/notifications.astro": "cream",
    "pages/parent/jarvis-schedules.astro": "cream",
    "pages/parent/settings/family.astro": "cream",
    "pages/parent/settings/index.astro": "cream",
    "pages/parent/settings/mcp-tokens.astro": "cream",
    "pages/parent/settings/referrals.astro": "cream",
    "pages/parent/settings/subscription.astro": "cream",
    "pages/parent/starter-packs.astro": "cream",
    "pages/parent/members.astro": "cream",
    "pages/parent/analytics.astro": "cream",
};

describe("PageLayout pages use their section tone", () => {
    it.each(Object.entries(PAGE_LAYOUT_TONES))("%s → %s", (file, tone) => {
        const src = read(file);
        const tones = [...src.matchAll(/\btone="([a-z]+)"/g)].map((m) => m[1]);
        expect(tones, `${file} tone= props`).toEqual([tone]);
        expect(src).not.toMatch(/\b(headerClass|backClass)=|<PageLayout[^>]*\sdark[\s>=]/);
    });
});

describe("PageHeader renders through headerToneClass", () => {
    it("has no per-page color escape hatches", () => {
        const src = read("components/ui/PageHeader.astro");
        expect(src).toMatch(/headerToneClass\(tone\)/);
        expect(src).not.toMatch(/headerClass|backClass|\bdark\b/);
    });
});
```

- [ ] **Step 2: Run it — RED**

Run: `timeout 300 npx vitest run test/section-tones.test.ts </dev/null 2>&1 | tail -15`
Expected: FAIL — most pages have `tone= props: []` or the wrong tone, and PageHeader lacks `headerToneClass(tone)`.

- [ ] **Step 3: Rewrite `PageHeader.astro`**

Replace the whole file with:

```astro
---
/**
 * PageHeader — section-colored page header (UX-B3): one shape everywhere,
 * color = section (see lib/headerTone.ts). Every text inside is ink.
 * @prop title       Page title rendered as h1
 * @prop tone        Section tone: "sky" | "mint" | "sun" | "coral" | "cream" (default "cream")
 * @prop backHref    Optional URL for back link (hidden when omitted)
 * @prop backLabel   Back link text (default "Back"/"Volver" by lang)
 * @prop lang        "en" | "es" — determines default back link text (default "en")
 * @prop class       Extra Tailwind classes on the outer <header>
 * Slots:
 *   actions — right of title row (buttons, icon-links)
 *   sub     — below title row (subtitle line, stat, breadcrumb)
 */
import { headerToneClass, type HeaderTone } from "../../lib/headerTone";

interface Props {
  title: string;
  tone?: HeaderTone;
  backHref?: string;
  backLabel?: string;
  lang?: "en" | "es";
  class?: string;
}
const { title, tone = "cream", backHref, backLabel, lang = "en", class: className = "" } = Astro.props;
---

<header class={`${headerToneClass(tone)} pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)] ${className}`}>
  {backHref && (
    <a href={backHref} class="text-brand-ink hover:underline text-sm font-bold flex items-center gap-1 mb-3">
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      {backLabel ?? (lang === "es" ? "Volver" : "Back")}
    </a>
  )}
  <div class="flex items-center justify-between gap-3">
    <h1 class="font-display text-2xl font-extrabold">{title}</h1>
    <slot name="actions" />
  </div>
  <slot name="sub" />
</header>
```

- [ ] **Step 4: Update `PageLayout.astro` and the `BudgetShell` comment**

In `src/components/ui/PageLayout.astro`:
- Add `import type { HeaderTone } from "../../lib/headerTone";` to the imports.
- In the doc comment, replace the four lines for `tone`, `headerClass`, `dark`, `backClass` with ` * @prop tone           Section tone for the header (default "cream"; see lib/headerTone.ts)`.
- In `interface Props`: replace `tone?: "sky" | "coral" | "mint" | "sun" | "cream";` with `tone?: HeaderTone;` and delete the `headerClass?`, `dark?`, `backClass?` lines.
- In the destructure: `tone = "cream",` and delete `headerClass,`, `dark = false,`, `backClass,`.
- In the markup: `<PageHeader title={title} tone={tone} backHref={backHref} backLabel={backLabel} lang={lang}>`.

In `src/components/ui/BudgetShell.astro` change the comment fragment `(or composes <PageHeader headerClass dark>)` to `(or composes <PageHeader tone="mint">)`.

- [ ] **Step 5: Migrate the 35 pages**

For each page in the table: on its `<PageLayout …>` tag delete `headerClass=…`, `dark`, `backClass=…` and set exactly one `tone="<tone>"` (replace an existing `tone=`). Then apply the light-content replacement table to every `slot="actions"` / `slot="header-extra"` element and its children on that page. Do not touch anything else on the page (white-on-fill buttons in the body are Tasks 7–8; colored text is Task 6).

Example (`src/pages/parent/gigs.astro`):

```astro
<!-- before -->
<PageLayout title={…} headerClass="bg-gradient-to-br from-violet-800 to-violet-600" dark backClass="text-violet-100 hover:text-white" backHref="/parent" …>
  <p slot="header-extra" class="text-violet-100 text-sm mt-1">{…}</p>
<!-- after -->
<PageLayout title={…} tone="sun" backHref="/parent" …>
  <p slot="header-extra" class="text-brand-ink text-sm mt-1">{…}</p>
```

- [ ] **Step 6: GREEN — section tones, type check**

Run: `timeout 300 npx vitest run test/section-tones.test.ts </dev/null 2>&1 | tail -4`
Expected: PASS.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?; grep -E 'error|Result' /tmp/b3-check.log | tail -8`
Expected: `exit=0`, `0 errors` (a leftover `headerClass`/`dark`/`backClass` on any page is a type error here).

- [ ] **Step 7: Ratchet the guard**

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -E 'expected [0-9]+ to be' `
Expected: `header-class-prop`, `header-gradient`?, `light-text-in-header` and possibly `white-on-brand-fill`/`deep-text` report LOWER actual counts than their allowance (the test fails because counts must match exactly). Lower each of those ALLOWANCE entries to the printed actual count. `header-class-prop` must now equal the number of `headerClass=` left on the 4 ChatShell pages (4). No count may go UP; if one does, fix the page that introduced it.
Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add -A src/components/ui/PageHeader.astro src/components/ui/PageLayout.astro src/components/ui/BudgetShell.astro src/pages test/section-tones.test.ts test/visual-consistency.test.ts
git commit -m "feat(ux-b3): section-colored PageHeader; PageLayout pages on their section tone

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Custom heroes, `ChatShell`, kid + parent home heroes, budget headers, title emoji

**Files:**
- Modify: `src/components/ui/ChatShell.astro`, `src/components/home/KidHeader.astro`, and pages `src/pages/{bank,envelopes,profile,chat,soporte}.astro`, `src/pages/gigs/index.astro`, `src/pages/calendar/month.astro`, `src/pages/dm/[id].astro`, `src/pages/parent/{index,assignments,jarvis}.astro`, `src/pages/budget/{index,import}.astro`, `src/pages/budget/recycle-bin/index.astro`; `test/section-tones.test.ts`; `test/visual-consistency.test.ts` (ALLOWANCE)

**Interfaces:**
- Consumes: `headerToneClass`, `HeaderTone` (Task 1); `ALLOWANCE` (Task 2); `test/section-tones.test.ts` (Task 4).
- Produces: `ChatShell` prop `tone: HeaderTone` (required) replaces `headerClass`.

Hero → tone:

| File | Header source | Tone / class |
|---|---|---|
| `pages/bank.astro`, `pages/envelopes.astro` | `<header slot="header">` | `headerToneClass("mint")` |
| `pages/budget/index.astro`, `pages/budget/import.astro`, `pages/budget/recycle-bin/index.astro` | page `<header>` (`bg-brand-sky-deep text-white`) | `headerToneClass("mint")` |
| `pages/gigs/index.astro` | `<header slot="header">` | `headerToneClass("sun")` |
| `pages/parent/assignments.astro`, `pages/calendar/month.astro` | `<header>` | `headerToneClass("sky")` |
| `pages/profile.astro` | `<header slot="header">` | `headerToneClass("cream")` |
| `pages/chat.astro`, `pages/soporte.astro`, `pages/dm/[id].astro`, `pages/parent/jarvis.astro` | `<ChatShell headerClass=…>` | `tone="cream"` |
| `pages/parent/index.astro` | `<header slot="header">` (slate gradient) | `bg-brand-ink text-white` (literal) |
| `components/home/KidHeader.astro` | `<header>` | child: `headerToneClass("sky")`; teen: `bg-[#1E2230] text-white` |

- [ ] **Step 1: Append the failing hero-tone checks**

Append to `test/section-tones.test.ts`:

```ts
/** Custom hero headers compose headerToneClass directly (spec "Custom hero headers"). */
const HERO_TONES: Record<string, HeaderTone> = {
    "pages/bank.astro": "mint",
    "pages/envelopes.astro": "mint",
    "pages/budget/index.astro": "mint",
    "pages/budget/import.astro": "mint",
    "pages/budget/recycle-bin/index.astro": "mint",
    "pages/gigs/index.astro": "sun",
    "pages/parent/assignments.astro": "sky",
    "pages/calendar/month.astro": "sky",
    "pages/profile.astro": "cream",
    "components/home/KidHeader.astro": "sky",
};

describe("custom hero headers use their section tone", () => {
    it.each(Object.entries(HERO_TONES))("%s → %s", (file, tone) => {
        const src = read(file);
        expect(src).toContain(`headerToneClass("${tone}")`);
        expect(src).not.toMatch(/<header[^>]*bg-gradient-to-/);
    });
});

describe("chat screens use ChatShell tone", () => {
    it.each(["pages/chat.astro", "pages/soporte.astro", "pages/dm/[id].astro", "pages/parent/jarvis.astro"])("%s → cream", (file) => {
        const src = read(file);
        expect(src).toMatch(/<ChatShell[\s\S]*?\btone="cream"/);
        expect(src).not.toMatch(/headerClass=/);
    });
    it("ChatShell renders through headerToneClass with no hardcoded white text", () => {
        const src = read("components/ui/ChatShell.astro");
        expect(src).toMatch(/headerToneClass\(tone\)/);
        expect(src).not.toMatch(/text-white|headerClass/);
    });
});

describe("home heroes", () => {
    it("parent hub hero is flat brand ink with white text", () => {
        expect(read("pages/parent/index.astro")).toMatch(/<header[\s\S]*?class="bg-brand-ink text-white/);
    });
    it("kid hero: teen keeps its dark skin, child uses the sky tone", () => {
        const src = read("components/home/KidHeader.astro");
        expect(src).toContain('"bg-[#1E2230] text-white"');
        expect(src).not.toMatch(/bg-brand-sky-deep/);
    });
});
```

- [ ] **Step 2: Run it — RED**

Run: `timeout 300 npx vitest run test/section-tones.test.ts </dev/null 2>&1 | tail -20`
Expected: FAIL on every new case (no `headerToneClass(...)` yet, ChatShell still `headerClass`).

- [ ] **Step 3: `ChatShell.astro`**

- Import: `import { headerToneClass, type HeaderTone } from "../../lib/headerTone";`
- Doc comment: replace the `@prop headerClass …` line with ` * @prop tone        Section tone for the header (chat screens use "cream"; see lib/headerTone.ts)`.
- Props: replace `headerClass: string;` with `tone: HeaderTone;`; destructure `tone` instead of `headerClass`.
- Header: `<header class={`${headerToneClass(tone)} pt-12 pb-4 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)] flex-shrink-0`}>`

- [ ] **Step 4: `KidHeader.astro`**

Replace `const bg = skin === "teen" ? "bg-[#1E2230]" : "bg-brand-sky-deep";` with:

```ts
import { headerToneClass } from "../../lib/headerTone";
// Teen keeps its dark skin; the child skin is the sky section tone (ink text, 6.5:1).
const skinClass = skin === "teen" ? "bg-[#1E2230] text-white" : headerToneClass("sky");
```

(the `import` goes with the other frontmatter imports). Change the opening tag to `<header class={`${skinClass} pt-12 pb-5 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]`}>` and remove `opacity-75` / `opacity-90` from the three text elements inside (the "Hola," line, the meter caption row, the released line). Chips keep `bg-white/15 border-white/25` (decorative, readable on both skins).

- [ ] **Step 5: Parent hub and the ten custom heroes**

- `src/pages/parent/index.astro`: the header's class becomes `bg-brand-ink text-white pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]` (was `bg-gradient-to-br from-slate-800 to-slate-700 text-white …`); inner `text-slate-300` stays (dark hero).
- Each file in the hero table: the header's class becomes ``class={`${headerToneClass("<tone>")} <the existing spacing/shape classes>`}`` — drop the old fill (`bg-gradient-…`/`bg-brand-sky-deep`) and `text-white`; add `import { headerToneClass } from "<relative path>/lib/headerTone";` to the frontmatter. Then apply Task 4's light-content replacement table to everything inside the `<header>` block.
- Where a custom header is only title + back link + one sub line (check `profile.astro`, `calendar/month.astro`), keep it as a custom header anyway — replacing it with `PageHeader` is allowed only if it renders the same content; do not restructure otherwise.

- [ ] **Step 6: Chat screens**

For `chat.astro`, `soporte.astro`, `dm/[id].astro`, `parent/jarvis.astro`: replace `headerClass="…"` with `tone="cream"` on `<ChatShell>`, then apply the light-content replacement table to the whole `slot="header"` fragment (the guard cannot see into these fragments — check every class in them by eye: `grep -n 'text-white\|/[0-9]0\b\|-100\|-200' <file>` inside the fragment).

- [ ] **Step 7: Title emoji**

Remove the emoji prefix (and the space after it) from the six `<h1>`s: `bank.astro` (`🏦`), `envelopes.astro` (`✉️`), `chat.astro` (`💬`), `soporte.astro` (`🛟`), `parent/jarvis.astro` (`🤖`), `dm/[id].astro` (`✉️`).

- [ ] **Step 8: GREEN — tones, guard ratchet, type check**

Run: `timeout 300 npx vitest run test/section-tones.test.ts </dev/null 2>&1 | tail -4`
Expected: PASS.
Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -E 'offenders match|expected [0-9]+ to be'`
Then set ALLOWANCE `"header-gradient": 0`, `"light-text-in-header": 0`, `"h1-emoji": 0`, `"header-class-prop": 0`, and lower any other rule whose printed actual count dropped (e.g. `white-on-brand-fill`, `deep-text`) to the printed count. Re-run: all eight rule cases PASS. If any of the four rules above is not 0, fix the offending file (never raise an allowance).
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?; grep -E 'Result|error' /tmp/b3-check.log | tail -5`
Expected: `exit=0`, `0 errors`.

- [ ] **Step 9: Commit**

```bash
git add -A src/components/ui/ChatShell.astro src/components/home/KidHeader.astro src/pages test/section-tones.test.ts test/visual-consistency.test.ts
git commit -m "feat(ux-b3): custom heroes, chat screens and home heroes on section tones; drop title emoji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Colored text → text-safe shades; faint text → ink-soft

**Files:**
- Modify: every non-exempt `src/**/*.{astro,ts}` containing `text-brand-{sky,mint,coral,sun}-deep` (≈ 60 files), `src/lib/toast.ts`, `test/visual-consistency.test.ts` (ALLOWANCE)

**Interfaces:**
- Consumes: tokens `text-brand-*-text` (Task 1); `ALLOWANCE` (Task 2).

- [ ] **Step 1: Pin the codemod regex with a test — RED**

Append to `test/visual-scan.test.ts`:

```ts
import { DEEP_TEXT_CODEMOD } from "./support/visual-scan";

describe("DEEP_TEXT_CODEMOD", () => {
    const run = (s: string) => s.replace(DEEP_TEXT_CODEMOD, "text-brand-$1-text");
    it("rewrites -deep text colors, keeping variant prefixes", () => {
        expect(run('class="text-brand-sky-deep hover:text-brand-mint-deep md:text-brand-sun-deep"')).toBe(
            'class="text-brand-sky-text hover:text-brand-mint-text md:text-brand-sun-text"',
        );
    });
    it("leaves fills, borders, rings, alpha tints and already-safe shades alone", () => {
        const s = 'class="bg-brand-sky-deep border-brand-coral-deep ring-brand-mint-deep/30 text-brand-sky-text text-brand-coral"';
        expect(run(s)).toBe(s);
    });
});
```

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -5`
Expected: FAIL — `DEEP_TEXT_CODEMOD` is not exported.

- [ ] **Step 2: Export the regex — GREEN**

Append to `test/support/visual-scan.ts`:

```ts
/** One-shot codemod regex (UX-B3 Task 6): text-brand-X-deep → text-brand-X-text. */
export const DEEP_TEXT_CODEMOD = /(?<![\w-])text-brand-(sky|mint|coral|sun)-deep(?![\w-])/g;
```

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 3: Apply the codemod to non-exempt files**

```bash
node --input-type=module -e '
import { readFileSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
const re = /(?<![\w-])text-brand-(sky|mint|coral|sun)-deep(?![\w-])/g;
const exempt = /^src\/(pages\/(login|register|index|tdah|privacidad|terminos|forgot-password|reset-password|verify-email|accept-invitation|404|500|kiosk)\.astro|pages\/admin\/|components\/ui\/AdminShell\.astro|components\/GuideShell\.astro)/;
const files = execSync("git ls-files src", { encoding: "utf8" }).split("\n").filter((f) => /\.(astro|ts)$/.test(f) && !exempt.test(f));
let n = 0;
for (const f of files) { const s = readFileSync(f, "utf8"); const t = s.replace(re, (_m, c) => (n++, `text-brand-${c}-text`)); if (t !== s) writeFileSync(f, t); }
console.log("replaced", n);
' </dev/null
```

Expected: `replaced N` with N ≈ 390 (non-exempt share of ~420).

- [ ] **Step 4: Dark-surface sweep (the spec exception)**

Run: `grep -rnE 'text-brand-(sky|mint|coral|sun)-text' src | grep -E 'bg-brand-ink\b|bg-slate-(7|8|9)00|bg-\[#1E2230\]|bg-gray-(8|9)00|bg-black' `
and for every file that has both a `-text` shade and a dark fill anywhere (`grep -lE 'bg-brand-ink\b|bg-slate-(7|8|9)00|bg-\[#' $(grep -rlE 'text-brand-(sky|mint|coral|sun)-text' src)`), open it and check each `-text` hit's element and nearest filled ancestor. Where the surface is dark, use the plain brand color instead (`text-brand-sky-text` → `text-brand-sky`, etc.). Record each such change in your report (file:line). Expected: few or none (all 2026-09-29 hits sat on light surfaces).

- [ ] **Step 5: Faint text**

`src/lib/toast.ts`: in the close button, `text-slate-400 hover:text-slate-600` → `text-brand-ink-soft hover:text-brand-ink`. Any other non-exempt `text-slate-400|500` / `text-gray-400|500` the guard lists → `text-brand-ink-soft`.

- [ ] **Step 6: Ratchet — GREEN**

Set ALLOWANCE `"deep-text": 0`, `"faint-text": 0`.
Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -4`
Expected: all pass. If `deep-text` is not 0, the remaining hits are in non-exempt files the command skipped (e.g. `.css`) — fix them by hand.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?`
Expected: `exit=0`.

- [ ] **Step 7: Commit**

```bash
git add -A src test/support/visual-scan.ts test/visual-scan.test.ts test/visual-consistency.test.ts
git commit -m "fix(ux-b3): colored text on AA-safe -text shades; faint gray text on ink-soft

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: White text on brand fills — money & budget area

**Files:**
- Modify (only offenders the guard lists for `white-on-brand-fill` in these files): `src/pages/budget/{settings,transactions,receipt-drafts,import,index,reports}.astro`, `src/pages/budget/recycle-bin/index.astro`, `src/pages/parent/settings/{family-bank,envelopes,subscription,referrals}.astro`, `src/pages/parent/settings/subscription/activate.astro`, `src/pages/parent/payouts.astro`, `src/pages/{bank,envelopes}.astro`, `src/components/budget/ReceiptScanSheet.astro`, `src/components/{MoveMoneyModal,AssignFundsModal,FABModal,AccountCreateModal,RecycleBinTable,PeriodSelector,ReportSubTabs}.astro`; `test/visual-consistency.test.ts` (ALLOWANCE)

**Interfaces:**
- Consumes: `buttonClass(variant, size)` (Task 1); `ALLOWANCE` (Task 2).

**Fix rule for each offender** (spec "Buttons and colored fills"):
1. **A call-to-action** (`<button>`, or `<a>`/`<label>` styled as a button — padded, rounded, one action) → replace its fill/text/hover/border/rounded/shadow/font classes with the kit button: in Astro markup ``class={`${buttonClass("<variant>", "<size>")} <layout-only classes it had: w-full, mt-*, flex-1, …>`}`` (import `buttonClass` from `lib/buttonClasses`); in a hoisted `<script>` (no `is:inline`/`define:vars`) import `buttonClass` and interpolate it; in `is:inline`/`define:vars` scripts copy the literal string `buttonClass` returns (print it with `node -e`). Variant by fill: sky/sky-deep → `"secondary"`, mint/mint-deep → `"mint"`, coral/coral-deep → `"primary"`, sun/sun-deep → `"sun"`. Size: `px-3 py-1.5`/`text-sm` → `"sm"`, `py-3`/`text-base` → `"md"`, `py-4`/`text-lg` → `"lg"`, icon-only round → `"icon"`.
2. **Anything else on a brand fill** (active tab/segment pill, chip, badge, avatar, count bubble, progress label, selected state) → keep the fill; `text-white` / `text-white/NN` (incl. `hover:`/`peer-checked:` variants) → `text-brand-ink`.
3. Never switch to white text on a darker fill, never introduce `text-brand-*-deep`.

- [ ] **Step 1: List this task's offenders — RED baseline**

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts -t white-on-brand-fill </dev/null 2>&1 | grep -E '^\s*(pages/(budget|bank|envelopes|parent/(payouts|settings/(family-bank|envelopes|subscription|referrals)))|components/(budget/ReceiptScanSheet|MoveMoneyModal|AssignFundsModal|FABModal|AccountCreateModal|RecycleBinTable|PeriodSelector|ReportSubTabs))' | tee /tmp/b3-t7-offenders.txt | wc -l`
Expected: ≈ 60 lines (the offender list printed in the assertion message).

- [ ] **Step 2: Fix every listed offender** per the fix rule. Keep behavior (ids, data-attributes, handlers, `type=` attributes) untouched.

- [ ] **Step 3: Ratchet — GREEN**

Re-run the Step 1 command. Expected: `0`.
Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -E 'expected [0-9]+ to be'` → lower `"white-on-brand-fill"` to the printed actual count (only the Task 8 files remain).
Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -4` → all pass.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?` → `exit=0`.

- [ ] **Step 4: Commit**

```bash
git add -A src test/visual-consistency.test.ts
git commit -m "fix(ux-b3): money & budget screens — kit buttons and ink text on brand fills

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: White text on brand fills — everything else

**Files:**
- Modify (only offenders the guard lists): every remaining non-exempt file in the `white-on-brand-fill` offender list — expected `src/pages/parent/{approvals,members,starter-packs,assignments,tasks,rewards,index}.astro`, `src/pages/parent/settings/family.astro`, `src/pages/parent/tasks/[id]/edit.astro`, `src/pages/{profile,family-cup,rewards,meals}.astro`, `src/pages/pet/{shop,quests}.astro`, `src/components/{BottomNav,MoreSheet,TaskCreateModal}.astro`, `src/components/deck/TaskDeck.astro`; `test/visual-consistency.test.ts` (ALLOWANCE)

**Interfaces:**
- Consumes: `buttonClass` (Task 1); `ALLOWANCE` (Task 2).

Same **fix rule** as Task 7 (CTA → `buttonClass`; everything else on a brand fill → `text-brand-ink`; never white on a darker fill; never `-deep` text). `BottomNav`/`MoreSheet` offenders are active-state pills/badges → rule 2.

- [ ] **Step 1: List the remaining offenders — RED**

Set ALLOWANCE `"white-on-brand-fill": 0`.
Run: `timeout 300 npx vitest run test/visual-consistency.test.ts -t white-on-brand-fill </dev/null 2>&1 | grep -E '^\s*(pages|components|lib)/' | tee /tmp/b3-t8-offenders.txt`
Expected: FAIL; ≈ 30 offenders, all outside the Task 7 file list.

- [ ] **Step 2: Fix every listed offender** per the fix rule.

- [ ] **Step 3: GREEN**

Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -4` → all pass (every ALLOWANCE entry is now 0).
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?` → `exit=0`.

- [ ] **Step 4: Commit**

```bash
git add -A src test/visual-consistency.test.ts
git commit -m "fix(ux-b3): kit buttons and ink text on brand fills across the rest of the app

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: One line-icon set — `lib/icons.ts` + `Icon.astro`

**Files:**
- Create: `src/lib/icons.ts`, `src/components/ui/Icon.astro`, `test/icons.test.ts`
- Modify: `src/components/MoreSheet.astro` (the `const I = { … }` map at lines 32–58, the `Link.icon` type, the four inline `<svg>` at ~141/153/163/178), `src/components/ui/PageHeader.astro` (back chevron `<svg>`)

**Interfaces:**
- Produces: `ICONS: Record<IconName, string>`; `type IconName = keyof typeof ICONS` (from `src/lib/icons.ts`); `<Icon name={IconName} class?={string} />` (from `src/components/ui/Icon.astro`, default class `"h-6 w-6"`, stroke width 2, `aria-hidden="true"`).

- [ ] **Step 1: Write the failing icon test**

`test/icons.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { ICONS } from "../src/lib/icons";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

const EXPECTED = [
    "bell", "pet", "meals", "shopping", "calendar", "chat", "dm", "profile", "members", "rewards",
    "consequences", "assignments", "jarvis", "kiosk", "operator", "settings", "tasks", "payouts",
    "analytics", "help", "support", "routines", "back", "close", "language", "logout",
];

describe("ICONS — the one line-icon set", () => {
    it("has exactly the chrome icons", () => {
        expect(Object.keys(ICONS).sort()).toEqual([...EXPECTED].sort());
    });
    it("every entry is a heroicons-outline path", () => {
        for (const [name, d] of Object.entries(ICONS)) expect(d, name).toMatch(/^M[\d.]/);
    });
});

describe("chrome renders through Icon", () => {
    it("MoreSheet has no private icon map or inline svg", () => {
        const src = read("components/MoreSheet.astro");
        expect(src).toMatch(/import Icon from "\.\/ui\/Icon\.astro"/);
        expect(src).not.toMatch(/const I\s*=\s*\{/);
        expect(src).not.toMatch(/<svg\b/);
    });
    it("PageHeader back link uses Icon", () => {
        const src = read("components/ui/PageHeader.astro");
        expect(src).toMatch(/<Icon name="back"/);
        expect(src).not.toMatch(/<svg\b/);
    });
});
```

- [ ] **Step 2: Run it — RED**

Run: `timeout 300 npx vitest run test/icons.test.ts </dev/null 2>&1 | tail -5`
Expected: FAIL — `Failed to resolve import "../src/lib/icons"`.

- [ ] **Step 3: Create `src/lib/icons.ts`**

Move the 22 entries of MoreSheet's `const I = { … }` map verbatim (keep the `support` comment), and add four more paths taken verbatim from the current inline SVGs:

```ts
/**
 * The ONE chrome icon set (UX-B3): heroicons outline, 24×24, stroke 2, one
 * <path d> each. Chrome (nav, More sheet, header titles/actions, toolbars,
 * row actions) uses these via <Icon name=…>. Emoji are for kid delight only:
 * big tiles, empty states, celebrations, and user-picked content.
 */
export const ICONS = {
    // …the 22 entries moved verbatim from MoreSheet.astro (bell … routines)…
    back: "M15 19l-7-7 7-7",
    close: "M6 18L18 6M6 6l12 12",
    language: "M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129",
    logout: "M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1",
} as const;

export type IconName = keyof typeof ICONS;
```

(The "…moved verbatim…" line is an instruction: paste the 22 `name: "path",` lines from `MoreSheet.astro` lines 33–58 in their current order.)

- [ ] **Step 4: Create `src/components/ui/Icon.astro`**

```astro
---
/**
 * Icon — one chrome line icon from lib/icons.ts (heroicons outline, 24×24).
 * @prop name   IconName
 * @prop class  Size/color classes (default "h-6 w-6"; color via currentColor)
 */
import { ICONS, type IconName } from "../../lib/icons";

interface Props {
  name: IconName;
  class?: string;
}
const { name, class: className = "h-6 w-6" } = Astro.props;
---

<svg class={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={ICONS[name]} />
</svg>
```

- [ ] **Step 5: Use it in `MoreSheet` and `PageHeader`**

- `MoreSheet.astro`: add `import Icon from "./ui/Icon.astro";` and `import type { IconName } from "../lib/icons";`; delete the `// Icon paths …` comment and the whole `const I = { … };` map; change `type Link = { …; icon: string; … }` to `icon: IconName`; replace every `icon: I.<name>` with `icon: "<name>"`; replace the four inline `<svg …>…</svg>` with `<Icon name="close" />`, `<Icon name={l.icon} class="h-6 w-6 text-brand-ink" />`, `<Icon name="language" class="h-5 w-5" />`, `<Icon name="logout" class="h-5 w-5" />` respectively (keep each svg's existing size/color classes).
- `PageHeader.astro`: add `import Icon from "./Icon.astro";` and replace the back-link `<svg …>…</svg>` with `<Icon name="back" class="h-4 w-4" />`.

- [ ] **Step 6: GREEN**

Run: `timeout 300 npx vitest run test/icons.test.ts </dev/null` → PASS.
Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -4` → all pass.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?` → `exit=0` (a mistyped `icon: "…"` name is a type error here).

- [ ] **Step 7: Commit**

```bash
git add src/lib/icons.ts src/components/ui/Icon.astro src/components/MoreSheet.astro src/components/ui/PageHeader.astro test/icons.test.ts
git commit -m "feat(ux-b3): one chrome line-icon set (lib/icons + Icon.astro)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Lock the guard strict; docs; full verification

**Files:**
- Modify: `test/visual-consistency.test.ts`, `CLAUDE.md` (repo root, section "### Frontend (Astro 5)"), `docs/superpowers/specs/2026-09-29-ux-b3-visual-consistency-design.md` (Status line)

**Interfaces:**
- Consumes: every ALLOWANCE entry is 0 (Tasks 3–8).

- [ ] **Step 1: Make the guard strict — delete the allowance**

In `test/visual-consistency.test.ts`: delete the `ALLOWANCE` constant and its doc comment; change the per-rule test to

```ts
    it.each([...RULE_IDS])("%s: no offenders", (rule) => {
        const offenders = hits.filter((h) => h.endsWith(`[${rule}]`));
        expect(offenders, `${rule} offenders`).toEqual([]);
    });
```

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null` → PASS (9 cases).
Mutation check (proves the guard bites): temporarily add `<p class="bg-brand-sky text-white">x</p>` to `src/pages/rewards.astro`, run the same command → Expected FAIL naming `pages/rewards.astro` `[white-on-brand-fill]`; revert the line (`git checkout src/pages/rewards.astro`), re-run → PASS.

- [ ] **Step 2: Document the rule in `CLAUDE.md`**

In the repo-root `CLAUDE.md`, directly after the paragraph that starts `**Dialogs (UX-B1):**`, add:

```markdown
**Visual system (UX-B3):** headers are colored by SECTION, never per page — `tone` on `PageLayout`/`PageHeader`/`ChatShell`, or `headerToneClass(tone)` (`lib/headerTone.ts`) for a custom hero: sky = doing things, mint = money, sun = earning & winning, coral = treats/care/home, cream = talk & settings (parent hub hero = `bg-brand-ink`). Text on a brand fill is ink, never white; buttons come from `buttonClass` (`lib/buttonClasses.ts`, also behind `Button.astro`); colored text uses `text-brand-{sky,mint,coral,sun}-text` — the `-deep` shades are fills/hovers only. Chrome icons come from `lib/icons.ts` via `<Icon>`; emoji only for kid delight and user-picked content, never in an `<h1>`. There is no dark mode. `frontend/test/visual-consistency.test.ts` fails CI on violations; `frontend/test/contrast.test.ts` checks every token pair ≥ 4.5:1.
```

- [ ] **Step 3: Spec status**

In the spec, change `**Status:** design approved in chat (2026-09-29), pending written-spec review` to `**Status:** approved 2026-09-29; implemented on feat/ux-b3-visual-consistency`.

- [ ] **Step 4: Full verification**

Run: `timeout 600 npx vitest run </dev/null 2>&1 | tail -5` → all test files pass.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3-check.log 2>&1; echo exit=$?; tail -3 /tmp/b3-check.log` → `exit=0`, `0 errors`.
Run: `timeout 900 npm run build </dev/null > /tmp/b3-build.log 2>&1; echo exit=$?; tail -3 /tmp/b3-build.log` → `exit=0`.
Run: `grep -rn "headerClass\|data-theme=\"dark\"\|BottomSheet\|FormField" src | grep -v '^src/pages/login.astro'` → no output.
Run: `grep -rnE '🏦|✉️|💬|🛟|🤖|from-(violet|amber|slate|emerald|indigo|cyan|teal|fuchsia)-' ../e2e-tests --include='*.ts' | grep -v node_modules` → no output (if any line prints, update that Playwright spec to the new title text / classes and commit it with this task).

- [ ] **Step 5: Commit**

```bash
git add test/visual-consistency.test.ts ../CLAUDE.md ../docs/superpowers/specs/2026-09-29-ux-b3-visual-consistency-design.md
git commit -m "test(ux-b3): visual guard strict; document the visual system rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
