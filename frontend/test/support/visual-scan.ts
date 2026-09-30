/**
 * Visual-consistency scanner (UX-B3). Pure: one file's text in, rule hits out.
 * The tree walk, exemptions and allowances live in visual-consistency.test.ts.
 *
 * Class tokens are matched with their variant prefixes (hover:, md:, group-hover:)
 * and optional /NN alpha. Pairing rules (white text + brand fill) only pair
 * tokens inside ONE quoted string on one line, so a ternary's two branches are
 * never mixed up. Two exceptions, both fix-round T2-1 (2026-09-29): a backtick
 * template literal is paired as ONE class string even across lines (its own
 * whole-text pass, masked out of the per-line quote scan so it isn't double
 * counted); and a file that adds/toggles/replaces a brand fill class via
 * `classList` at runtime makes every `text-white` token in that file suspect,
 * since the pairing never sits in one string together.
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
const WHITE_TEXT = new RegExp(`${START}${V}text-white(?:/\\d+)?(?![\\w-])`);
const DEEP_TEXT = new RegExp(`${START}${V}text-brand-(?:sky|mint|coral|sun)-deep(?![\\w-])`, "g");
const FAINT_TEXT = new RegExp(`${START}${V}text-(?:slate|gray)-(?:400|500)(?![\\w-])`, "g");
const LIGHT_TEXT = new RegExp(`${START}${V}text-(?:white(?:/\\d+)?|[a-z]+-(?:50|100|200|300))(?![\\w-])`, "g");
// text-brand-ink-soft is legal body copy but fails AA on the sky/coral tone fills (T4-2
// controller ruling); flagged ONLY alongside LIGHT_TEXT in the two header contexts below
// (never in white-on-brand-fill, faint-text or anywhere else — ink-soft stays legal in bodies).
const INK_SOFT_TEXT = new RegExp(`${START}${V}text-brand-ink-soft(?:/\\d+)?(?![\\w-])`, "g");
const QUOTED = /"([^"\n]*)"|'([^'\n]*)'/g; // backtick literals are handled separately — they can span lines
const BACKTICK_LITERAL = /`([^`]*)`/g;
const CLASS_LIST_BRAND_FILL = /classList\.(?:add|toggle|replace)\(([^)]*)\)/g;
const DARK_THEME = /\[data-theme=["']?dark["']?\]|prefers-color-scheme:\s*dark/;
const HEADER_CLASS = /\bheaderClass\s*=/;
const SLOT_LINE = /slot="(?:header-extra|actions)"/;
const DARK_HERO = /\bbg-brand-ink(?![\w-])|\bbg-\[#/;
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

/**
 * Blank out backtick-literal spans (newlines kept, so line numbers stay
 * stable) so the per-line double/single-quote scan below never re-pairs
 * quotes that live inside a template literal — that literal gets its own
 * whole-text, multi-line-aware pass instead (see the BACKTICK_LITERAL loop).
 */
function maskBackticks(text: string): string {
    return text.replace(BACKTICK_LITERAL, (m) => m.replace(/[^\n]/g, " "));
}

export function scanVisual(raw: string): Hit[] {
    const text = stripCommentLines(raw);
    const maskedLines = maskBackticks(text).split("\n");
    const hits: Hit[] = [];

    text.split("\n").forEach((l, i) => {
        const line = i + 1;
        for (const q of maskedLines[i].matchAll(QUOTED)) {
            const s = q[1] ?? q[2] ?? "";
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
            for (const m of l.matchAll(INK_SOFT_TEXT)) hits.push({ rule: "light-text-in-header", line, match: m[0] });
        }
    });

    // A backtick template literal counts as ONE class string even across lines.
    for (const m of text.matchAll(BACKTICK_LITERAL)) {
        const content = m[1];
        if (WHITE_TEXT.test(content) && BRAND_FILL.test(content)) {
            const offset = content.search(WHITE_TEXT);
            const idx = (m.index ?? 0) + 1 + Math.max(offset, 0);
            hits.push({
                rule: "white-on-brand-fill",
                line: lineAt(text, idx),
                match: "text-white (template literal)",
            });
        }
    }

    // A file that adds/toggles/replaces a brand fill via classList at runtime
    // makes every text-white token in that file suspect (max 1 hit per line).
    const hasRuntimeBrandFill = [...text.matchAll(CLASS_LIST_BRAND_FILL)].some((m) => BRAND_FILL.test(m[1]));
    if (hasRuntimeBrandFill) {
        text.split("\n").forEach((l, i) => {
            if (WHITE_TEXT.test(l)) {
                hits.push({
                    rule: "white-on-brand-fill",
                    line: i + 1,
                    match: "text-white (runtime brand fill)",
                });
            }
        });
    }

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
            for (const t of block.matchAll(INK_SOFT_TEXT)) {
                hits.push({ rule: "light-text-in-header", line: lineAt(text, start + (t.index ?? 0)), match: t[0] });
            }
        }
    }

    for (const m of text.matchAll(H1_BLOCK)) {
        if (EMOJI.test(m[1])) hits.push({ rule: "h1-emoji", line: lineAt(text, m.index ?? 0), match: "<h1>" });
    }

    return hits.sort((a, b) => a.line - b.line || a.rule.localeCompare(b.rule));
}
