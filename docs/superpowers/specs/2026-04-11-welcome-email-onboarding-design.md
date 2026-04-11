# Welcome email onboarding — design spec

**Status:** approved (2026-04-11, brainstorming session)
**Repo:** `family-task-manager`
**Scope:** backend + frontend

## 1. Overview

When a new user account is created in `family-task-manager`, the system
must send a welcome email in the user's preferred language containing a
role-aware quick-start checklist and a link to the full user guide. The
guide must be accessible as a public page on the frontend (no auth).

Today only one of the four user-creation paths fires any welcome email,
and even that path uses a brittle `html.replace()` trick and does not
reference the 2000-line `USER_GUIDE_{ES,EN}.md` that already exists.

### Goals

1. **All four paths fire welcome** consistently: `/api/auth/register`,
   `/api/auth/register-family`, Google OAuth first sign-in, and
   `POST /api/invitations/accept`.
2. **Role-aware content**: parents get a setup-oriented quick-start
   (create first task, invite family, configure rewards, hook budget).
   Minors (CHILD + TEEN) get a usage-oriented quick-start (see today's
   tasks, mark done, redeem points).
3. **Bilingual**: `preferred_lang` on `User` drives subject, body, CTA
   labels, and link URL.
4. **Hosted user guide**: `frontend/src/pages/help.astro` (English)
   and `frontend/src/pages/ayuda.astro` (Spanish) render the canonical
   `docs/USER_GUIDE_EN.md` / `docs/USER_GUIDE_ES.md` markdown inside the
   existing Layout. Public routes, no auth middleware.
5. **Timing correctness**: for password-based paths the welcome fires
   *after* email verification completes, so the dashboard link in the
   email always works. For OAuth and invitation accept, Google / the
   invite token already vouch for the email, so welcome fires at the
   moment the `User` row is created.
6. **Idempotent**: `User.welcome_email_sent` boolean ensures the welcome
   is sent at most once per user, regardless of retries / race
   conditions / re-verification flows.
7. **Fire-and-forget**: an email failure never blocks registration,
   verification, OAuth sign-in, or invitation acceptance. Failures are
   logged at WARNING level but do not propagate.

### Non-goals

- No PDF attachments or pandoc/weasyprint pipeline.
- No backfill to existing users. (5 users exist in prod today; 4 are
  demo with fake emails, the 5th is the developer.) Feature applies
  going forward only.
- No onboarding sequence (drip campaign). One welcome per user.
- No role variants beyond parent-vs-minor. TEEN and CHILD share the
  minor template; the full manual already has per-role sections.
- No in-app onboarding UI (tooltips, guided tour, modal). Email + hosted
  guide only.
- `medical-omnichannel` is out of scope. That product provisions users
  via staff, not self-registration, and its email flow has its own
  concerns.
- No automatic retry of failed sends. If Resend returns a failure once,
  the welcome is lost for that user and nobody reconciles it. Adding a
  Celery-based retry queue is a separate spec.
- No bounce monitoring. We mark `welcome_email_sent=True` optimistically
  as soon as Resend accepts the API call. If the destination MTA
  rejects the message 5 minutes later, we don't learn about it.

## 2. Trigger matrix

| Path | File / handler | Role created | Email verified? | When welcome fires |
|---|---|---|---|---|
| `POST /api/auth/register-family` | `backend/app/api/routes/auth.py:61` | `PARENT` | No → verification email sent | Inside `verify_email_token` after `email_verified` flips to True |
| `POST /api/auth/register` | `backend/app/api/routes/auth.py:41` via `AuthService.register_user` | Any (role from request) | No → verification email sent | Inside `verify_email_token` after `email_verified` flips to True |
| `POST /api/oauth/google` first sign-in | `backend/app/services/google_oauth_service.py:151` inside `authenticate_or_create_user` when `is_new_user=True` | `PARENT` (hardcoded default) | Yes (Google vouches) | At `User` creation time, inside `authenticate_or_create_user` before return |
| `POST /api/invitations/accept` | `backend/app/api/routes/invitations.py:163` | Any (from invitation) | No, but invitation token is equivalent proof | Already wired; adapted to go through the new idempotent helper |

### New helper contract

```python
# backend/app/services/email_service.py
@staticmethod
async def send_welcome_if_not_sent(
    db: AsyncSession,
    user: User,
    base_url: str,
) -> bool:
    """
    Send welcome email if this user has never received one.

    Idempotent: safe to call from multiple code paths. If the user
    already has welcome_email_sent=True, returns True without
    re-sending. If the send succeeds, flips the flag and commits.
    Any exception (Resend failure, template error, missing family)
    is caught and logged at WARNING level; returns False.
    """
```

All three call sites that need to fire welcome use this helper:

- `EmailService.verify_email_token` — at the end, after the user is
  marked verified and committed.
- `GoogleOAuthService.authenticate_or_create_user` — when
  `is_new_user=True`, just before returning.
- `invitations.py` accept handler — replaces the existing direct
  `send_welcome_email` call.

### Timing edge cases

- **Password register → verify → login all happen within seconds**:
  fine. Verify fires welcome; welcome shows up in inbox seconds after
  verify email. Dashboard link resolves; user can log in.
- **User never verifies**: no welcome is ever sent. Acceptable — we
  don't want to welcome people who may have typoed their email.
- **User re-clicks the verification link** (e.g. stale tab): `verify_email_token`
  short-circuits because `email_verified` is already True, so welcome
  is not fired a second time. But the idempotent helper provides a
  second belt-and-suspenders guarantee.
- **Google OAuth signs in twice as first sign-in** (race): impossible
  because `authenticate_or_create_user` is atomic inside a DB session
  and the second call will find the user by `oauth_id`. `is_new_user`
  is only True on the very first call.
- **Invitation accepted and then user is somehow re-registered**: the
  idempotent flag catches it.

## 3. Email content

### Visual structure (both variants, both languages)

```
┌─────────────────────────────────────────────┐
│  [LOGO — Family Task Manager]               │
│                                             │
│  {heading: ¡Bienvenido, {name}! / Welcome}  │
│                                             │
│  {role-specific opening paragraph}          │
│                                             │
│  🚀 {quick-start heading}                   │
│  1. ...                                     │
│  2. ...                                     │
│  ...                                        │
│                                             │
│  [ Primary button: Open dashboard → ]       │
│                                             │
│  📘 {secondary link: full manual →}         │
│                                             │
│  ─────                                      │
│  {footer boilerplate, unchanged}            │
└─────────────────────────────────────────────┘
```

HTML generated by a new helper `_build_welcome_html(variant, lang,
user_name, family_name, base_url)`. The helper builds the entire welcome
block directly — no `html.replace()` tricks. The existing `_build_html`
generic helper in `email_service.py:112` stays as-is and continues to be
used for verify / reset / invitation emails.

### Variant PARENT — Spanish

- **Subject:** `¡Bienvenido a Family Task Manager, {name}!`
- **Opening:** `Hola {name}, bienvenido a {family_name} en Family Task Manager. Como padre/madre en esta familia, tienes acceso completo para crear tareas, configurar recompensas, llevar el presupuesto y administrar a todos los miembros.`
- **Quick-start heading:** `🚀 Tus primeros 5 pasos`
- **Steps:**
  1. `📋 **Crea tu primera tarea** — ve a Dashboard → Nueva tarea, asígnala a ti o a otro miembro, ponle puntos como premio.`
  2. `👨‍👩‍👧 **Invita a tu familia** — desde Settings → Miembros genera un código de invitación y compártelo con tu pareja, hijos o adolescentes.`
  3. `🎁 **Configura recompensas** — en Rewards define los premios que los miembros pueden canjear con los puntos que ganen.`
  4. `💰 **Conecta tu presupuesto** — en Budget crea cuentas, categorías y empieza a registrar ingresos/gastos (o escanea un recibo con la cámara).`
  5. `⚙️ **Ajusta el idioma y las notificaciones** — en Profile elige español/inglés y revisa tus preferencias.`
- **Primary CTA:** `Abrir mi dashboard →` → `{base_url}/dashboard`
- **Secondary link:** `📘 Ver manual completo →` → `{base_url}/ayuda`

### Variant PARENT — English

- **Subject:** `Welcome to Family Task Manager, {name}!`
- **Opening:** `Hi {name}, welcome to {family_name} on Family Task Manager. As a parent in this family, you have full access to create tasks, configure rewards, track budgets, and manage all members.`
- **Quick-start heading:** `🚀 Your first 5 steps`
- **Steps:**
  1. `📋 **Create your first task** — go to Dashboard → New task, assign it to yourself or another member, set points as the reward.`
  2. `👨‍👩‍👧 **Invite your family** — from Settings → Members generate an invitation code and share it with your partner, kids, or teens.`
  3. `🎁 **Set up rewards** — in Rewards, define the prizes members can redeem with the points they earn.`
  4. `💰 **Connect your budget** — in Budget create accounts, categories, and start logging income/expenses (or scan a receipt with your camera).`
  5. `⚙️ **Adjust language and notifications** — in Profile pick English/Spanish and review your preferences.`
- **Primary CTA:** `Open my dashboard →` → `{base_url}/dashboard`
- **Secondary link:** `📘 View full user guide →` → `{base_url}/help`

### Variant minor (CHILD / TEEN) — Spanish

- **Subject:** `¡Bienvenido a {family_name}, {name}!`
- **Opening:** `Hola {name}, ya eres parte de {family_name} en Family Task Manager. Aquí puedes ver tus tareas, completarlas para ganar puntos, y canjear esos puntos por recompensas.`
- **Quick-start heading:** `🚀 Cómo empezar`
- **Steps:**
  1. `📋 **Revisa tus tareas del día** — abre Dashboard y verás todo lo que te toca hacer hoy, con cuántos puntos vale cada una.`
  2. `✅ **Marca las tareas como completadas** — cuando termines algo, ponle check. Tus papás revisarán y recibirás los puntos.`
  3. `🎁 **Canjea tus puntos por recompensas** — en Rewards ves la lista de premios disponibles. Elige y canjea.`
  4. `🌐 **Elige tu idioma** — en Profile puedes cambiar entre español e inglés cuando quieras.`
- **Primary CTA:** `Ver mis tareas →` → `{base_url}/dashboard`
- **Secondary link:** `📘 Ver guía para miembros →` → `{base_url}/ayuda`

### Variant minor (CHILD / TEEN) — English

- **Subject:** `Welcome to {family_name}, {name}!`
- **Opening:** `Hi {name}, you're now part of {family_name} on Family Task Manager. Here you can see your tasks, complete them to earn points, and redeem those points for rewards.`
- **Quick-start heading:** `🚀 Getting started`
- **Steps:**
  1. `📋 **Check today's tasks** — open Dashboard and you'll see everything assigned to you today, with the points each one is worth.`
  2. `✅ **Mark tasks as done** — when you finish something, check it off. Your parents will review and you'll get the points.`
  3. `🎁 **Redeem points for rewards** — in Rewards you'll see the list of available prizes. Pick one and redeem.`
  4. `🌐 **Pick your language** — in Profile you can switch between English and Spanish anytime.`
- **Primary CTA:** `See my tasks →` → `{base_url}/dashboard`
- **Secondary link:** `📘 View members' guide →` → `{base_url}/help`

### String storage

The 4 variant-language combinations contribute ~36 new translation keys
total (subject, opening, heading, 4-5 steps, CTA, secondary link) added
to the `TRANSLATIONS` dict in `email_service.py` (top of file, lines
~34-100). Keys namespaced by variant and language:

```
welcome_parent_es_subject, welcome_parent_es_opening, welcome_parent_es_heading,
welcome_parent_es_step1 .. step5, welcome_parent_es_cta,
welcome_parent_es_secondary_link       (9 keys for parent+es, 5 steps)

welcome_minor_es_subject, welcome_minor_es_opening, welcome_minor_es_heading,
welcome_minor_es_step1 .. step4, welcome_minor_es_cta,
welcome_minor_es_secondary_link        (8 keys for minor+es, 4 steps)
```

...and analogous `welcome_parent_en_*` (9 keys), `welcome_minor_en_*`
(8 keys). Total: 9+9+8+8 = 34 keys. Parent has 5 steps, minor has 4. Four small helpers avoid stringly-typed key
construction:

```python
def _welcome_template_keys(user: User) -> str:
    """Return 'parent' or 'minor' depending on user.role."""
    return "parent" if user.role == UserRole.PARENT else "minor"

def _guide_url(base_url: str, lang: str) -> str:
    """Return the hosted manual URL in the user's language."""
    return f"{base_url}/ayuda" if lang == "es" else f"{base_url}/help"
```

## 4. Hosted manual pages

### Routes

- `frontend/src/pages/help.astro` → renders `USER_GUIDE_EN.md`
- `frontend/src/pages/ayuda.astro` → renders `USER_GUIDE_ES.md`

Both are **public routes** (no auth required). The middleware allowlist
in `frontend/src/middleware.ts` is extended to include `/help` and
`/ayuda` in the `publicRoutes` list, exactly like `/login` and
`/forgot-password`.

### Markdown loading

Astro supports importing markdown files as modules with auto-generated
`Content` components and frontmatter / headings metadata. The canonical
files live at the repo root in `docs/USER_GUIDE_*.md`, which from the
perspective of `frontend/src/pages/help.astro` is at the relative path
`../../../docs/USER_GUIDE_EN.md`. Astro (via Vite) allows imports from
outside `src/` by default, so no `astro.config.mjs` change is needed.

```astro
---
import Layout from "../layouts/Layout.astro";
import { Content as GuideContent } from "../../../docs/USER_GUIDE_EN.md";
---

<Layout title="User Guide — Family Task Manager">
    <article class="prose prose-slate max-w-3xl mx-auto px-4 py-12">
        <GuideContent />
    </article>
</Layout>
```

The Spanish page `ayuda.astro` is identical modulo the import path and
title. We intentionally do NOT make a single dynamic `[lang].astro` page
because: (a) the two URLs are the two user-visible routes and having
them hardcoded means they survive middleware changes, (b) the email
link needs to be stable per language, (c) there's no other dynamic
i18n routing in this app to pattern-match against.

### Styling

`prose prose-slate` is the Tailwind Typography plugin class set —
verify it's installed in the frontend; if not, fall back to minimal
custom styles in a `<style>` block. The manual's markdown already has
h1/h2/h3 / bullet / code conventions that Typography handles cleanly.

**Decision if Typography is NOT installed:** skip installing it in this
spec's scope. Write 15-20 lines of CSS in a scoped `<style>` block on
each page covering: `h1/h2/h3` sizes, `ul/ol` indentation, `code`
background, `a` color. Keep it minimal.

### Lang-aware linking between the two pages

A small "English / Español" toggle at the top of each page that links
to the other one, so a user who landed on `/help` via an email but
actually reads Spanish can switch with one click. No server logic —
plain `<a href="/ayuda">Español</a>` and vice versa.

## 5. Code changes & tests

### Files changed / created

**Backend:**

1. `backend/app/models/user.py` — add
   ```python
   welcome_email_sent = Column(Boolean, default=False, nullable=False)
   ```
2. `backend/migrations/versions/2026_04_11_XXXX_add_welcome_email_sent.py`
   — new Alembic revision adding the column as:
   ```python
   op.add_column(
       "users",
       sa.Column(
           "welcome_email_sent",
           sa.Boolean(),
           nullable=False,
           server_default=sa.text("false"),
       ),
   )
   ```
   The `server_default=sa.text("false")` is required so the column
   can be `nullable=False` on a table that already has rows — Postgres
   fills existing rows with the server default. Downgrade drops the
   column. The autogenerate-revision hash `XXXX` is filled in by
   `alembic revision --autogenerate` at creation time.
3. `backend/app/services/email_service.py`:
   - Extend `TRANSLATIONS` with ~40 new welcome_* keys.
   - Add `_welcome_template_keys(user)` and `_guide_url(base_url, lang)`
     helpers near top.
   - Add `_build_welcome_html(variant, lang, user_name, family_name, base_url) -> str`
     that builds the entire welcome HTML without `html.replace`.
   - Rewrite `send_welcome_email` as a thin wrapper that picks variant,
     picks lang, calls `_build_welcome_html`, calls `_send`.
   - Add `send_welcome_if_not_sent(db, user, base_url) -> bool`
     idempotent dispatcher: checks flag, resolves family_name, calls
     `send_welcome_email`, flips flag, commits, wraps in try/except.
4. `backend/app/services/email_service.py:verify_email_token` —
   after marking `email_verified=True` and committing, call
   `send_welcome_if_not_sent`.
5. `backend/app/services/google_oauth_service.py:authenticate_or_create_user`
   — after creating a new user, call `send_welcome_if_not_sent`
   if `is_new_user=True`.
6. `backend/app/api/routes/invitations.py:163` — replace direct
   `send_welcome_email` call with `send_welcome_if_not_sent`.

**Frontend:**

7. `frontend/src/pages/help.astro` — new.
8. `frontend/src/pages/ayuda.astro` — new.
9. `frontend/src/middleware.ts` — add `/help` and `/ayuda` to
   `publicRoutes`.

### Tests (new file: `backend/tests/test_welcome_email.py`)

1. `test_welcome_template_keys_parent_returns_parent` — PARENT user → "parent"
2. `test_welcome_template_keys_child_returns_minor` — CHILD user → "minor"
3. `test_welcome_template_keys_teen_returns_minor` — TEEN user → "minor"
4. `test_guide_url_spanish_returns_ayuda` — `_guide_url("https://x", "es")` → `"https://x/ayuda"`
5. `test_guide_url_english_returns_help` — `_guide_url("https://x", "en")` → `"https://x/help"`
6. `test_build_welcome_html_parent_es_contains_family_name` — HTML string contains the provided family name and the parent-es subject keywords.
7. `test_build_welcome_html_minor_en_has_minor_steps` — HTML for minor variant does NOT contain parent-only keywords like "Invite your family".
8. `test_send_welcome_if_not_sent_sets_flag_on_success` — mock `_send` to return True, verify `user.welcome_email_sent` flips to True and DB is committed.
9. `test_send_welcome_if_not_sent_is_idempotent` — pre-set flag True, call, verify `_send` is NOT called and return value is True.
10. `test_send_welcome_if_not_sent_swallows_exception` — mock `_send` to raise, verify no exception propagates and flag stays False.
11. `test_send_welcome_if_not_sent_missing_family_uses_fallback` — user with a family_id that no longer resolves still sends with a fallback family_name string.
12. `test_verify_email_token_triggers_welcome` — integration: register user, call verify, assert welcome_email_sent=True.
13. `test_password_register_does_not_send_welcome_before_verify` — register only, without verify, assert welcome_email_sent=False.
14. `test_google_oauth_first_signin_triggers_welcome` — mock Google verify, call `authenticate_or_create_user`, assert welcome_email_sent=True.
15. `test_google_oauth_returning_user_does_not_re-send` — same as above but user already exists, assert `_send` NOT called a second time.

**Frontend tests:** no existing e2e infrastructure for FTM frontend
pages. Verify `/help` and `/ayuda` via `curl` after deploy:
- `curl -sI http://localhost:3003/help` → 200, `content-type: text/html`
- `curl -sI http://localhost:3003/ayuda` → 200, `content-type: text/html`
- `curl -s http://localhost:3003/help | grep -c 'Family Task Manager'` → ≥1
- Same for ayuda + Spanish-specific string.

### Error handling contract

All 4 call sites + the idempotent helper use the same try/except pattern:

```python
try:
    await EmailService.send_welcome_if_not_sent(db, user, settings.BASE_URL)
except Exception as e:
    logger.warning(
        f"welcome email dispatch failed for user {user.email}: {e}",
        exc_info=True,
    )
    # deliberately do NOT re-raise: the caller flow must not be blocked
```

The helper itself has its own inner try/except (for Resend failures,
DB commit errors, etc.). The outer try/except is belt-and-suspenders
against unexpected exceptions in the helper's non-try code paths.

## 6. Deployment

Standard feature branch workflow per the repo's pre-commit-hook:

1. `git checkout -b feat/welcome-email-onboarding`
2. Commit backend + frontend changes together.
3. Push, merge to `main` with `--no-ff`.
4. On prod host: `git pull`.
5. `sudo docker compose build --no-cache backend frontend` (backend
   because the Python tests and migration need the new code baked in;
   frontend because the new Astro pages need to be built into the
   image — the bind mount picks them up at runtime but a rebuild
   is cleaner for long-term image state).
6. `docker compose exec backend alembic upgrade head` — applies the
   `welcome_email_sent` migration.
7. `docker compose up -d --force-recreate backend frontend`.
8. Smoke test via `curl` (welcome endpoint is not directly callable
   because the welcome is fire-and-forget inside other endpoints, but
   we can test `/help` and `/ayuda` with `curl`, and exercise the
   trigger indirectly by creating a test account).
9. Document in `docs/deployments/2026-04-11.md` (append section).

## 7. Rollback

If something goes wrong:

1. `git reset --hard <previous-HEAD>` on prod.
2. `sudo docker compose up -d --force-recreate backend frontend`.
3. The `welcome_email_sent` column is additive-only with a default, so
   a code-level rollback is safe without reverting the migration.
   Leaving the column in place doesn't affect any existing queries.
4. If the migration itself is the problem, `alembic downgrade -1`
   drops the column and the previous codebase works unchanged.
