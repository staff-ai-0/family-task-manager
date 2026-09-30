# UX-B3 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four readability gaps B3 left: teen palette, colored text on tints, the tour's Next button, and emoji in page titles — each pinned by a test.

**Architecture:** Token changes live in `src/styles/global.css`; the contrast test learns to read every `body[data-ui-mode]` block and tint pairs; the visual scanner learns two shapes (CSS declaration blocks, `title` attributes on `PageLayout`/`PageHeader`); then the offending files are fixed.

**Tech Stack:** Astro 5, Tailwind CSS v4 (`@theme` tokens), vitest 4 (node env).

**Spec:** `docs/superpowers/specs/2026-09-30-ux-b3-followups-design.md`

## Global Constraints

- Paths are relative to `frontend/` unless they start with `docs/` or are `CLAUDE.md`; run commands from `frontend/` with `</dev/null` and a `timeout`.
- New text shades, exact: `--color-brand-sky-text: #165F84;` `--color-brand-mint-text: #1B694A;` `--color-brand-coral-text: #9E3A1B;` `--color-brand-sun-text: #8A5A00;` (sun unchanged). No other token value changes.
- Teen mode keeps ONLY `body[data-ui-mode="teen"] .rounded-2xl { border-radius: 0.75rem; }` and `.rounded-xl { border-radius: 0.5rem; }`; the adult block (`--color-brand-cream: #FAFAFA; --color-brand-cream-deep: #EEEEEE;`) stays.
- Tour Next button: `background: var(--color-brand-sky, #4FB8E6); color: var(--color-brand-ink, #1F2937); border: 2px solid var(--color-brand-ink, #1F2937);`.
- Exempt files (never edit): `src/pages/{login,register,index,tdah,privacidad,terminos,forgot-password,reset-password,verify-email,accept-invitation,404,500,kiosk}.astro`, `src/pages/admin/**`, `src/components/ui/AdminShell.astro`, `src/components/GuideShell.astro`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Teen screens after the palette drop** — anything that assumed teen coral = blue (e.g. a teen-only element styled `bg-brand-coral` meant as "blue") now turns coral; a teen expects a coherent screen. Pinned by the post-deploy teen pass (diego.demo) in Task 4 Step 5.
2. **Title text used elsewhere** — the `title` prop also feeds the browser `<title>`; e2e specs or tour anchors may match the emoji title. Pinned by Task 3 Step 5 (e2e grep).
3. **CSS-block rule firing on `.astro` expressions** — `{ … }` JSX expressions that mention a brand var and `white` must not false-positive. Pinned by Task 2's unit case "JS object literal with unrelated color" and the strict tree guard.
4. **Darker text shades landing on a dark surface** — B3 verified no `-text` shade sits on a dark fill; darker shades only raise contrast on light surfaces. Pinned by the unchanged strict guard (`text-shade-on-fill`) + contrast test.
5. **A future UI mode block written with a different selector shape** (e.g. `[data-ui-mode="x"] body`) would escape the per-mode test. Pinned by Task 1's assertion that the parsed modes include `default` and `adult`.

---

### Task 1: Contrast test per UI mode + tints; drop teen palette; darker text shades

**Files:**
- Modify: `test/support/contrast.ts` (add `mix`), `test/contrast.test.ts` (rewrite the token suite), `src/styles/global.css` (the four `-text` lines in `@theme`; the teen block + its comment)

**Interfaces:**
- Produces: `mix(fg: string, bg: string, alpha: number): string` in `test/support/contrast.ts` — composite `#RRGGBB` `fg` at `alpha` over opaque `bg`, returns uppercase `#RRGGBB`.

- [ ] **Step 1: Add `mix` and rewrite the token suite (tests first)**

Append to `test/support/contrast.ts`:

```ts
/** Composite `fg` at `alpha` (0–1) over opaque `bg`; #RRGGBB in, uppercase #RRGGBB out. */
export function mix(fg: string, bg: string, alpha: number): string {
    const rgb = (h: string) => {
        const n = parseInt(h.replace("#", ""), 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const [f, b] = [rgb(fg), rgb(bg)];
    return "#" + f.map((c, i) => Math.round(c * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, "0")).join("").toUpperCase();
}
```

In `test/contrast.test.ts`: change the import to `import { contrastRatio, mix } from "./support/contrast";`, keep `CSS`, `AA`, `WHITE`, `token()` and the `describe("contrastRatio", …)` block, add a `mix` unit block, and REPLACE the whole `describe("brand token contrast (WCAG AA, UX-B3)", …)` block with:

```ts
describe("mix", () => {
    it("composites fg over bg by alpha", () => {
        expect(mix("#000000", "#FFFFFF", 0.5)).toBe("#808080");
        expect(mix("#4FB8E6", "#FFFFFF", 1)).toBe("#4FB8E6");
        expect(mix("#4FB8E6", "#FFFFFF", 0)).toBe("#FFFFFF");
    });
});

/** --color-brand-* overrides declared in each `body[data-ui-mode="<mode>"] { … }` block. */
function modeOverrides(): Record<string, Record<string, string>> {
    const modes: Record<string, Record<string, string>> = { default: {} };
    for (const m of CSS.matchAll(/body\[data-ui-mode="([a-z]+)"\]\s*\{([^}]*)\}/g)) {
        const vars = (modes[m[1]] ??= {});
        for (const v of m[2].matchAll(/--color-brand-([a-z-]+):\s*(#[0-9A-Fa-f]{6})/g)) vars[v[1]] = v[2];
    }
    return modes;
}

const MODES = modeOverrides();

it("parses the default and adult UI modes", () => {
    expect(Object.keys(MODES)).toEqual(expect.arrayContaining(["default", "adult"]));
});

it("teen mode uses the default palette (decision 2026-09-30: teen = corners only)", () => {
    expect(MODES.teen ?? {}).toEqual({});
});

describe.each(Object.entries(MODES))("brand token contrast in %s mode (WCAG AA)", (_mode, over) => {
    const tok = (name: string) => over[name] ?? token(name);
    const surfaces = () => [WHITE, tok("cream"), tok("cream-deep")];

    it.each(["sky", "mint", "sun", "coral", "cream"])("ink text on the %s header tone", (tone) => {
        expect(contrastRatio(tok("ink"), tok(tone))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky-deep", "mint-deep", "sun-deep", "coral-deep"])("ink text on the %s hover fill", (fill) => {
        expect(contrastRatio(tok("ink"), tok(fill))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky", "mint", "coral", "sun"])("%s-text on white, cream and cream-deep", (hue) => {
        for (const bg of surfaces()) expect(contrastRatio(tok(`${hue}-text`), bg)).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky", "mint", "coral", "sun"])("%s-text on its own 30%% tint over white, cream and cream-deep", (hue) => {
        for (const bg of surfaces()) {
            expect(contrastRatio(tok(`${hue}-text`), mix(tok(hue), bg, 0.3))).toBeGreaterThanOrEqual(AA);
        }
    });

    it("white text on the ink parent-hub hero", () => {
        expect(contrastRatio(WHITE, tok("ink"))).toBeGreaterThanOrEqual(AA);
    });
});
```

- [ ] **Step 2: Run — RED**

Run: `timeout 300 npx vitest run test/contrast.test.ts </dev/null 2>&1 | grep -E '✓|×|FAIL|passed|failed' | tail -25`
Expected: FAIL — "teen mode uses the default palette" (teen has 8 overrides); teen-mode ink on coral / coral-deep / sun-deep; tint cases for sky/mint/coral in default and adult modes. `mix` cases pass.

- [ ] **Step 3: Change the tokens**

In `src/styles/global.css` `@theme`, set exactly:

```css
  --color-brand-sky-text:   #165F84;
  --color-brand-mint-text:  #1B694A;
  --color-brand-coral-text: #9E3A1B;
  --color-brand-sun-text:   #8A5A00;
```

Replace the teen section (from the `/* ---------- Teen UI mode (W4.2) ----------` comment through the two `.rounded-*` rules) with:

```css
/* ---------- Teen UI mode (W4.2) ----------
   Activated by data-ui-mode="teen" on <body>. Teens use the same brand
   palette as kids (their own colors were dropped 2026-09-30: dark text on
   the teen blue failed contrast); only the corner rounding is less
   playful. Their home header keeps its dark skin (KidHeader). */
body[data-ui-mode="teen"] .rounded-2xl { border-radius: 0.75rem; }
body[data-ui-mode="teen"] .rounded-xl  { border-radius: 0.5rem; }
```

- [ ] **Step 4: Run — GREEN, then the suite**

Run: `timeout 300 npx vitest run test/contrast.test.ts </dev/null 2>&1 | tail -4` → all pass.
Run: `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.

- [ ] **Step 5: Commit**

```bash
git add test/support/contrast.ts test/contrast.test.ts src/styles/global.css
git commit -m "fix(ux-b3): drop teen palette; darker text shades pass on tints; contrast test per UI mode

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Guard reads CSS blocks; tour Next button readable

**Files:**
- Modify: `test/support/visual-scan.ts` (new CSS-block pass inside `scanVisual`, before `return hits`), `test/visual-scan.test.ts` (white-on-brand-fill describe), `src/lib/tour-theme.css` (`.driver-popover .driver-popover-next-btn` block)

**Interfaces:**
- Consumes: `scanVisual`, `Hit`, `lineAt` (existing in visual-scan.ts).

- [ ] **Step 1: Failing unit tests** — append inside `describe("scanVisual — white-on-brand-fill", …)`:

```ts
    it("flags a CSS block with a brand background and white text", () => {
        const css = [
            ".driver-popover .driver-popover-next-btn {",
            "    background: var(--color-brand-sky-deep, #2563eb);",
            "    color: #fff;",
            "}",
            ".b { background-color: var(--color-brand-mint); color: white; }",
        ].join("\n");
        expect(rules(css, "white-on-brand-fill").map((h) => h.line)).toEqual([3, 5]);
    });
    it("leaves CSS blocks with ink text, ink backgrounds or no brand var alone", () => {
        const css = [
            ".a { background: var(--color-brand-sky); color: var(--color-brand-ink); }",
            ".b { background: var(--color-brand-ink); color: #fff; }",
            ".c { background-color: #fff; color: white; }",
            "const style = { background: 'var(--color-brand-sky)', border: 0 };",
        ].join("\n");
        expect(rules(css, "white-on-brand-fill")).toEqual([]);
    });
```

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -6`
Expected: FAIL — the first case returns `[]`.

- [ ] **Step 2: Implement** — add near the other regex constants in `test/support/visual-scan.ts`:

```ts
// CSS declaration blocks (.css files, <style> blocks): brand background + white text.
const CSS_BLOCK = /\{([^{}]*)\}/g;
const CSS_BRAND_BG = /background(?:-color)?\s*:\s*var\(\s*--color-brand-(?:sky|mint|coral|sun)(?:-deep)?(?![\w-])/;
const CSS_WHITE_TEXT = /(?:^|[;{\s])color\s*:\s*(?:#fff(?:fff)?|white)(?![\w-])/i;
```

and inside `scanVisual`, just before the final `return`:

```ts
    for (const m of text.matchAll(CSS_BLOCK)) {
        const body = m[1];
        if (!CSS_BRAND_BG.test(body)) continue;
        const w = CSS_WHITE_TEXT.exec(body);
        if (w) {
            hits.push({ rule: "white-on-brand-fill", line: lineAt(text, (m.index ?? 0) + 1 + w.index), match: "color: white on brand background (CSS)" });
        }
    }
```

(If the final `return` sorts/dedupes `hits`, keep it after this loop.)

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -4` → PASS.

- [ ] **Step 3: Tree guard — RED on the tour theme**

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -A4 'white-on-brand-fill'`
Expected: FAIL naming `lib/tour-theme.css` (and any other real CSS offender — fix each the same way: text → `var(--color-brand-ink, #1F2937)`).

- [ ] **Step 4: Fix the tour button** — in `src/lib/tour-theme.css` replace the `.driver-popover .driver-popover-next-btn { … }` block with:

```css
.driver-popover .driver-popover-next-btn {
    background: var(--color-brand-sky, #4FB8E6);
    color: var(--color-brand-ink, #1F2937);
    border: 2px solid var(--color-brand-ink, #1F2937);
}
```

Run: `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.

- [ ] **Step 5: Commit**

```bash
git add test/support/visual-scan.ts test/visual-scan.test.ts src/lib/tour-theme.css
git commit -m "fix(ux-b3): tour Next button ink on sky; guard reads CSS declaration blocks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: No emoji in page titles

**Files:**
- Modify: `test/support/visual-scan.ts` (title-attribute pass next to the `H1_BLOCK` loop), `test/visual-scan.test.ts` (h1-emoji describe), and the 13 pages: `src/pages/{routines,calendar,shopping,dm,meals,pet,notifications}.astro`, `src/pages/calendar/scan.astro`, `src/pages/pet/{shop,quests}.astro`, `src/pages/parent/{kiosk,routines,analytics}.astro`

- [ ] **Step 1: Failing unit tests** — append inside `describe("scanVisual — h1-emoji", …)`:

```ts
    it("flags an emoji in a PageLayout / PageHeader title attribute", () => {
        const src = [
            "<PageLayout",
            "    title={`📅 ${labels.title}`}",
            "    role={user.role}",
            ">",
            '<PageHeader title={es ? "🎯 Meta" : "🎯 Goal"} tone="sky" />',
        ].join("\n");
        expect(rules(src, "h1-emoji").map((h) => h.line)).toEqual([2, 5]);
    });
    it("ignores emoji-free titles and other components' title/icon props", () => {
        const src = [
            '<PageLayout title="Settings" tone="cream">',
            '<SettingsAccordion id="accounts" title={es ? "Cuentas" : "Accounts"} icon="🏦">',
            '<Card title="🎯 goal" />',
        ].join("\n");
        expect(rules(src, "h1-emoji")).toEqual([]);
    });
```

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -6` → FAIL (first case `[]`).

- [ ] **Step 2: Implement** — add the constant next to `H1_BLOCK`:

```ts
// PageLayout/PageHeader render their `title` prop as the page <h1>.
const TITLE_ATTR = /<(?:PageLayout|PageHeader)\b[^>]*?\btitle=(\{`[^`]*`\}|\{[^}]*\}|"[^"]*")/g;
```

and right after the `H1_BLOCK` loop in `scanVisual`:

```ts
    for (const m of text.matchAll(TITLE_ATTR)) {
        if (EMOJI.test(m[1])) {
            hits.push({ rule: "h1-emoji", line: lineAt(text, (m.index ?? 0) + m[0].length - m[1].length), match: "title=" });
        }
    }
```

Run: `timeout 300 npx vitest run test/visual-scan.test.ts </dev/null 2>&1 | tail -4` → PASS.

- [ ] **Step 3: Tree guard — RED**

Run: `timeout 300 npx vitest run test/visual-consistency.test.ts </dev/null 2>&1 | grep -A16 'h1-emoji'`
Expected: FAIL listing the 13 pages' `title=` lines.

- [ ] **Step 4: Strip the emoji** — in each listed page change `title={`<emoji> ${X}`}` to `title={X}` (e.g. `title={`📅 ${labels.title}`}` → `title={labels.title}`, `title={`⛅ ${L.title}`}` → `title={L.title}`). Change nothing else.

Run: `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.

- [ ] **Step 5: e2e / anchors check**

Run: `grep -rnE '⛅|📅|🛒|📄|✉️|🍽️|🐾|🛍️|🔔|🗺️|📺|📊' ../e2e-tests --include='*.ts' | grep -v node_modules | grep -iE 'title|heading|toHaveTitle'`
Expected: no output; if any spec matches a title with its emoji, update it to the emoji-free title in this commit.

- [ ] **Step 6: Commit**

```bash
git add test/support/visual-scan.ts test/visual-scan.test.ts src/pages ../e2e-tests
git commit -m "fix(ux-b3): no emoji in page titles; h1-emoji rule reads PageLayout/PageHeader title

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Docs + full verification

**Files:**
- Modify: `CLAUDE.md` (repo root), `docs/superpowers/specs/2026-09-30-ux-b3-followups-design.md` (Status)

- [ ] **Step 1: CLAUDE.md** — in the "Visual system (UX-B3)" paragraph replace `` `frontend/test/contrast.test.ts` checks every default-palette token pair ≥ 4.5:1 (teen-mode palette not yet covered).`` with `` `frontend/test/contrast.test.ts` checks every token pair ≥ 4.5:1 in every UI mode, including each text shade on its own 30 % tint. Teen mode uses the same palette as kids (only corners differ).``

- [ ] **Step 2: Spec status** → `**Status:** approved 2026-09-30; implemented on fix/ux-b3-followups`.

- [ ] **Step 3: Verify**

Run: `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.
Run: `timeout 900 npx astro check </dev/null > /tmp/b3f-check.log 2>&1; echo exit=$?` → `exit=0`.
Run: `timeout 900 npm run build </dev/null > /tmp/b3f-build.log 2>&1; echo exit=$?; tail -2 /tmp/b3f-build.log` → `exit=0`, `Complete!`.

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md ../docs/superpowers/specs/2026-09-30-ux-b3-followups-design.md
git commit -m "docs(ux-b3): contrast test covers every UI mode; teen palette dropped

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: After deploy** — prod pass at 390 px as `diego.demo@agent-ia.mx` (TEEN, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7`): `/dashboard`, `/rewards`, `/gigs`, `/bank` — coral/sun/mint headers in the kid palette with ink text, dark teen home header, tighter corners; and a kid page with a mint/20 flash or chip.
