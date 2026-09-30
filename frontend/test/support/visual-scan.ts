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
