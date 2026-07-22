# Documentation & AI-Tool Config Audit

Scope: `docs/` (all files + subdirs), root `.md` files, GitHub Copilot search (repo-wide), `.claude/`, `.claudeignore`, root-level compose/backup/scratch files. Nothing deleted or edited — report only, pending confirm.

## (a) DELETE candidates

**1. `.claude/worktrees/agent-a34bc264adae2ec80/` (7.2 MB)** — orphaned but still git-registered worktree (`git worktree list` shows it live, branch `worktree-agent-a34bc264adae2ec80`, HEAD `bb53043`, last touched 2026-05-26). Confirmed **fully merged into main** (`git merge-base --is-ancestor bb53043 main` → true) — nothing here is unique history. Frozen pre-cleanup snapshot containing exactly the cruft the 2026-06-04 audit (`02-techdebt.md`) already flagged as dead: `.github/copilot-instructions.md`, `.github/memory-bank/`, `.github/instructions/`, `.opencode/rules/`, `fam-app.zip`, `web-stack/` prototype, `docker-compose.stage.yml`/`deploy-prod.sh`/`ecosystem.config.cjs` (old PM2/Actual-Budget stack). Remove with `git worktree remove .claude/worktrees/agent-a34bc264adae2ec80` (then `git branch -d worktree-agent-a34bc264adae2ec80`) — not a bare `rm -rf`, or it leaves dangling entries under `.git/worktrees/`. **This is where all the GitHub Copilot artifacts live — the live repo itself has none.**

**2. `docs/deployments/2026-04-11.md`** — only file in `docs/deployments/`, a one-off historical deploy log targeting the already-decommissioned `10.1.0.99` NVMe path, citing a `family_id` that no longer matches the real family (reset 2026-06-23). Nothing links to it.

**3. `docs/BROCHURE_VENTA.html` (20K) + `docs/BROCHURE_VENTA.pdf` (596K)** — zero references anywhere in `frontend/src` or other docs. Committed 2026-03-02 alongside an early landing page; today's landing page doesn't link either. Old dark cyan/magenta branding, not current palette (`docs/design-tokens.md`). 596K unreferenced PDF binary in git.

## (b) CONSOLIDATE candidates

**1. `docs/manual-usuario.md` (20K) + `docs/manual-usuario.pdf` (368K) + `docs/export-pdf.mjs` (8K)** — standalone condensed Spanish manual duplicating the canonical, actively-maintained `docs/USER_GUIDE_ES.md` (108K, last touched 2026-07-21, actually rendered at `/ayuda`). manual-usuario.md is **not** rendered by the app, not in CLAUDE.md's doc table; only consumer is export-pdf.mjs. Hardcodes the dead URL `https://gcp-family.agent-ia.mx` twice. Recommend deleting the trio in favor of USER_GUIDE_ES.md, or regenerating from it + fixing the URL if the short/print format is wanted.

**2. `docs/audit/2026-06-04/`, `docs/audit/2026-07-02-ux/`, `docs/audit/2026-07-07/` (756K total)** — all tracked findings now resolved per project memory (UX audit waves, launch-gap audit both closed). Real historical value (`docs/specs/family-bank.md` still cites `2026-07-07/00-INDEX.md` as roadmap source — don't delete), but nothing marks them archived, so a reader could mistake them for open backlogs. Suggest an "ARCHIVED — resolved, see CLAUDE.md" banner on each index, or move the tree to `docs/audit/archive/`.

## (c) UPDATE candidates

**1. `docs/JARVIS_MCP.md` — HIGH PRIORITY.** Live security/ops runbook still pointing at decommissioned GCP infra: `https://api-gcp-family.agent-ia.mx/mcp`, "Cloudflare Tunnel `gcp-family`" (current canonical is `api-family.agent-ia.mx` via tunnel `family-onprem`). Provisioning commands use `sudo docker compose -f docker-compose.gcp.yml ...` — wrong compose file (rollback-only) and wrong pattern (project convention is rootless podman, no sudo). **Internally self-contradictory**: intro says "Gated by `JARVIS_MCP_HTTP_ENABLED` (default `true`)" while the Security Model section correctly says "off by default (`JARVIS_MCP_HTTP_ENABLED=false`)" — verified against code (`backend/app/core/config.py:67` → `JARVIS_MCP_HTTP_ENABLED: bool = False`), the intro line is simply wrong. Since this doc gates a destructive/money-moving feature, the staleness is operationally risky, not cosmetic.

**2. `docs/OAUTH_PAYMENT_SETUP.md`** — generic boilerplate not matching the real implementation. Documents endpoints that don't exist (`POST /api/oauth/google`, `/api/payment/create`, `/api/payment/execute`, `/api/payment/webhook` — zero grep hits; real routes under `/api/auth/` and `/api/subscriptions/`), describes the classic one-off PayPal Payments API rather than the actual subscriptions-based billing (`paypal_service.py`, `setup_paypal_plans.py`), instructs `vault kv put ...` even though prod doesn't set `VAULT_ADDR`/`VAULT_TOKEN`. Dated 2026-02-27, predates most current auth/billing code. Needs a rewrite or replacement with a short pointer doc.

**3. `.claudeignore` (root)** — actively hides `ARCHITECTURE.md` from Claude's context with the comment "Outdated docs (causes confusion — CLAUDE.md has current truth)". Read `ARCHITECTURE.md` in full: it's accurate and current (correct host, decommission notes, domain model). The ignore entry is stale and counterproductive. Other two entries in that block (`actual/`, `.github/copilot-instructions.md`) are moot — neither path exists at repo root anymore — harmless but worth pruning while touching the file.

**4. `docs/manual-usuario.md`** — see CONSOLIDATE #1 (stale `gcp-family.agent-ia.mx` URL) — listed here as the fix-in-place alternative to deleting.

## (d) KEEP-AS-IS

- **`AGENTS.md`** — minimal, explicitly defers to CLAUDE.md ("do not duplicate content here"), facts match current state. Good pattern.
- **`README.md`, `ARCHITECTURE.md`, `docs/DEPLOYMENT.md`** — verified accurate against CLAUDE.md ground truth.
- **`docs/CAPACITOR.md`, `docs/OBSERVABILITY.md`, `docs/SEO_ASO.md`, `docs/design-tokens.md`, `docs/specs/family-bank.md`** — current, internally consistent, no decommissioned-infra references.
- **`docs/superpowers/plans/*`, `docs/superpowers/specs/*`** — dated 2026-07-17 through 07-21 (this week), tied to recently-shipped PRs (matches git log). Active working-doc trail.
- **`docs/USER_GUIDE_EN.md` / `USER_GUIDE_ES.md`** — actively maintained, correctly rendered at `/help`/`/ayuda`, current content.
- **GitHub Copilot**: no real Copilot artifacts in the live tree. Every "copilot" grep hit at repo root is prose ("Jarvis AI copilot"), not GitHub Copilot config. `.github/` at root contains only `workflows/ci.yml`. No copilot-adjacent file functions as a memory-bank in the live repo — that pattern (`.github/memory-bank/`) only exists inside the orphaned worktree (DELETE #1) and is superseded by the real auto-memory system (`~/.claude/.../memory/MEMORY.md`). Nothing to keep-and-rename.
- **`.claude/settings.local.json`, `.claude/hooks/*.sh`** — live functional config (post-edit test/build hooks, pre-bash guard blocking `alembic downgrade`/force-push-to-main/`rm -rf /`/volume-wipe). Not scratch state.
- **`docker-compose.stage.yml`** — flagged stale in prior audits, confirmed fixed 2026-07-08 (header now explicitly disclaims old content). Non-issue.
- **`.opencode/`, `backups/*.sql`, `.worktrees/`, `.remember/`, `.superpowers/`, `docker-compose.override.yml`** — all untracked/gitignored (`git ls-files` → 0 for each). Not committed cruft, no action needed.

## File-size flags

| File | Size | Status |
|---|---|---|
| `docs/BROCHURE_VENTA.pdf` | 596K | DELETE, binary, unreferenced |
| `docs/manual-usuario.pdf` | 368K | CONSOLIDATE, binary, duplicate of USER_GUIDE_ES.md |
| `docs/audit/2026-07-07/report.html` | 36K | fine, part of archival audit |
| `docs/BROCHURE_VENTA.html` | 20K | DELETE, unreferenced |
| `docs/USER_GUIDE_EN.md` / `_ES.md` | 112K / 108K | KEEP, actively rendered |
| `.claude/worktrees/agent-a34bc264adae2ec80/` | 7.2M | DELETE, whole orphaned worktree |

Total easy-win reclaim if DELETE list actioned: ~8.2 MB, mostly the orphaned worktree.
