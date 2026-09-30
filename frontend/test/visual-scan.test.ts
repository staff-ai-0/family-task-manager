import { describe, expect, it } from "vitest";

import { DEEP_TEXT_CODEMOD, RULE_IDS, scanVisual, type RuleId } from "./support/visual-scan";

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

describe("scanVisual — white-on-brand-fill: split class strings (F-3b/c/e)", () => {
    it("pairs quoted tokens across the elements of one array literal", () => {
        const src = 'const activeTabClasses = ["bg-brand-sky-deep", "text-white", "border-brand-sky-deep"];';
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("pairs across the elements of a multi-line class:list", () => {
        const src = ["<b class:list={[", '    "px-3 bg-brand-mint",', '    on && "text-white",', "]}>x</b>"].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([3]);
    });
    it("pairs a quoted object key in class:list", () => {
        const src = '<b class:list={["px-3 bg-brand-coral", { "text-white": on }]}>x</b>';
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("does not pair the two branches of one ternary element, or two separate arrays", () => {
        const src = [
            '<b class:list={["px-3", on ? "bg-brand-sky text-brand-ink" : "bg-white text-white"]}>x</b>',
            '<b class:list={[on ? "bg-brand-sky" : "text-white"]}>y</b>',
            'const a = ["bg-brand-sky"]; const b = ["text-white"];',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill")).toEqual([]);
    });
    it("pairs a template literal nested inside another one", () => {
        const src = 'el.className = `px-3 ${on ? `bg-brand-sky text-white` : ""}`;';
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("does not end a template literal at a quoted brace inside ${}", () => {
        const src = 'el.className = `a ${x ? "}" : ""} bg-brand-sky text-white`;';
        expect(rules(src, "white-on-brand-fill")).toHaveLength(1);
    });
    it("treats text-brand-cream[/NN] like text-white", () => {
        const src = [
            '<span class="bg-brand-sky text-brand-cream">a</span>',
            '<span class="bg-brand-coral/20 hover:text-brand-cream/80">b</span>',
            '<span class="bg-brand-ink text-brand-cream">ok</span>',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1, 2]);
    });
    it("counts text-brand-cream in a file that toggles a brand fill via classList", () => {
        const src = ['<p class="text-brand-cream">x</p>', 'el.classList.add("bg-brand-mint");'].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1]);
    });
    // False positives surfaced by the live tree once cream counted as light (fix wave):
    it("does not pair the branches of one ternary inside a template literal (calendar/month)", () => {
        const src = [
            "<a class={`px-2 border ${",
            "    sel",
            '        ? "bg-brand-ink text-brand-cream border-brand-ink"',
            '        : "bg-brand-sun/30 border-brand-sun-deep text-brand-ink"',
            "}`}>d</a>",
        ].join("\n");
        expect(rules(src, "white-on-brand-fill")).toEqual([]);
    });
    it("is variant-aware: a hover that swaps to an ink fill with cream text is fine (parent/tasks)", () => {
        const src = [
            '<button class="bg-brand-sun-deep text-brand-ink hover:bg-brand-ink hover:text-brand-cream">ok</button>',
            '<button class="bg-brand-sun-deep text-brand-ink hover:text-brand-cream">bad</button>',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([2]);
    });
    it("runtime taint skips light text on its own ink fill (pet/quests toast)", () => {
        const src = ['<div class="bg-brand-ink text-brand-cream">toast</div>', 'btn.classList.add("bg-brand-mint-deep");'].join(
            "\n",
        );
        expect(rules(src, "white-on-brand-fill")).toEqual([]);
    });
    it("…unless the file swaps that ink fill at runtime", () => {
        const src = [
            '<div class="bg-brand-ink text-white">x</div>',
            'el.classList.replace("bg-brand-ink", "bg-brand-sky");',
        ].join("\n");
        expect(rules(src, "white-on-brand-fill").map((h) => h.line)).toEqual([1]);
    });
});

describe("scanVisual — text-shade-on-fill (F-3f)", () => {
    const shade = (src: string) => rules(src, "text-shade-on-fill");
    it("is a registered rule", () => {
        expect(RULE_IDS).toContain("text-shade-on-fill");
    });
    it("flags a -text shade on a solid brand fill (own hue, -deep, or another hue)", () => {
        const src = [
            '<b class="bg-brand-sky text-brand-sky-text">a</b>',
            '<b class="bg-brand-sun-deep text-brand-sun-text">b</b>',
            '<b class="bg-brand-mint text-brand-coral-text">c</b>',
        ].join("\n");
        expect(shade(src).map((h) => h.line)).toEqual([1, 2, 3]);
    });
    it("allows a -text shade on an alpha tint of a brand fill", () => {
        expect(shade('<b class="bg-brand-sky/20 text-brand-sky-text">a</b>')).toEqual([]);
    });
    it("flags a hover fill that keeps the shade, not one that also switches to ink", () => {
        const src = [
            '<a class="text-brand-mint-text hover:bg-brand-mint">bad</a>',
            '<a class="text-brand-mint-text hover:bg-brand-mint hover:text-brand-ink">ok</a>',
        ].join("\n");
        expect(shade(src).map((h) => h.line)).toEqual([1]);
    });
    it("pairs across array elements and inside template literals", () => {
        const src = [
            'const on = ["bg-brand-sky", "text-brand-sky-text"];',
            'el.className = `px-3 bg-brand-coral ${x ? "text-brand-coral-text" : "text-brand-ink"}`;',
        ].join("\n");
        expect(shade(src).map((h) => h.line)).toEqual([1, 2]);
    });
    it("does not pair the two branches of one ternary inside a template literal", () => {
        const src = 'el.className = `px-3 ${on ? "bg-brand-sky text-brand-ink" : "bg-white text-brand-sky-text"}`;';
        expect(shade(src)).toEqual([]);
    });
});

describe("scanVisual — hidden-display-conflict (F-1)", () => {
    const conflict = (src: string) => rules(src, "hidden-display-conflict");
    it("is a registered rule", () => {
        expect(RULE_IDS).toContain("hidden-display-conflict");
    });
    it("flags `hidden` with a display utility Tailwind emits after .hidden", () => {
        const late = ["inline", "inline-block", "inline-flex", "inline-grid", "inline-table", "list-item", "table", "table-cell"];
        for (const d of late) expect(conflict(`<b class="hidden ${d} px-3">x</b>`), d).toHaveLength(1);
    });
    it("flags `hidden` next to buttonClass(...) in a class template literal", () => {
        const src = '<a class={`${buttonClass("primary", "md")} hidden block w-full`}>x</a>';
        expect(conflict(src)).toHaveLength(1);
    });
    it("flags hidden + buttonClass split across class:list elements", () => {
        const src = [
            '<a class:list={[buttonClass("mint"), aiLocked && "hidden"]}>x</a>',
            '<b class:list={["inline-flex px-3", { hidden: !open }]}>y</b>',
        ].join("\n");
        expect(conflict(src).map((h) => h.line)).toEqual([1, 2]);
    });
    it("flags a conditional hidden on an inline-flex element in client-rendered markup", () => {
        const src = 'el.innerHTML = `<b class="inline-flex ${on ? "" : "hidden"}">x</b>`;';
        expect(conflict(src)).toHaveLength(1);
    });
    it("flags a hidden class on the Button component (it renders buttonClass)", () => {
        expect(conflict('<Button variant="mint" class="hidden w-full">Go</Button>')).toHaveLength(1);
    });
    it("does not flag display utilities emitted BEFORE .hidden (hidden wins)", () => {
        for (const d of ["block", "contents", "flex", "flow-root", "grid"]) {
            expect(conflict(`<b class="hidden ${d}">x</b>`), d).toEqual([]);
        }
    });
    it("does not flag responsive / variant-prefixed display or hidden utilities", () => {
        const src = [
            '<b class="hidden md:flex">a</b>',
            '<b class="hidden sm:inline-flex">b</b>',
            '<b class="inline-flex md:hidden">c</b>',
            '<b class="inline-flex group-hover:hidden">d</b>',
        ].join("\n");
        expect(conflict(src)).toEqual([]);
    });
    it("does not flag look-alike tokens or the hidden attribute", () => {
        const src = [
            '<b class="overflow-hidden inline-flex table-auto">a</b>',
            '<b aria-hidden="true" class="inline-flex">b</b>',
            '<input type="hidden" class="inline-block" />',
            'el.innerHTML = `<button hidden class="${buttonClass("primary")}">x</button>`;',
            'el.innerHTML = `<i class="hidden"></i><b class="inline-flex">sibling</b>`;',
        ].join("\n");
        expect(conflict(src)).toEqual([]);
    });
    it("does not pair the two branches of one ternary", () => {
        const src = [
            '<b class={on ? "hidden" : "inline-flex"}>a</b>',
            '<b class:list={[on ? "hidden" : "inline-flex"]}>b</b>',
        ].join("\n");
        expect(conflict(src)).toEqual([]);
    });
});

describe("scanVisual — header slot blocks and dark heroes (F-3a/d)", () => {
    const light = (src: string) => rules(src, "light-text-in-header");
    it('scans a <Fragment slot="header"> like a <header> block', () => {
        const src = [
            '<ChatShell tone="cream">',
            '    <Fragment slot="header">',
            '        <h1 class="text-2xl">t</h1>',
            '        <p class="text-white/80 text-xs">sub</p>',
            "    </Fragment>",
            '    <p class="text-white">body, not header</p>',
            "</ChatShell>",
        ].join("\n");
        expect(light(src).map((h) => [h.line, h.match])).toEqual([[4, "text-white/80"]]);
    });
    it('scans any element carrying slot="header", nested same-name tags included', () => {
        const src = [
            '<div slot="header" class="flex">',
            '    <div class="x"><span class="text-brand-ink-soft">a</span></div>',
            '    <span class="text-sky-100">b</span>',
            "</div>",
        ].join("\n");
        expect(light(src).map((h) => h.line)).toEqual([2, 3]);
    });
    it("keeps the dark-hero exception for a slot block", () => {
        expect(light('<div slot="header" class="bg-brand-ink"><p class="text-white">x</p></div>')).toEqual([]);
    });
    it('does not double-count a <header slot="header">', () => {
        const src = '<header slot="header" class={headerToneClass("sky")}><p class="text-white">x</p></header>';
        expect(light(src)).toHaveLength(1);
    });
    it("treats only bg-brand-ink and known dark hexes as dark heroes", () => {
        const src = [
            '<header class="bg-[#FFF8F0]"><p class="text-white">cream hex</p></header>',
            '<header class="bg-brand-ink/10"><p class="text-white">ink tint</p></header>',
            '<header class="hover:bg-brand-ink"><p class="text-white">hover only</p></header>',
            '<header class="bg-[#1E2230]"><p class="text-white">teen</p></header>',
            '<header class="bg-brand-ink/90"><p class="text-white">ink 90</p></header>',
        ].join("\n");
        expect(light(src).map((h) => h.line)).toEqual([1, 2, 3]);
    });
    it("flags text-brand-cream inside a light header", () => {
        const src = '<header class={headerToneClass("sky")}><p class="text-brand-cream">x</p></header>';
        expect(light(src)).toHaveLength(1);
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
