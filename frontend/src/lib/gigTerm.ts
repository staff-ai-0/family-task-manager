/**
 * Resolve a family's gig term into the four cased/pluralized forms used in copy.
 * DB/routes stay "gig"; only user-visible strings vary. The family's stored
 * term (e.g. "chamba") is honored in BOTH languages — a family that picked
 * "chamba" sees it in English copy too, not just Spanish. `_lang` is unused
 * today; it's reserved for future per-language pluralization rules.
 */
export function gigTerm(term: string, _lang: string): { one: string; many: string; One: string; Many: string } {
    const t = term === "chamba" ? "chamba" : "gig";
    const one = t;
    const many = t === "chamba" ? "chambas" : "gigs";
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
    return { one, many, One: cap(one), Many: cap(many) };
}
