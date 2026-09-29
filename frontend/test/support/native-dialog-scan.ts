/**
 * Finds native alert/confirm/prompt calls in source text (UX-B1 guard).
 * A call preceded by a letter, digit, `_`, `$` or `.` is not native
 * (confirmSheet, obj.confirm, google.accounts.id.prompt) — except the
 * explicit window.alert/confirm/prompt forms. Comments are skipped.
 */
const BARE = /(?<![A-Za-z0-9_.$])(?:alert|confirm|prompt)\s*\(/g;
const WINDOW = /\bwindow\.(?:alert|confirm|prompt)\s*\(/g;

export function scanSource(text: string): { line: number; match: string }[] {
    const hits: { line: number; match: string }[] = [];
    let inBlock = false;
    text.split("\n").forEach((raw, i) => {
        let line = raw;
        if (inBlock) {
            const end = line.indexOf("*/");
            if (end === -1) return;
            line = line.slice(end + 2);
            inBlock = false;
        }
        line = line.replace(/\/\*.*?\*\//g, " ");
        const open = line.indexOf("/*");
        if (open !== -1) {
            line = line.slice(0, open);
            inBlock = true;
        }
        line = line.replace(/(^|[^:])\/\/.*$/, "$1");
        const found: { index: number; match: string }[] = [];
        for (const m of line.matchAll(WINDOW)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        for (const m of line.matchAll(BARE)) found.push({ index: m.index ?? 0, match: m[0].replace(/\s+/g, "") });
        found.sort((a, b) => a.index - b.index).forEach((f) => hits.push({ line: i + 1, match: f.match }));
    });
    return hits;
}
