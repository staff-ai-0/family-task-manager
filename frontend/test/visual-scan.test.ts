import { describe, expect, it } from "vitest";

import { DEEP_TEXT_CODEMOD, scanVisual, type RuleId } from "./support/visual-scan";

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
    it("treats bg-brand-ink-soft as a light fill, not a dark hero", () => {
        const src = '<header class="bg-brand-ink-soft"><p class="text-white">x</p></header>';
        expect(rules(src, "light-text-in-header")).toHaveLength(1);
    });
    it("flags light text on a header-extra / actions slot element", () => {
        const src = [
            '<p slot="header-extra" class="text-amber-100 text-sm">sub</p>',
            '<div slot="actions" class="flex gap-2 text-brand-ink">ok</div>',
        ].join("\n");
        expect(rules(src, "light-text-in-header").map((h) => h.line)).toEqual([1]);
    });
    it("flags text-brand-ink-soft on a header-extra slot line (T4-2: below AA on sky/coral)", () => {
        const src = '<p slot="header-extra" class="text-brand-ink-soft text-sm">sub</p>';
        expect(rules(src, "light-text-in-header")).toHaveLength(1);
    });
    it("flags text-brand-ink-soft (with variant + alpha) inside a light <header> block", () => {
        const src = [
            '<header class={headerToneClass("sky")}>',
            '  <p class="text-brand-ink-soft/80">sub</p>',
            "</header>",
        ].join("\n");
        expect(rules(src, "light-text-in-header")).toHaveLength(1);
    });
    it("allows text-brand-ink-soft in a dark hero header (dark-hero exception)", () => {
        const src = '<header class="bg-brand-ink text-white"><p class="text-brand-ink-soft">x</p></header>';
        expect(rules(src, "light-text-in-header")).toEqual([]);
    });
    it("leaves text-brand-ink-soft legal in a page body outside any header/slot", () => {
        const src = '<p class="text-brand-ink-soft">just body copy</p>';
        expect(rules(src, "light-text-in-header")).toEqual([]);
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
    it("pairs a multi-line template literal as ONE class string", () => {
        const src = ["`inline-flex text-white ${", '    ok ? "bg-brand-mint-deep" : "bg-red-600"', "} px-3`"].join(
            "\n",
        );
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1]);
    });
    it("does not double-count a single-line backtick literal", () => {
        const src = "el.className = `inline-flex text-white bg-brand-mint-deep px-3`;";
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("flags every text-white when the file toggles a brand fill via classList", () => {
        const src = ['btn.classList.toggle("bg-brand-sky-deep", on);', 'btn.classList.toggle("text-white", on);'].join(
            "\n",
        );
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([2]);
    });
    it("flags a static text-white class when a brand fill is toggled elsewhere in the file", () => {
        const src = ['<button class="px-4 text-white">Go</button>', 'ok.classList.toggle("bg-brand-sky-deep", x);'].join(
            "\n",
        );
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1]);
    });
    it("does not flag classList coupling to a non-brand fill", () => {
        const src = ['el.classList.toggle("bg-red-600", x);', '<span class="text-white">y</span>'].join("\n");
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
