/**
 * Mark the per-module tours done for the accounts the suite logs in as.
 *
 * A module tour auto-runs on a user's first visit to its page (/budget,
 * /parent/tasks, /parent/gigs, /gigs, /rewards) and covers that page with a
 * driver.js overlay, so the next click in any spec that lands there times out.
 *
 * The nasty part is that it fails ORDER-DEPENDENTLY: whichever spec reaches a
 * page first runs the tour and acks it, so which test breaks depends on the
 * order the suite happened to run in and on whether the database is fresh.
 * Doing it here, once, puts every account in the state a returning user is in
 * before any spec starts — regardless of whether that spec logs in through
 * helpers/auth.js or inline, which most of them do.
 *
 * First-visit behaviour is not skipped, only moved: module-tours.spec.js
 * registers a brand-new family precisely so it can assert what a first visit
 * actually does.
 */
const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

const TOUR_IDS = [
    'budget-parent',
    'gigs-parent',
    'gigs-kid',
    'chores-parent',
    'rewards-kid',
];

const ACCOUNTS = [
    {
        email: process.env.E2E_EMAIL || 'e2e-fresh@example.com',
        password: process.env.E2E_PASSWORD || 'fresh1234',
    },
    {
        email: process.env.E2E_CHILD_EMAIL || 'emma@demo.com',
        password: process.env.E2E_CHILD_PASSWORD || 'password123',
    },
    { email: 'mom@demo.com', password: 'password123' },
    { email: 'dad@demo.com', password: 'password123' },
    { email: 'lucas@demo.com', password: 'password123' },
];

async function ackToursFor(account) {
    const login = await fetch(`${BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: BASE_URL },
        body: JSON.stringify(account),
    });
    // A missing demo account is not a setup failure — the specs that need it
    // skip themselves. Only report, never throw.
    if (!login.ok) return `${account.email}: login ${login.status}`;

    const cookie = (login.headers.getSetCookie?.() ?? [])
        .map((c) => c.split(';')[0])
        .join('; ');
    if (!cookie) return `${account.email}: no cookies`;

    for (const id of TOUR_IDS) {
        await fetch(`${BASE_URL}/api/onboarding/tours/${id}/complete`, {
            method: 'POST',
            headers: { Cookie: cookie, Origin: BASE_URL },
        }).catch(() => {});
    }
    return null;
}

module.exports = async () => {
    const problems = (await Promise.all(ACCOUNTS.map(ackToursFor))).filter(Boolean);
    if (problems.length) {
        // Visible, not fatal: the suite still runs, and this line explains any
        // tour overlay that shows up in a failure screenshot.
        console.log(`[global-setup] tours not pre-acked for — ${problems.join(', ')}`);
    }
};
