/**
 * Visual-consistency scanner (UX-B3). Pure: one file's text in, rule hits out.
 * The tree walk, exemptions and allowances live in visual-consistency.test.ts.
 *
 * Class tokens are matched with their variant prefixes (hover:, md:, group-hover:)
 * and optional /NN alpha. The pairing rules (white-on-brand-fill, text-shade-on-fill,
 * hidden-display-conflict) look at "class strings":
 *  - one quoted string on one line ("…" / '…'), so a ternary's two branches are never
 *    mixed up;
 *  - a backtick template literal, across lines, with `${}` nesting (a literal nested in
 *    an interpolation is part of the outer one — F-3c), with the branches of one
 *    conditional interpolation as alternatives that never pair (see classCombos).
 *    white-on-brand-fill pairs the whole literal otherwise (spec rule 2, fix-round
 *    T2-1: every element of client-rendered markup together); the two newer rules
 *    also split it per `class="…"` attribute, because `hidden`, `inline-flex` and the
 *    -text shades sit on sibling elements all the time;
 *  - an array literal / `class:list={[…]}`: strings from DIFFERENT elements pair,
 *    two strings inside one element (ternary branches) don't (F-3b);
 *  - white-on-brand-fill only: a file that adds/toggles/replaces a brand fill via
 *    `classList` at runtime makes every light text token in it suspect (T2-1).
 * Within a class string, fill + text pairing is variant-aware (textOnFill): a hover that
 * swaps BOTH fill and text (hover:bg-brand-ink hover:text-brand-cream) is not a pair.
 * Backtick literals are masked out of the per-line quote scan so they aren't double
 * counted, and identical hits are reported once.
 */
export type RuleId =
    | "header-gradient"
    | "light-text-in-header"
    | "white-on-brand-fill"
    | "text-shade-on-fill"
    | "hidden-display-conflict"
    | "deep-text"
    | "faint-text"
    | "h1-emoji"
    | "dark-theme"
    | "header-class-prop";

export const RULE_IDS: readonly RuleId[] = [
    "header-gradient",
    "light-text-in-header",
    "white-on-brand-fill",
    "text-shade-on-fill",
    "hidden-display-conflict",
    "deep-text",
    "faint-text",
    "h1-emoji",
    "dark-theme",
    "header-class-prop",
];

/** One-shot codemod regex (UX-B3 Task 6): text-brand-X-deep → text-brand-X-text. */
export const DEEP_TEXT_CODEMOD = /(?<![\w-])text-brand-(sky|mint|coral|sun)-deep(?![\w-])/g;

export interface Hit {
    rule: RuleId;
    line: number;
    match: string;
}

const START = "(?<![\\w-])"; // token must not continue a longer word
const V = "(?:[a-z-]+:)*"; // variant prefixes
const BRAND_FILL = new RegExp(`${START}${V}bg-brand-(?:sky|mint|coral|sun)(?:-deep)?(?:/\\d+)?(?![\\w-])`);
// Light text that fails on every brand fill: white, and the cream surfaces (F-3e —
// cream on sky/mint/coral/sun is 1.5–2.2:1).
const LIGHT_ON_FILL = new RegExp(`${START}${V}text-(?:white|brand-cream(?:-deep)?)(?:/\\d+)?(?![\\w-])`);
const LIGHT_ON_FILL_ALL = new RegExp(LIGHT_ON_FILL.source, "g");
const DEEP_TEXT = new RegExp(`${START}${V}text-brand-(?:sky|mint|coral|sun)-deep(?![\\w-])`, "g");
const FAINT_TEXT = new RegExp(`${START}${V}text-(?:slate|gray)-(?:400|500)(?![\\w-])`, "g");
const LIGHT_TEXT = new RegExp(
    `${START}${V}text-(?:white|brand-cream(?:-deep)?|[a-z]+-(?:50|100|200|300))(?:/\\d+)?(?![\\w-])`,
    "g",
);
// text-brand-ink-soft is legal body copy but fails AA on the sky/coral tone fills (T4-2
// controller ruling); flagged ONLY alongside LIGHT_TEXT in the header contexts below
// (never in white-on-brand-fill, faint-text or anywhere else — ink-soft stays legal in bodies).
const INK_SOFT_TEXT = new RegExp(`${START}${V}text-brand-ink-soft(?:/\\d+)?(?![\\w-])`, "g");
const QUOTED = /"([^"\n]*)"|'([^'\n]*)'/g; // backtick literals are handled separately — they can span lines
const CLASS_LIST_BRAND_FILL = /classList\.(?:add|toggle|replace)\(([^)]*)\)/g;
const CLASS_LIST_ANY = /classList\.(?:add|remove|toggle|replace)\(([^)]*)\)/g;
const DARK_THEME = /\[data-theme=["']?dark["']?\]|prefers-color-scheme:\s*dark/;
const HEADER_CLASS = /\bheaderClass\s*=/;
const SLOT_LINE = /slot="(?:header-extra|actions)"/;
// A dark hero keeps its white text: the parent hub (`bg-brand-ink`, solid or ≥80% alpha,
// unprefixed) and the arbitrary hexes below, which are the ONLY dark ones used in src
// (teen kid hero #1E2230). Any other `bg-[#…]` — e.g. cream #FFF8F0 — is light (F-3d).
const DARK_HEXES = ["1E2230"];
const DARK_HERO = new RegExp(
    `(?<![\\w:/-])bg-(?:brand-ink(?:/(?:[89]\\d|100))?|\\[#(?:${DARK_HEXES.join("|")})\\])(?![\\w/-])`,
    "i",
);
const HEADER_BLOCK = /<header\b([^>]*)>([\s\S]*?)<\/header>/g;
// Any other element carrying slot="header" (ChatShell's <Fragment slot="header">, a
// custom hero <div slot="header">) is scanned like a <header> block (F-3a).
const SLOT_HEADER_OPEN = /<([A-Za-z][\w.:-]*)\b([^>]*?(?<![\w-])slot=["']header["'][^>]*?)(\/?)>/g;
const H1_BLOCK = /<h1\b[^>]*>([\s\S]*?)<\/h1>/g;
// PageLayout/PageHeader render their `title` prop as the page <h1>.
const TITLE_ATTR = /<(?:PageLayout|PageHeader)\b[^>]*?\btitle=(\{`[^`]*`\}|\{[^}]*\}|"[^"]*")/g;
// CSS declaration blocks (.css files, <style> blocks): brand background + white text.
const CSS_BLOCK = /\{([^{}]*)\}/g;
const CSS_BRAND_BG = /background(?:-color)?\s*:\s*var\(\s*--color-brand-(?:sky|mint|coral|sun)(?:-deep)?(?![\w-])/;
const CSS_WHITE_TEXT = /(?:^|[;{\s])color\s*:\s*(?:#fff(?:fff)?|white)(?![\w-])/i;
const EMOJI = /\p{Extended_Pictographic}/u;
const COMMENT_LINE = /^\s*(?:\/\/|\/\*|\*|<!--|\{\/\*)/;

// ── text-shade-on-fill (F-3f) ───────────────────────────────────────────────
// Every -text shade on every SOLID brand fill (plain or -deep) is 1.7–3.9:1, so the pair
// is flagged whatever the hues; alpha tints (bg-brand-sky/20) are fine. Variant-aware
// (textOnFill), so `text-brand-mint-text hover:bg-brand-mint hover:text-brand-ink`
// (fix-round T6-1 pattern) is clean.
const COLOR_TOKEN =
    /(?<![\w-])((?:[a-z0-9-]+:)*)(bg|text)-((?:brand-[a-z]+(?:-[a-z]+)*|white|black|transparent|current|inherit|[a-z]+-\d{2,3}|\[#[0-9a-fA-F]{3,8}\])(?:\/\d+)?)(?![\w-])/g;
const SOLID_BRAND_FILL = /^brand-(?:sky|mint|coral|sun)(?:-deep)?$/;
const ANY_BRAND_FILL = /^brand-(?:sky|mint|coral|sun)(?:-deep)?(?:\/\d+)?$/;
const TEXT_SHADE = /^brand-(?:sky|mint|coral|sun)-text(?:\/\d+)?$/;
const LIGHT_VALUE = /^(?:white|brand-cream(?:-deep)?)(?:\/\d+)?$/;

// ── hidden-display-conflict (F-1) ───────────────────────────────────────────
// Unprefixed display utilities that Tailwind v4 emits AFTER `.hidden{display:none}`, so
// they beat the `hidden` CLASS on the same element (the `hidden` ATTRIBUTE still wins:
// preflight's `[hidden]` rule is !important). Derived 2026-09-30: `npm run build` →
// dist/client/_astro/global.*.css orders the display utilities used in src as
// block, contents, flex, grid, hidden, inline, inline-block, inline-flex, table; the ones
// not used yet were ordered by compiling every display utility with tailwindcss 4.3.3's
// compile() (same-property utilities sort by name): block, contents, flex, flow-root,
// grid | hidden | inline, inline-block, inline-flex, inline-grid, inline-table,
// list-item, table, table-caption, table-cell, table-column, table-column-group,
// table-footer-group, table-header-group, table-row, table-row-group.
// buttonClass(...) carries inline-flex. Variant-prefixed utilities (md:flex,
// sm:inline-flex, md:hidden) never conflict: they sit in later media/variant blocks.
const DISPLAY_AFTER_HIDDEN = [
    "inline",
    "inline-block",
    "inline-flex",
    "inline-grid",
    "inline-table",
    "list-item",
    "table",
    "table-caption",
    "table-cell",
    "table-column",
    "table-column-group",
    "table-footer-group",
    "table-header-group",
    "table-row",
    "table-row-group",
];
const LATE_DISPLAY = new RegExp(`(?<![\\w:/-])!?(?:${DISPLAY_AFTER_HIDDEN.join("|")})!?(?![\\w-])`);
const HIDDEN_CLASS = /(?<![\w:/!-])hidden(?![\w!-])/;
const BUTTON_CLASS_CALL = /\bbuttonClass\(/;
const BUTTON_TAG = /<Button\b([^>]*)>/g;
const CLASS_ATTR_VALUE = /\bclass=(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\})/;

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

const blank = (s: string) => s.replace(/[^\n]/g, " ");

// ── a small JS-ish lexer: same-line quotes, template literals with ${} nesting ──

/** i at a quote → index just past its same-line closing quote, or -1. */
function skipQuote(text: string, i: number): number {
    const q = text[i];
    for (let j = i + 1; j < text.length; j++) {
        const c = text[j];
        if (c === "\\") j++;
        else if (c === q) return j + 1;
        else if (c === "\n") return -1;
    }
    return -1;
}

/** i at an opening backtick → index just past its closing backtick, or -1. */
function skipTemplate(text: string, i: number): number {
    for (let j = i + 1; j < text.length; j++) {
        const c = text[j];
        if (c === "\\") j++;
        else if (c === "`") return j + 1;
        else if (c === "$" && text[j + 1] === "{") {
            const end = skipExpr(text, j + 2);
            if (end < 0) return -1;
            j = end - 1;
        }
    }
    return -1;
}

/** i just after `${` → index just past the matching `}`, or -1. */
function skipExpr(text: string, i: number): number {
    let depth = 0;
    for (let j = i; j < text.length; j++) {
        const c = text[j];
        if (c === "`") {
            const end = skipTemplate(text, j);
            if (end < 0) return -1;
            j = end - 1;
        } else if (c === '"' || c === "'") {
            const end = skipQuote(text, j);
            if (end >= 0) j = end - 1;
        } else if (c === "{") depth++;
        else if (c === "}") {
            if (depth === 0) return j + 1;
            depth--;
        }
    }
    return -1;
}

interface Span {
    start: number;
    end: number;
}

/** Top-level template literals (the opening backtick through the closing one). */
function templateLiterals(text: string): Span[] {
    const out: Span[] = [];
    for (let i = 0; i < text.length; i++) {
        if (text[i] !== "`") continue;
        const end = skipTemplate(text, i);
        if (end < 0) continue; // stray backtick
        out.push({ start: i, end });
        i = end - 1;
    }
    return out;
}

/** A template literal's content → its static text and its `${…}` expressions. */
function splitTemplate(content: string): { statics: string; exprs: string[] } {
    let statics = "";
    const exprs: string[] = [];
    for (let j = 0; j < content.length; j++) {
        const c = content[j];
        if (c === "$" && content[j + 1] === "{") {
            const end = skipExpr(content, j + 2);
            if (end < 0) {
                statics += content.slice(j);
                break;
            }
            exprs.push(content.slice(j + 2, end - 1));
            statics += " ";
            j = end - 1;
        } else statics += c;
    }
    return { statics, exprs };
}

/**
 * The class-ish strings in a JS expression: quoted strings, nested template literals
 * (as their combos), a `buttonClass(` marker, and bare object keys (`{ hidden: x }` in
 * class:list). With `ownLevelOnly`, strings inside a nested `[…]` are left to that array.
 */
function exprStrings(expr: string, ownLevelOnly = false): string[] {
    const out: string[] = [];
    let nested = 0;
    for (let j = 0; j < expr.length; j++) {
        const c = expr[j];
        if (c === '"' || c === "'") {
            const end = skipQuote(expr, j);
            if (end < 0) continue;
            if (!(ownLevelOnly && nested)) out.push(expr.slice(j + 1, end - 1));
            j = end - 1;
        } else if (c === "`") {
            const end = skipTemplate(expr, j);
            if (end < 0) continue;
            if (!(ownLevelOnly && nested)) out.push(...classCombos(expr.slice(j + 1, end - 1)));
            j = end - 1;
        } else if (c === "[") nested++;
        else if (c === "]") nested = Math.max(0, nested - 1);
    }
    if (BUTTON_CLASS_CALL.test(expr)) out.push("buttonClass(");
    for (const m of expr.matchAll(/[{,]\s*([A-Za-z_][\w-]*)\s*:/g)) out.push(m[1]);
    return out;
}

/**
 * The class strings a template literal can produce: its static text, plus each string of
 * a conditional interpolation (ternary / && / || / ??) as ONE alternative — two branches
 * of one interpolation never pair, two different interpolations may both be on.
 */
function classCombos(content: string): string[] {
    const { statics, exprs } = splitTemplate(content);
    let always = statics;
    const alts: string[][] = [];
    for (const e of exprs) {
        const strs = exprStrings(e);
        if (!strs.length) continue;
        if (/\?|&&|\|\|/.test(e)) alts.push(strs);
        else always += ` ${strs.join(" ")}`;
    }
    const combos = [always];
    alts.forEach((a, i) => {
        for (const s of a) {
            combos.push(`${always} ${s}`);
            for (const b of alts.slice(i + 1)) for (const t of b) combos.push(`${always} ${s} ${t}`);
        }
    });
    return combos;
}

/** `class="…"` attribute values inside a template literal (client-rendered markup). */
function classAttrValues(content: string): { offset: number; value: string }[] {
    const out: { offset: number; value: string }[] = [];
    for (const m of content.matchAll(/\bclass=(["'])/g)) {
        const q = m[1];
        const from = (m.index ?? 0) + m[0].length;
        let j = from;
        for (; j < content.length; j++) {
            const c = content[j];
            if (c === "$" && content[j + 1] === "{") {
                const end = skipExpr(content, j + 2);
                if (end < 0) break;
                j = end - 1;
            } else if (c === q) break;
        }
        out.push({ offset: from, value: content.slice(from, j) });
    }
    return out;
}

// ── pairing checks: each returns the offending token, or null ───────────────

/**
 * The text token that sits on a matching fill in some state, or null. States are the base
 * and every variant prefix used (hover:, md:, …); in each, the fills/texts in force are the
 * ones with exactly that prefix, falling back to the unprefixed ones — so
 * `bg-brand-sun-deep text-brand-ink hover:bg-brand-ink hover:text-brand-cream` is clean.
 */
function textOnFill(s: string, isFill: (v: string) => boolean, isText: (v: string) => boolean): string | null {
    const toks = [...s.matchAll(COLOR_TOKEN)].map((m) => ({ prefix: m[1], kind: m[2], value: m[3], raw: m[0] }));
    if (!toks.some((t) => t.kind === "bg" && isFill(t.value))) return null;
    const states = new Set(["", ...toks.map((t) => t.prefix)]);
    for (const p of states) {
        const inForce = (kind: string) => {
            const exact = toks.filter((t) => t.kind === kind && t.prefix === p);
            return exact.length ? exact : toks.filter((t) => t.kind === kind && t.prefix === "");
        };
        if (!inForce("bg").some((t) => isFill(t.value))) continue;
        const bad = inForce("text").find((t) => isText(t.value));
        if (bad) return bad.raw;
    }
    return null;
}

const lightOnFill = (s: string) =>
    textOnFill(
        s,
        (v) => ANY_BRAND_FILL.test(v),
        (v) => LIGHT_VALUE.test(v),
    );
const shadeOnFill = (s: string) =>
    textOnFill(
        s,
        (v) => SOLID_BRAND_FILL.test(v),
        (v) => TEXT_SHADE.test(v),
    );

function hiddenConflict(s: string): string | null {
    if (!HIDDEN_CLASS.test(s)) return null;
    return LATE_DISPLAY.test(s) || BUTTON_CLASS_CALL.test(s) ? "hidden" : null;
}

type PairCheck = { rule: RuleId; check: (s: string) => string | null };
const PRECISE_CHECKS: PairCheck[] = [
    { rule: "text-shade-on-fill", check: shadeOnFill },
    { rule: "hidden-display-conflict", check: hiddenConflict },
];
const ALL_CHECKS: PairCheck[] = [{ rule: "white-on-brand-fill", check: lightOnFill }, ...PRECISE_CHECKS];

/** Every light text token on the line sits in a quoted class string with a dark-hero fill. */
function lightOnOwnDarkFill(line: string): boolean {
    const dark = [...line.matchAll(QUOTED)]
        .filter((q) => DARK_HERO.test(q[0]))
        .map((q) => ({ from: q.index ?? 0, to: (q.index ?? 0) + q[0].length }));
    return [...line.matchAll(LIGHT_ON_FILL_ALL)].every((t) => dark.some((q) => q.from < (t.index ?? 0) && (t.index ?? 0) < q.to));
}

/** Code with template literals and quoted-string contents blanked, for bracket matching. */
function codeMask(text: string, literals: Span[]): string {
    let masked = text;
    for (const l of literals) masked = masked.slice(0, l.start) + blank(masked.slice(l.start, l.end)) + masked.slice(l.end);
    return masked.replace(QUOTED, (m) => m[0] + " ".repeat(m.length - 2) + m[m.length - 1]);
}

/** Array literals with ≥ 2 elements, as element spans. */
function arrayLiterals(mask: string): Span[][] {
    const CLOSE: Record<string, string> = { "[": "]", "(": ")", "{": "}" };
    const out: Span[][] = [];
    for (let i = 0; i < mask.length; i++) {
        if (mask[i] !== "[") continue;
        const stack = ["]"];
        const elems: Span[] = [];
        let elStart = i + 1;
        for (let j = i + 1; j < mask.length && j - i < 4000; j++) {
            const c = mask[j];
            if (c in CLOSE) stack.push(CLOSE[c]);
            else if (c === "]" || c === ")" || c === "}") {
                if (stack.pop() !== c) break;
                if (!stack.length) {
                    elems.push({ start: elStart, end: j });
                    if (elems.length > 1) out.push(elems);
                    break;
                }
            } else if (c === "," && stack.length === 1) {
                elems.push({ start: elStart, end: j });
                elStart = j + 1;
            }
        }
    }
    return out;
}

/** Index of the first non-blank character of a span. */
function trimmedStart(text: string, s: Span): number {
    let i = s.start;
    while (i < s.end && /\s/.test(text[i])) i++;
    return i;
}

/** End index of the element opened at `from` (depth-aware on same-name tags), or -1. */
function findClose(text: string, name: string, from: number): number {
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`<(/?)${esc}(?![\\w.:-])[^>]*?(/?)>`, "g");
    re.lastIndex = from;
    let depth = 1;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
        if (m[1]) {
            if (--depth === 0) return m.index + m[0].length;
        } else if (!m[2]) depth++;
    }
    return -1;
}

export function scanVisual(raw: string): Hit[] {
    const text = stripCommentLines(raw);
    const literals = templateLiterals(text);
    let maskedText = text;
    for (const l of literals) {
        maskedText = maskedText.slice(0, l.start) + blank(maskedText.slice(l.start, l.end)) + maskedText.slice(l.end);
    }
    const maskedLines = maskedText.split("\n");
    const hits: Hit[] = [];

    text.split("\n").forEach((l, i) => {
        const line = i + 1;
        for (const q of maskedLines[i].matchAll(QUOTED)) {
            const s = q[1] ?? q[2] ?? "";
            for (const { rule, check } of ALL_CHECKS) {
                const tok = check(s);
                if (tok) hits.push({ rule, line, match: rule === "white-on-brand-fill" ? q[0] : tok });
            }
        }
        for (const m of l.matchAll(DEEP_TEXT)) hits.push({ rule: "deep-text", line, match: m[0] });
        for (const m of l.matchAll(FAINT_TEXT)) hits.push({ rule: "faint-text", line, match: m[0] });
        if (DARK_THEME.test(l)) hits.push({ rule: "dark-theme", line, match: DARK_THEME.exec(l)![0] });
        if (HEADER_CLASS.test(l)) hits.push({ rule: "header-class-prop", line, match: "headerClass=" });
        if (SLOT_LINE.test(l)) {
            for (const m of l.matchAll(LIGHT_TEXT)) hits.push({ rule: "light-text-in-header", line, match: m[0] });
            for (const m of l.matchAll(INK_SOFT_TEXT)) hits.push({ rule: "light-text-in-header", line, match: m[0] });
        }
    });

    for (const lit of literals) {
        const content = text.slice(lit.start + 1, lit.end - 1);
        const base = lit.start + 1;
        // white-on-brand-fill: the whole literal is ONE class string, even across lines
        // (the branches of one ternary still never pair).
        const light = classCombos(content).map(lightOnFill).find(Boolean);
        if (light) {
            hits.push({
                rule: "white-on-brand-fill",
                line: lineAt(text, base + Math.max(content.indexOf(light), 0)),
                match: `${light} (template literal)`,
            });
        }
        // The precise rules: per class="…" attribute when the literal is markup, else the
        // literal itself; per ternary branch either way.
        const attrs = classAttrValues(content);
        const units = attrs.length ? attrs : [{ offset: 0, value: content }];
        for (const u of units) {
            for (const { rule, check } of PRECISE_CHECKS) {
                const tok = classCombos(u.value).map(check).find(Boolean);
                if (!tok) continue;
                const at = u.value.indexOf(tok);
                hits.push({ rule, line: lineAt(text, base + u.offset + Math.max(at, 0)), match: `${tok} (template literal)` });
            }
        }
    }

    // Array literals / class:list: strings from different elements pair (F-3b).
    for (const elems of arrayLiterals(codeMask(text, literals))) {
        const strs = elems.map((e) => exprStrings(text.slice(e.start, e.end), true));
        for (let a = 0; a < elems.length; a++) {
            for (let b = a + 1; b < elems.length; b++) {
                for (const s of strs[a]) {
                    for (const t of strs[b]) {
                        for (const { rule, check } of ALL_CHECKS) {
                            const tok = check(`${s} ${t}`);
                            if (!tok || check(s) || check(t)) continue;
                            const owner = s.includes(tok) ? elems[a] : elems[b];
                            hits.push({ rule, line: lineAt(text, trimmedStart(text, owner)), match: `${tok} (array)` });
                        }
                    }
                }
            }
        }
    }

    // A file that adds/toggles/replaces a brand fill via classList at runtime makes
    // every light text token in that file suspect (max 1 hit per line) — except light
    // text in a class string holding its own dark-hero fill (an ink toast), as long as
    // the file never swaps that dark fill at runtime.
    const hasRuntimeBrandFill = [...text.matchAll(CLASS_LIST_BRAND_FILL)].some((m) => BRAND_FILL.test(m[1]));
    if (hasRuntimeBrandFill) {
        const darkFillSwapped = [...text.matchAll(CLASS_LIST_ANY)].some((m) => DARK_HERO.test(m[1]));
        text.split("\n").forEach((l, i) => {
            const m = LIGHT_ON_FILL.exec(l);
            if (!m || (!darkFillSwapped && lightOnOwnDarkFill(l))) return;
            hits.push({ rule: "white-on-brand-fill", line: i + 1, match: `${m[0]} (runtime brand fill)` });
        });
    }

    // <Button> renders buttonClass (inline-flex): a `hidden` class on it never hides it.
    for (const m of text.matchAll(BUTTON_TAG)) {
        const cls = CLASS_ATTR_VALUE.exec(m[1]);
        if (cls && HIDDEN_CLASS.test(cls[1] ?? cls[2] ?? cls[3] ?? "")) {
            hits.push({ rule: "hidden-display-conflict", line: lineAt(text, m.index ?? 0), match: "hidden (<Button>)" });
        }
    }

    const lightInBlock = (block: string, start: number) => {
        for (const t of block.matchAll(LIGHT_TEXT)) {
            hits.push({ rule: "light-text-in-header", line: lineAt(text, start + (t.index ?? 0)), match: t[0] });
        }
        for (const t of block.matchAll(INK_SOFT_TEXT)) {
            hits.push({ rule: "light-text-in-header", line: lineAt(text, start + (t.index ?? 0)), match: t[0] });
        }
    };

    for (const m of text.matchAll(HEADER_BLOCK)) {
        const start = m.index ?? 0;
        const attrs = m[1];
        if (/bg-gradient-to-/.test(attrs)) {
            hits.push({ rule: "header-gradient", line: lineAt(text, start), match: "bg-gradient-to-" });
        }
        if (!DARK_HERO.test(attrs)) lightInBlock(m[0], start);
    }

    for (const m of text.matchAll(SLOT_HEADER_OPEN)) {
        if (m[1].toLowerCase() === "header") continue; // a <header> block, scanned above
        const start = m.index ?? 0;
        const openEnd = start + m[0].length;
        const end = m[3] ? openEnd : findClose(text, m[1], openEnd);
        if (DARK_HERO.test(m[2])) continue;
        // Nested <header> blocks carry their own fill and dark-hero test (scanned above).
        const block = text.slice(start, end < 0 ? openEnd : end).replace(HEADER_BLOCK, blank);
        lightInBlock(block, start);
    }

    for (const m of text.matchAll(H1_BLOCK)) {
        if (EMOJI.test(m[1])) hits.push({ rule: "h1-emoji", line: lineAt(text, m.index ?? 0), match: "<h1>" });
    }
    for (const m of text.matchAll(TITLE_ATTR)) {
        if (EMOJI.test(m[1])) {
            hits.push({ rule: "h1-emoji", line: lineAt(text, (m.index ?? 0) + m[0].length - m[1].length), match: "title=" });
        }
    }

    for (const m of text.matchAll(CSS_BLOCK)) {
        const body = m[1];
        if (!CSS_BRAND_BG.test(body)) continue;
        const w = CSS_WHITE_TEXT.exec(body);
        if (w) {
            hits.push({ rule: "white-on-brand-fill", line: lineAt(text, (m.index ?? 0) + 1 + w.index), match: "color: white on brand background (CSS)" });
        }
    }

    const seen = new Set<string>();
    return hits
        .filter((h) => {
            const key = `${h.rule}|${h.line}|${h.match}`;
            return seen.has(key) ? false : (seen.add(key), true);
        })
        .sort((a, b) => a.line - b.line || a.rule.localeCompare(b.rule));
}
