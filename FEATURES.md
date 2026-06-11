# Family Task Manager — Feature Roadmap Status

Last updated: 2026-05-25 (post-build session).

## Migration chain (17 total)
```
push_subs_v1
 → tmpl_effort_v1     W1.1  effort_level multiplier
 → late_pen_v1        W1.2  auto late penalty
 → chore_lock_v1      W1.3  blocks_rewards
 → shop_v1            W1.4  shopping lists
 → cal_evt_v1         W2.1  calendar events
 → ai_val_v1          W3.1  AI photo validation
 → notif_v1           W3.2  notifications feed
 → kiosk_v1           W3.3  kiosk devices
 → gig_mode_v1        W4.1  gig modes (claim/rotation/competition/collaboration)
 → pet_v1             W4.3  virtual pet (status: UNCERTAIN per user — do not expand)
 → jarvis_v1         W6.1  Jarvis copilot chat history
 → pup_hist_v1        W6.3  PUP score snapshot history
 → meals_v1           W7.2  recipes + meal plan entries
 → fchat_v1           W8.1  family chat messages
 → chat_read_v1       W8.5  users.chat_last_read_at
 → chat_react_v1      W8.6  chat reactions
```

Apply with: `docker compose exec backend alembic upgrade head`

## Backend modules

### Services (new this session)
- `shopping_service` — multi-list family shopping with check/uncheck attribution
- `calendar_service` — events CRUD with date range filter
- `calendar_scanner_service` — Claude Vision OCR of school flyers → event drafts
- `task_proof_validator` — Claude Vision check on gig proof photos for AI auto-approval
- `notification_service` — in-app feed + push fan-out + rate limit (10/hr/user)
- `pet_service` — KidPet CRUD + decay + task hooks + treats catalog
- `analytics_service` — PUP score + snapshot history
- `jarvis_service` — LiteLLM chat + tool calling + SSE streaming + daily cap
- `jarvis_tools` — flat REGISTRY of 10 tools (definition + handler)
- `meal_service` — recipes + plan entries + auto-shop sync + qty parser
- `recipe_importer` — LLM URL scraper for recipes
- `family_chat_service` — messages, SSE poll-stream, reactions, read receipts
- `kiosk` route module — device tokens + snapshot endpoint (token-gated, no auth)

### Cron jobs (lifespan AsyncIOScheduler)
- `_overdue_sweep_loop` — every 60min; PENDING → OVERDUE + auto-penalties
- `subscription_sweep` — 03:00 daily; renewals
- `pet_decay_sweep` — 08:00 daily; pet stat decay + sad/starving notifs
- `pup_snapshot_sweep` — 23:30 daily; PUP score snapshot per family

### Jarvis tools (10)
| Tool | Domain | Write/Read |
|---|---|---|
| create_task_template | Tasks | W |
| create_calendar_event | Calendar | W |
| add_shopping_item | Shopping | W |
| add_recipe | Meals | W |
| schedule_meal | Meals | W |
| send_family_notification | Comms | W |
| list_today_progress | Tasks | R |
| list_pending_approvals | Gigs | R |
| list_overdue_tasks | Tasks | R |
| list_recent_notifications | Comms | R |

### Notable settings
- `GIG_AUTO_APPROVE_STREAK` (default 3)
- `GIG_AI_AUTO_APPROVE_THRESHOLD` (default 0.8)
- `JARVIS_DAILY_MESSAGE_CAP` (default 100 per family)

## Frontend pages new
- `/shopping` — multi-list grocery with check/uncheck
- `/calendar` — agenda + per-day filter
- `/calendar/month` — month grid with source-color dots
- `/calendar/scan` — flyer OCR upload + event preview/edit/import
- `/notifications` — inbox feed + mark-all
- `/kiosk` — fullscreen wall display (token-gated, no auth)
- `/parent/kiosk` — device token management
- `/parent/analytics` — PUP score + 30-day sparkline + per-member completion
- `/parent/jarvis` — copilot chat with SSE streaming + live tool badges
- `/meals` — week grid + recipe form + URL importer
- `/pet` — pet view + treats shop (UNCERTAIN feature)
- `/chat` — family chat with realtime SSE + emoji reactions + read receipts

## Tests
- 18 new test files covering: effort_level, auto_late_penalty, chore_locking,
  shopping_list, calendar_service, calendar_scanner, notifications, kiosk,
  gig_modes, gig_modes_award, gig_rotation_shuffle, kid_pet, pet_treats,
  analytics_pup, receipt_shopping_match, meal_service, meal_shopping_sync,
  recipe_importer, integration_gig_lifecycle, jarvis_tools, jarvis_sse,
  family_chat, chat_read_react
- 5 new E2E specs: shopping, calendar-events, notifications, jarvis,
  kiosk-admin, chat

## Memory entries (private)
- `feedback_virtual_pet_uncertain` — do not expand /pet without checking
- `project_i18n_debt` — new pages use ES/EN ternaries inline; defer refactor

## Skipped per user
- Virtual pet expansion (decision pending)
- GPS / location tracking (privacy)
- i18n centralization (scope vs velocity)

## Open backlog
- Chat: DM threads (recipients table)
- Chat: typing indicators (needs Redis pubsub)
- Realtime broker (Redis) — replace SSE poll for sub-second latency
- Meal: drag-drop reorder week
- Calendar: drag-create on month grid
- Jarvis: streaming token output (currently events only, not chunked reply)
- Jarvis: scheduled prompts (e.g. weekly summary email)
