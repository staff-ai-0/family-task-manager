# Google OAuth & PayPal Setup

Rewritten 2026-07-22 against the actual implementation (the prior version described a generic one-off PayPal Payments flow and endpoints that never existed in this codebase).

## Google OAuth

Config (`backend/.env`, read by `app/core/config.py`):

```bash
GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com   # primary web client
GOOGLE_CLIENT_IDS=id1.apps.googleusercontent.com,id2...          # optional: comma list of additional client IDs
                                                                   # (native iOS/Android clients under the same Cloud project)
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=https://family.agent-ia.mx/auth/google/callback
```

`GoogleOAuthService.verify_google_token` (`backend/app/services/google_oauth_service.py`) skips the library's built-in `aud` check and validates the token against the union of `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_IDS` manually, so any client sharing the Cloud project (web, iOS, Android) can authenticate.

**Google Cloud Console**: create an OAuth 2.0 Web-application client, add authorized JavaScript origin + redirect URI matching `GOOGLE_REDIRECT_URI` above (both the local `http://localhost:3003` and prod `https://family.agent-ia.mx` variants).

**Endpoints** (`backend/app/api/routes/oauth.py`, mounted at `/api/oauth`):
- `POST /api/oauth/google` — login/register with a Google ID token; creates the user if new (needs `family_id` or `join_code`).
- `POST /api/oauth/google/verify` — verify a Google token without creating an account.

## PayPal (subscriptions, not one-off payments)

This app bills via **PayPal subscriptions** (recurring Billing Plans), not the classic one-off Payments API — there is no `/api/payment/*` route group. PayPal only; no Stripe, no Mercado Pago.

Config (`backend/.env`):

```bash
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_MODE=sandbox   # or live
PAYPAL_WEBHOOK_ID=...

# One PayPal Billing Plan ID per (tier x cycle) — provisioned via
# backend/scripts/setup_paypal_plans.py, then pasted here:
PAYPAL_PLAN_ID_PLUS_MONTHLY=...
PAYPAL_PLAN_ID_PLUS_ANNUAL=...
PAYPAL_PLAN_ID_PRO_MONTHLY=...
PAYPAL_PLAN_ID_PRO_ANNUAL=...
```

**Endpoints** (`backend/app/api/routes/subscriptions.py` + `subscriptions_webhook.py`, mounted at `/api/subscriptions`):
- `GET /api/subscriptions/plans` — list tiers.
- `GET /api/subscriptions/current` — the family's active subscription.
- `GET /api/subscriptions/usage` — metered-feature usage against plan limits.
- `POST /api/subscriptions/checkout` — creates a PayPal subscription for a plan+billing_cycle, returns an approval URL (redirects to `{PUBLIC_URL}/parent/settings/subscription/activate` on approve, `?cancelled=1` on cancel).
- `POST /api/subscriptions/activate` — finalizes after PayPal approval redirect.
- `POST /api/subscriptions/cancel` — cancels the family's subscription.
- `POST /api/subscriptions/webhook` — PayPal webhook receiver; signature-verified via `PayPalService.verify_webhook_signature`.

**PayPal Developer Dashboard**: create a Sandbox app for dev, a Live app for prod; under the app's Webhooks, point the webhook URL at `https://api-family.agent-ia.mx/api/subscriptions/webhook` and subscribe to the `BILLING.SUBSCRIPTION.*` events (activation/cancellation reconciliation — see `paypal_service.py` for the exact set consumed).

## Secrets in production

Current prod (10.1.0.91) does **not** set `VAULT_ADDR`/`VAULT_TOKEN` — all secrets above live directly in `.env` on the host, per `.env.onprem.example`. (`app/core/vault_bootstrap.py` still folds Vault KV into env if those two vars are ever set, but that path is unused today.)

## See also

- `CLAUDE.md` — canonical env-var table, subscription/premium-gating architecture (`app/core/premium.py`), production layout.
- `backend/app/services/google_oauth_service.py`, `backend/app/services/paypal_service.py` — implementation.
- `backend/scripts/setup_paypal_plans.py` — provisions the PayPal Billing Plans and prints the `PAYPAL_PLAN_ID_*` values to paste into `.env`.
