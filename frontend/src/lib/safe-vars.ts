/**
 * Pass server data to a client script without going through `define:vars`.
 *
 * Astro's `define:vars` serializer only escapes the exact lowercase `</script>`
 * sequence. The HTML tokenizer, however, ends a script element at `</script`
 * followed by whitespace, `/` or `>`, and tag names are case-insensitive — so
 * `</SCRIPT >`, `</script\t>` and `</script >` all terminate the block while
 * passing through unescaped. Verified against astro 5.17.3 in a browser: one
 * source block containing an attacker-controlled `</SCRIPT >` was parsed as TWO
 * script elements, split exactly at the injected tag. (Advisory
 * GHSA-j687-52p2-xcff; fixed only in astro 7.1.4, i.e. two majors away.)
 *
 * That matters here because user-authored strings reach these blocks — display
 * names, routine names, budget account and category names — and none of them
 * restrict characters (`name` is validated as length-only). A family member
 * could set their name to a crafted payload and execute script in every other
 * member's browser, including a parent's.
 *
 * HTML *attribute* escaping is not affected by that bug: Astro escapes `<` to
 * `&lt;` in attribute values, and the tokenizer never looks for a closing tag
 * inside one. So the fix is to ship the data as an attribute and read it back.
 *
 * Server side:
 *   <div id="chat-data" data-json={serializeForClient(payload)} hidden></div>
 * Client side:
 *   const { memberMap } = readClientData("chat-data");
 */

/** JSON for embedding in an HTML attribute. Astro escapes the attribute itself. */
export function serializeForClient(value: unknown): string {
    return JSON.stringify(value);
}

/**
 * Read back what `serializeForClient` wrote.
 *
 * Returns an empty object when the element is missing or holds invalid JSON, so
 * a malformed payload degrades to "no data" rather than throwing and killing
 * the rest of the island's script.
 */
export function readClientData<T = Record<string, unknown>>(elementId: string): T {
    const el = document.getElementById(elementId);
    const raw = el?.getAttribute("data-json");
    if (!raw) return {} as T;
    try {
        return JSON.parse(raw) as T;
    } catch {
        console.error(`[client-data] invalid JSON in #${elementId}`);
        return {} as T;
    }
}
