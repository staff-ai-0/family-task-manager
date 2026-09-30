/**
 * Button classes (UX-B3) — the ONE source for the kit "sticker" button:
 * bright brand fill, ink text, ink outline, hard shadow, -deep hover.
 * Button.astro renders through this; page scripts that build button HTML
 * import it too. is:inline / define:vars scripts cannot import — they copy
 * the literal string and the visual-consistency guard keeps them honest.
 */
export type ButtonVariant = "primary" | "secondary" | "mint" | "sun" | "ghost";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

const BASE =
    "press inline-flex items-center justify-center gap-2 font-display font-extrabold " +
    "border-2 border-brand-ink rounded-full shadow-[var(--shadow-card)] " +
    "tracking-tight whitespace-nowrap select-none cursor-pointer";

const SIZES: Record<ButtonSize, string> = {
    sm: "px-4 py-2 text-sm",
    md: "px-5 py-3 text-base",
    lg: "px-7 py-4 text-lg",
    icon: "h-10 w-10 p-0 text-xl",
};

const VARIANTS: Record<ButtonVariant, string> = {
    primary: "bg-brand-coral text-brand-ink hover:bg-brand-coral-deep",
    secondary: "bg-brand-sky text-brand-ink hover:bg-brand-sky-deep",
    mint: "bg-brand-mint text-brand-ink hover:bg-brand-mint-deep",
    sun: "bg-brand-sun text-brand-ink hover:bg-brand-sun-deep",
    ghost: "bg-transparent text-brand-ink hover:bg-brand-cream-deep",
};

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
    return `${BASE} ${SIZES[size] ?? SIZES.md} ${VARIANTS[variant] ?? VARIANTS.primary}`;
}
