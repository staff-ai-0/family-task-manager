import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { scanSource } from "./support/native-dialog-scan";

const SRC = fileURLToPath(new URL("../src", import.meta.url));

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return walk(path);
        return /\.(astro|ts)$/.test(name) ? [path] : [];
    });
}

describe("scanSource", () => {
    it("flags every native form", () => {
        const src = [
            'alert("x");',
            'if (!confirm("y")) return;',
            'const v = prompt("z");',
            "window.alert(1); window.confirm(2); window.prompt(3);",
            `<form onsubmit="return confirm('Delete?')">`,
        ].join("\n");
        expect(scanSource(src).map((h) => h.line)).toEqual([1, 2, 3, 4, 4, 4, 5]);
    });
    it("ignores lookalikes", () => {
        const src = [
            "google.accounts.id.prompt();",
            "await confirmSheet({ title });",
            "await promptSheet({ title });",
            "obj.confirm();",
            "onConfirm();",
            "window.ftmDialogs?.confirmSheet({ title });",
        ].join("\n");
        expect(scanSource(src)).toEqual([]);
    });
    it("ignores comments but not code after them", () => {
        const src = [
            "// never alert() here",
            "/* confirm( */ prompt('after');",
            "/*",
            " * alert(",
            " */",
            'const url = "https://x.test/alert"; alert(url);',
        ].join("\n");
        expect(scanSource(src)).toEqual([
            { line: 2, match: "prompt(" },
            { line: 6, match: "alert(" },
        ]);
    });
});

describe("frontend/src", () => {
    it("has no native alert / confirm / prompt", () => {
        const hits = walk(SRC).flatMap((file) =>
            scanSource(readFileSync(file, "utf8")).map((h) => `${relative(SRC, file)}:${h.line} ${h.match}`),
        );
        expect(hits).toEqual([]);
    });
});
