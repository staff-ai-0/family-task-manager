# Jarvis Teen Check-in — Design

**Date:** 2026-10-01
**Status:** design decided in conversation 2026-10-01 (four questions answered by the user, the rest delegated: "go with your picks all over"); awaiting written-spec review
**Program:** UX/GUI program, between D4a pings (PR #295, shipped) and D4b mystery reward. Raised by the user during the D4 brainstorm: *"let jarvis ask the teens if he can help to solve their issues with their task, jarvis can collect feedback from users and collect it on db for later analysis"*.

## Goal

Two things, in one small feature:

1. **Help a stuck teen at the moment they are stuck.** When a teen has a chore that is late or was sent back by a parent, Jarvis offers a hand on their home screen.
2. **Tell the product owner why chores do not get done.** The teen's one-tap reason is stored in a form that can be counted across all families.

## What exists today (and is not changed)

Teens already have Jarvis: a private per-teen thread, advice only (no tools), scoped to the teen's own data, on plans with `ai_features`; plus the free "support" mode. `/parent/jarvis` accepts teens and takes a `?q=` prefill. Nothing in this spec changes how that chat works, what it stores, or who can read it.

## Decisions

**User (2026-10-01):**
- The saved feedback is for the **product owner, across families** — not a per-family report for parents.
- Learn **both** kinds of thing, tagged separately: why chores do not get done, and problems with the app itself.
- Jarvis offers help **in the app, on the teen's home**, when the teen looks stuck. No push.
- **Taps first, chat after:** the teen picks a reason with one tap (that is what is saved), then gets help — a real Jarvis conversation on paid plans, a ready-made tip on every plan.
- **Free text only where tags fall short:** a short note is kept only for the reasons *app problem* and *other*, at most 200 characters, shown to the product owner without the teen's name.

**Delegated to the designer:**
- **Teens only** (role TEEN). Younger kids are out of scope.
- **Parents decide, explicitly.** Every family starts *undecided*: check-ins are off and the parent hub shows a one-time card (only in families that have a teen). Reason: this stores answers given by a minor for the product team, which needs a parent's yes — the same opt-in card pattern the weekly quest used.
- **It must not nag:** at most one offer a day and three a week; "Not now" pauses offers for a week; a chore is asked about once, ever.
- **Only recent chores** (last 14 days): asking about a chore from two months ago helps nobody.
- **The product owner sees no identities:** counts, and notes with a date, a reason and a language — no teen, no family.
- **Parents do not get a per-teen report** in the app. (The family data export still contains the family's own rows, like every other family table.)
- The chat that may follow is ordinary teen Jarvis chat: private, not analysed, not stored for the product owner.

**Not in scope:** children (role CHILD), push notifications for check-ins, AI classification of chat content, a parent-facing report, a per-family view for the operator, replying to a note, CSV export, a retention schedule for notes, any change to teen Jarvis chat itself.

## Rules

### When Jarvis offers

`GET /api/jarvis/checkin` returns an offer only when all of these hold:

- the caller is a TEEN and a participating member;
- `families.teen_checkin_enabled` is `true`;
- the teen has no check-in row created today (family-local date) — **one a day**;
- the teen has fewer than 3 check-in rows in the current Monday–Sunday week (family-local) — **three a week**;
- the teen has no `dismissed` row from the last 7 days — a "Not now" on day D blocks offers on D through D+6 — **"Not now" pauses a week**;
- there is a **candidate chore**.

A candidate chore is one of the teen's own non-bonus assignments, in the caller's family, dated within the last 14 days (today included), with no check-in row yet, that is either:

| Trigger | Condition |
|---|---|
| `sent_back` | status `PENDING` and `approval_status = REJECTED` (a parent rejected it; the app re-opened it for a redo) |
| `late` | status `PENDING` or `OVERDUE`, `assigned_date` before today, and not a `sent_back` row |

One chore is offered: the most recently dated `sent_back` one if any, otherwise the most recently dated `late` one.

"Today" and the week are the family's (`families.timezone`), like every other progress feature.

### What the teen sees

A card on the teen home (under the task deck), in three states, no modal:

1. **Offer.** "🤝 ¿Atorado con *{title}*?" / "🤝 Stuck on *{title}*?" — buttons "Sí, ayúdame" / "Yes, help me" and "Ahora no" / "Not now".
2. **Reason.** Seven chips:

   | Key | ES | EN | Kind |
   |---|---|---|---|
   | `too_hard` | Está muy difícil | It's too hard | chore |
   | `not_clear` | No sé bien qué hacer | I'm not sure what to do | chore |
   | `no_time` | No tengo tiempo | I don't have time | chore |
   | `not_fair` | No me parece justo | It doesn't feel fair | chore |
   | `forgot` | Se me olvidó | I forgot | chore |
   | `app_problem` | La app no me deja | The app won't let me | app |
   | `other` | Otra cosa | Something else | other |

   Tapping a chore-kind chip saves the answer at once. Tapping `app_problem` or `other` opens a note box (optional, 200 characters, with the line "Tu nota llega al equipo de la app, sin tu nombre." / "Your note goes to the app's team, without your name.") and a "Enviar" / "Send" button; the answer is saved on Send.
3. **Help.** A ready-made tip for the reason, and — when the family's plan has `ai_features` — a button "Hablarlo con Jarvis" / "Talk it through with Jarvis" that opens `/parent/jarvis?q=…` with a first message already typed ("Estoy atorado con «{title}»: {reason}. ¿Me ayudas?" / "I'm stuck on "{title}": {reason}. Can you help?"). The teen sends it themselves; nothing reaches the AI before that.

Tips:

| Reason | ES | EN |
|---|---|---|
| `too_hard` | Divídela: pon 5 minutos en el reloj y haz solo la primera parte. | Split it: set a 5-minute timer and do only the first part. |
| `not_clear` | Pide a tu papá o mamá que te muestre una vez cómo debe quedar. | Ask a parent to show you once what "done" looks like. |
| `no_time` | Pégala a algo que ya haces: antes de cenar o al llegar de la escuela. | Attach it to something you already do — before dinner, or right after school. |
| `not_fair` | Díselo a tus papás: en la app pueden volver a repartir las tareas de la semana. | Tell your parents — they can reshuffle the week's chores in the app. |
| `forgot` | Todavía puedes hacerla hoy. Activa las notificaciones para que no se te pase. | You can still do it today. Turn on notifications so it doesn't slip. |
| `app_problem` | Gracias. Lo vamos a revisar. | Thanks. We'll look into it. |
| `other` | Gracias por decirnos. | Thanks for telling us. |

"Not now" saves a `dismissed` row and removes the card. A teen who ignores the card (neither button) gets the same offer on a later visit.

The card never claims that parents cannot see the answer: the app does not show it to them, but the family's data export contains the family's rows.

### What is stored

One row per check-in the teen acted on — table `teen_checkins`:

| Column | Notes |
|---|---|
| `id` | UUID |
| `family_id` | FK `families`, CASCADE, NOT NULL, indexed |
| `user_id` | FK `users`, CASCADE, NOT NULL — the teen |
| `assignment_id` | FK `task_assignments`, SET NULL, nullable |
| `trigger` | `late` / `sent_back` |
| `outcome` | `answered` / `dismissed` |
| `reason` | one of the seven keys; NULL when dismissed |
| `note` | text, ≤ 200 characters (CHECK); only ever set when `reason` is `app_problem` or `other` |
| `days_late` | whole days between the chore's date and today (0 for a same-day `sent_back`) |
| `points` | the chore's points — a non-identifying size signal |
| `lang` | `es` / `en` — the teen's language, for reading notes |
| `created_at` | timestamptz |

Constraints: `UNIQUE(family_id, user_id, assignment_id)` (a chore is asked about once); CHECK `outcome = 'answered'` ⇔ `reason IS NOT NULL`; CHECK `note IS NULL OR reason IN ('app_problem','other')`; CHECK `char_length(note) <= 200`.

The chore's title is **not** copied: titles are written by the family and can contain names.

`POST /api/jarvis/checkin` — body `{assignment_id, outcome, reason?, note?}`. The server re-derives eligibility: the assignment must be the current offer for the caller (same rules as the GET), so a client cannot store rows for another teen, another family, another chore, or past the limits. A note sent with a chore-kind reason is rejected (422), not silently dropped. Whitespace-only notes are stored as NULL. Returns `{saved: true, can_chat: bool}`.

### Parents

`families.teen_checkin_enabled` — nullable boolean, three states like the weekly quest setting:

- `NULL` — undecided: check-ins off; the parent hub shows a one-time card when the family has at least one teen. Every family starts here, existing and new.
- `true` — on. · `false` — off by choice (no card).

Hub card: "Nuevo: Jarvis acompaña a tus adolescentes" / "New: Jarvis checks in with your teens" — "Cuando una tarea se atrasa o la regresas, Jarvis le pregunta a tu adolescente qué pasó y le da una idea para destrabarse. El motivo que elige (y una nota corta si es un problema con la app) nos ayuda a mejorar la app; lo vemos sin nombres." / "When a chore is late or you send it back, Jarvis asks your teen what happened and offers a way to get unstuck. The reason they pick (and a short note if it is a problem with the app) helps us improve the app; we see it without names." — buttons "Activar" / "Turn on" and "Ahora no" / "Not now" (`true` / `false`).

Settings → Family: a checkbox section "Jarvis acompaña a tus adolescentes" / "Jarvis checks in with your teens" with the same explanation; saves at once, toast, reverts on failure (the D4a switch pattern).

### Product owner

Operator console page `/admin/feedback`, backed by `GET /api/admin/teen-checkins?days=30|90` (`require_superadmin`, the only cross-family read; lives in `app/services/admin/`):

- totals: offers answered, offers dismissed, families taking part, teens taking part;
- answers by reason, grouped **chore** (`too_hard`, `not_clear`, `no_time`, `not_fair`, `forgot`) / **app** (`app_problem`) / **other**;
- answers by trigger (`late`, `sent_back`);
- "done afterwards": how many answered check-ins point at a chore that is now completed — the closest thing to "did it help";
- notes, newest first, 50 per page: date, reason, language, text. **No teen, no family, no chore.**

All counts are cast to `int`.

## Architecture

**Backend**
- `backend/app/models/teen_checkin.py` + migration `teen_checkins` (down-revision `family_smart_reminders`): the table and `families.teen_checkin_enabled`.
- `backend/app/services/teen_checkin_service.py`: pure rules (`REASONS`, `NOTE_REASONS`, limits, `pick_candidate`, `may_offer`) and family-scoped queries (`offer_for(db, user)`, `record(db, user, …)`).
- `backend/app/api/routes/jarvis.py`: `GET` and `POST /api/jarvis/checkin` (the frontend already proxies `/api/jarvis/*`).
- `backend/app/services/admin/admin_read_service.py` + the admin router: the summary.
- `backend/app/schemas/family.py`: `teen_checkin_enabled` on update and response.
- `backend/app/services/family_export_service.py`: `teen_checkins` joins `EXPORTED_FAMILY_TABLES` (`jarvis/teen_checkins.json`).
- No LLM call anywhere in this feature, so no AI gate is needed; `can_chat` is `family_tier_allows(…, "ai_features")`.

**Frontend**
- `frontend/src/lib/checkin.ts`: reason copy, tips, the prefilled chat message, pure view helpers (the only place the copy lives).
- `frontend/src/components/home/CheckinCard.astro`: the three-state card; `dashboard.astro` fetches the offer for teens only and passes it to `KidHome`.
- `frontend/src/pages/parent/index.astro`: the opt-in card. `parent/settings/family.astro`: the checkbox.
- `frontend/src/pages/admin/feedback.astro` + a link from the console index.
- No native dialogs; kit classes; section tone unchanged.

**Docs**
- `/privacidad`: a paragraph on teen check-ins (what is stored, who sees it, how a parent turns it off).
- User guides EN/ES: a short section in the Jarvis chapter. `CLAUDE.md`: a note in the Jarvis row.

## Error handling

- The offer request failing → no card. The save failing → the card says so with a toast and stays, so the teen can retry.
- A double tap or two devices: the UNIQUE constraint makes the second save a conflict; the API answers it as already saved (200, idempotent), never a 500.
- The chore deleted meanwhile → `assignment_id` goes NULL; the row stays (counts stay true).
- Family or teen deleted → rows cascade away.

## Testing

Backend: pure rules (candidate priority, 14-day window, daily / weekly / pause limits, note only for the two reasons, 200-character bound); service tests against the DB (offer and save for a teen; a child and a parent get no offer; family off or undecided gets none; another family's chore or another teen's chore can never be saved; the server refuses a non-offered assignment; double save is idempotent; title never stored); the three-state family setting; admin summary (cross-family counts, no identifying field in the response, non-superadmin gets 404); export registry guard; migration test. Dates derive from the real today.

Frontend (vitest): `checkin.ts` copy and helpers; source-structure tests for the card states, the dashboard fetch being teen-only, the hub card, the settings checkbox, the admin page; a guard that every path the browser calls has a route file (the D4a lesson); existing visual and no-native-dialog guards stay green.

## Rollout and production check

Deploy with `./scripts/deploy-onprem.sh`. Every family starts undecided. Check in the demo family only (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`, verified by id): hub card → on; diego (teen) sees an offer for a late chore → picks a reason → tip shown; second visit the same day shows no card; `/admin/feedback` is not reachable for a non-operator. The operator page itself is checked by its tests (the console sits behind Cloudflare Access).
