/**
 * Family-timezone-aware date formatting for SSR pages.
 *
 * The Astro SSR container runs in UTC, so a bare
 * `new Date(x).toLocaleString(locale, opts)` renders backend timestamps in
 * UTC — a parent in Mexico City sees "04:52 a.m." for a chore submitted at
 * 10:52 p.m. Every SSR render of a backend *timestamp* must go through these
 * helpers with the family timezone (denormalized on /api/auth/me as
 * `user.timezone`).
 *
 * Bare calendar dates ("2026-07-24" — due dates, week keys) are NOT
 * instants: converting them through a timezone can shift the day. Use
 * fmtCalendarDate for those.
 */

export const localeFor = (lang: string): string =>
    lang === "es" ? "es-MX" : "en-US";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
// Backend timestamps are UTC but some serializers omit the offset; JS parses
// offset-less ISO strings as *server-local* time, so pin them to Z.
const NAIVE_ISO = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseUtcInstant(value: string | Date): Date {
    if (value instanceof Date) return value;
    if (NAIVE_ISO.test(value)) return new Date(value.replace(" ", "T") + "Z");
    return new Date(value);
}

function format(
    value: string | Date | null | undefined,
    lang: string,
    tz: string | null | undefined,
    opts: Intl.DateTimeFormatOptions,
): string {
    if (!value) return "";
    // Calendar dates delegate — a tz conversion would shift the day.
    if (typeof value === "string" && DATE_ONLY.test(value)) {
        const { hour: _h, minute: _m, second: _s, ...dateOpts } = opts;
        return fmtCalendarDate(value, lang, dateOpts);
    }
    const d = parseUtcInstant(value);
    if (isNaN(d.getTime())) return "";
    try {
        return d.toLocaleString(localeFor(lang), { ...opts, timeZone: tz || "UTC" });
    } catch {
        // Unknown tz name stored in the DB — render UTC rather than crash SSR.
        return d.toLocaleString(localeFor(lang), { ...opts, timeZone: "UTC" });
    }
}

/** "24 jul, 10:52 p.m." — list-row / review-card default. Custom `opts`
 *  REPLACE the default set (so `dateStyle`-based options stay valid). */
export const fmtDateTime = (
    value: string | Date | null | undefined,
    lang: string,
    tz: string | null | undefined,
    opts: Intl.DateTimeFormatOptions = {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    },
): string => format(value, lang, tz, opts);

/** Date part of a timestamp, in the family tz. */
export const fmtDate = (
    value: string | Date | null | undefined,
    lang: string,
    tz: string | null | undefined,
    opts: Intl.DateTimeFormatOptions = {
        year: "numeric", month: "numeric", day: "numeric",
    },
): string => format(value, lang, tz, opts);

/** Time part of a timestamp, in the family tz. */
export const fmtTime = (
    value: string | Date | null | undefined,
    lang: string,
    tz: string | null | undefined,
    opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" },
): string => format(value, lang, tz, opts);

/** "YYYY-MM-DD" day key of an instant in the family tz — for bucketing
 *  events/rows under the correct local day (a 8pm Mexico City event is 2am
 *  UTC the NEXT day; UTC-day bucketing files it under the wrong header). */
export function dayKeyInTz(
    value: string | Date,
    tz: string | null | undefined,
): string {
    const d = parseUtcInstant(value);
    if (isNaN(d.getTime())) return "";
    try {
        return d.toLocaleDateString("en-CA", { timeZone: tz || "UTC" });
    } catch {
        return d.toLocaleDateString("en-CA", { timeZone: "UTC" });
    }
}

/** Format a bare calendar date ("2026-07-24") — timezone-neutral: the date
 *  parts render as-is, never shifted through a tz conversion. */
export function fmtCalendarDate(
    value: string,
    lang: string,
    opts: Intl.DateTimeFormatOptions = {
        year: "numeric", month: "numeric", day: "numeric",
    },
): string {
    const m = DATE_ONLY.exec(value);
    if (!m) return "";
    const [y, mo, d] = value.split("-").map(Number);
    return new Date(y, mo - 1, d, 12).toLocaleDateString(localeFor(lang), opts);
}
