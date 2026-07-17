/**
 * Resolve a family's gig term into the four cased/pluralized forms used in copy.
 * DB/routes stay "gig"; only user-visible strings vary. English keeps gig/gigs
 * even when the family picked "chamba" is a Spanish label — callers pass the
 * family's stored term and the active lang, and we honor the term in both.
 */
export function gigTerm(term: string, _lang: string): { one: string; many: string; One: string; Many: string } {
    const t = term === "chamba" ? "chamba" : "gig";
    const one = t;
    const many = t === "chamba" ? "chambas" : "gigs";
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
    return { one, many, One: cap(one), Many: cap(many) };
}
