import type { APIRoute } from "astro";
import type { LoginResponse } from "../../../types/api";
import { authCookies } from "../../../lib/auth-cookies";
import { clientIpHeaders } from "../../../lib/client-ip";

/**
 * POST /api/auth/register
 * Creates a new family + founding PARENT user, sets httpOnly cookie, and returns JSON.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    try {
        const body = await request.json();
        const { family_name, family_code, name, email, password, preferred_lang, role, accept_terms, birthdate, ref, coupon, timezone } = body;
        // Carry the UI language into the account so the welcome email + first
        // login render in the user's language. Fall back to the lang cookie.
        const lang = preferred_lang === "es" || preferred_lang === "en"
            ? preferred_lang
            : (cookies.get("lang")?.value === "es" ? "es" : "en");

        // Validate required fields
        if (!name || !email || !password) {
            return new Response(
                JSON.stringify({ success: false, error: "All fields are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        // Either family_code or family_name must be provided
        if (!family_code && !family_name) {
            return new Response(
                JSON.stringify({ success: false, error: "Family code or family name is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const registerBody: Record<string, string | boolean> = {
            name,
            email,
            password,
            preferred_lang: lang,
            accept_terms: accept_terms === true,
        };

        // The browser's IANA timezone, so "today" (task lists, shuffle week,
        // payday) is right from day one — the UTC default bit families in the
        // evening, whose calendar showed the next day's tasks. The backend
        // consumes it only when FOUNDING a family and re-validates it with
        // ZoneInfo, falling back to UTC. Length-guarded here because
        // RegisterFamilyRequest.timezone is max_length=64: a junk value must
        // degrade to UTC, never 422 the whole signup over a convenience field.
        if (typeof timezone === "string" && timezone && timezone.length <= 64) {
            registerBody.timezone = timezone;
        }

        if (family_code) {
            registerBody.family_code = family_code;
            // PARENT is never granted via join code (invitation-only); the
            // backend enforces this too — only pass through child/teen.
            if (role === "child" || role === "teen") {
                registerBody.role = role;
            }
            if (typeof birthdate === "string" && birthdate) {
                registerBody.birthdate = birthdate;
            }
        } else {
            registerBody.family_name = family_name;
            // Referral code only applies when FOUNDING a new family. The
            // backend records the referral + grants both families a 30-day
            // Plus credit; an unknown code is ignored (never breaks signup).
            if (typeof ref === "string" && ref.trim()) {
                registerBody.ref = ref.trim().toUpperCase();
            }
            // Coupon code (?coupon=CODE), likewise founding-only. The key is
            // only set when there is a non-empty code:
            // RegisterFamilyRequest.coupon is min_length=1, so forwarding ""
            // would 422 the entire signup instead of just skipping the coupon.
            // An unusable code never breaks signup — the backend redeems
            // best-effort and reports the outcome via coupon_applied.
            if (typeof coupon === "string" && coupon.trim()) {
                registerBody.coupon = coupon.trim().toUpperCase();
            }
        }

        const response = await fetch(`${apiUrl}/api/auth/register-family`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...clientIpHeaders(request) },
            body: JSON.stringify(registerBody),
        });

        const data = await response.json();

        if (response.ok && data.pending_approval) {
            // Join-code signup pending parental approval: no tokens were
            // issued, so no auth cookies — surface the wait-for-parent message.
            return new Response(
                JSON.stringify({ success: true, pending: true, message: data.message }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        if (response.ok) {
            const result = data as LoginResponse;
            const authCks = authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV);
            const headers = new Headers({ "Content-Type": "application/json" });
            for (const c of authCks) headers.append("Set-Cookie", c);
            // Seed the UI language cookie so the dashboard renders in the chosen language.
            cookies.set("lang", lang, { path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365 });
            // Parents land on the parent dashboard (getting-started checklist);
            // kids/teens land on the kid task dashboard.
            const isParent = (data as any)?.user?.role === "parent";
            return new Response(
                JSON.stringify({
                    success: true,
                    redirect: isParent ? "/parent" : "/dashboard",
                    // Relayed so the page can say whether the coupon actually
                    // landed. Defaults to false when the backend omits it.
                    coupon_applied: (data as any)?.coupon_applied === true,
                }),
                { status: 200, headers }
            );
        }

        const errorMessage = data.detail || "Registration failed. Please try again.";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Register error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
