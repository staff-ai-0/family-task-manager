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

/** Composite `fg` at `alpha` (0–1) over opaque `bg`; #RRGGBB in, uppercase #RRGGBB out. */
export function mix(fg: string, bg: string, alpha: number): string {
    const rgb = (h: string) => {
        const n = parseInt(h.replace("#", ""), 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const [f, b] = [rgb(fg), rgb(bg)];
    return "#" + f.map((c, i) => Math.round(c * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, "0")).join("").toUpperCase();
}

/**
 * --color-brand-* overrides per `body[data-ui-mode="<mode>"] { … }` block of a stylesheet,
 * plus an empty `default` mode. Fails loudly instead of skipping: every override must be a
 * #RRGGBB hex (the contrast maths can't read oklch/var/short hex), and every
 * --color-brand-* declaration outside `@theme` must sit in one of the parsed blocks.
 */
export function parseModeOverrides(css: string): Record<string, Record<string, string>> {
    const modes: Record<string, Record<string, string>> = { default: {} };
    let parsed = 0;
    for (const m of css.matchAll(/body\[data-ui-mode="([a-z]+)"\]\s*\{([^}]*)\}/g)) {
        const vars = (modes[m[1]] ??= {});
        for (const d of m[2].matchAll(/--color-brand-([a-z-]+)\s*:\s*([^;]+);/g)) {
            const value = d[2].trim();
            if (!/^#[0-9A-Fa-f]{6}$/.test(value)) {
                throw new Error(`mode "${m[1]}": --color-brand-${d[1]} must be a #RRGGBB hex, got "${value}"`);
            }
            vars[d[1]] = value;
            parsed++;
        }
    }
    const outsideTheme = css.replace(/@theme\s*\{[\s\S]*?\n\}/, "");
    const declared = [...outsideTheme.matchAll(/--color-brand-[a-z-]+\s*:/g)].length;
    if (declared !== parsed) {
        throw new Error(`${declared - parsed} --color-brand-* declaration(s) outside @theme are not in a parsed body[data-ui-mode="…"] block`);
    }
    return modes;
}
