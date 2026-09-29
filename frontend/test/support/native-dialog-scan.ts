/**
 * Finds native alert/confirm/prompt calls in source text (UX-B1 guard).
 * A call preceded by a letter, digit, `_`, `$` or `.` is not native
 * (confirmSheet, obj.confirm, google.accounts.id.prompt) — except the
 * explicit window.alert/confirm/prompt forms (also globalThis./self., and
 * the optional-chained window?./globalThis?./self?. spellings — all four
 * are just as native as the bare call and would otherwise slip through the
 * lookbehind above because of the dot/`?.` right before the function name).
 *
 * Line comments, block comments and HTML comments are stripped — but only
 * when they start outside a string literal, so a block-comment opener
 * sitting inside a string, a double-slash path inside a template string,
 * or a same-line HTML comment don't swallow real code that follows them
 * on the same or a later line. Quote state (single/double/backtick, with
 * backslash escapes) is tracked left-to-right and resets at end of line —
 * an unclosed quote never carries into the next line. Block and HTML
 * comments DO carry across lines, since real multi-line comments do.
 */
const BARE = /(?<![A-Za-z0-9_.$])(?:alert|confirm|prompt)\s*\(/g;
const WINDOW = /\b(?:window|globalThis|self)(?:\?\.|\.)(?:alert|confirm|prompt)\s*\(/g;

export function scanSource(text: string): { line: number; match: string }[] {
    const hits: { line: number; match: string }[] = [];
    let inBlockComment = false;
    let inHtmlComment = false;
    text.split("\n").forEach((rawLine, i) => {
        let out = "";
        let quote: string | null = null;
        let idx = 0;
        while (idx < rawLine.length) {
            if (inBlockComment) {
                const end = rawLine.indexOf("*/", idx);
                if (end === -1) break;
                idx = end + 2;
                inBlockComment = false;
                continue;
            }
            if (inHtmlComment) {
                const end = rawLine.indexOf("-->", idx);
                if (end === -1) break;
                idx = end + 3;
                inHtmlComment = false;
                continue;
            }
            const ch = rawLine[idx];
            if (quote) {
                out += ch;
                if (ch === "\\" && idx + 1 < rawLine.length) {
                    out += rawLine[idx + 1];
                    idx += 2;
                    continue;
                }
                if (ch === quote) quote = null;
                idx++;
                continue;
            }
            if (rawLine.startsWith("/*", idx)) {
                inBlockComment = true;
                idx += 2;
                continue;
            }
            if (rawLine.startsWith("//", idx)) break;
            if (rawLine.startsWith("<!--", idx)) {
                inHtmlComment = true;
                idx += 4;
                continue;
            }
            if (ch === '"' || ch === "'" || ch === "`") quote = ch;
            out += ch;
            idx++;
        }
        const found: { index: number; match: string }[] = [];
        for (const m of out.matchAll(WINDOW)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        for (const m of out.matchAll(BARE)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        found.sort((a, b) => a.index - b.index).forEach((f) => hits.push({ line: i + 1, match: f.match }));
    });
    return hits;
}
