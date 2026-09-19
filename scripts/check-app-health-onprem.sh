#!/bin/bash
##############################################################################
# Family Task Manager — on-prem 10.1.0.91 app health monitor (alert-only)
#
# Catches the 2026-09-15 incident (same signature as school-admin's 2026-07-31
# one on this same shared host): family_onprem_frontend's process died but
# rootless podman/crun's stored state kept reporting "running" (no OOM, no
# recorded exit, restart policy never fired because it never saw an exit
# event), so `podman ps` looked fine while cloudflared got connection-refused
# and family.agent-ia.mx 502'd for hours before a human noticed. Podman's own
# healthcheck correctly flagged `unhealthy` the whole time — nothing was
# watching it.
#
# Alert-only by design, matching school-admin's deliberate choice on this same
# host: no unattended container recreation in prod. On failure it emails via
# Resend and logs; a human runs `podman stop -t 5 <c> && podman start <c>`
# (plain `restart` does NOT work in this failure mode — conmon is already
# gone, so `restart` errors "conmon exited prematurely"; stop+start is what
# actually clears it).
#
# De-dupes with a state file so a stuck outage sends one "down" email, not
# one every run, and sends a single "recovered" email when it clears.
#
# Required env (already in .91's .env):
#   RESEND_API_KEY  — Resend API key
#   ALERT_EMAIL     — where to send (info@agent-ia.mx)
##############################################################################

set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/jc/family-task-manager}"
LOG_FILE="$PROJECT_DIR/logs/health-check.log"
STATE_FILE="$PROJECT_DIR/logs/.health-check-down-since"

RESEND_API_KEY="${RESEND_API_KEY:-}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
ALERT_FROM="Family Task Manager Health <alerts@agent-ia.mx>"

APP_URL="https://family.agent-ia.mx/"
API_URL="https://api-family.agent-ia.mx/health"
CONTAINERS_WITH_HEALTHCHECK=(family_onprem_db family_onprem_redis family_onprem_backend family_onprem_frontend)

mkdir -p "$(dirname "$LOG_FILE")"
log(){ echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

send_alert() {
    local subject="$1" body="$2"
    if [ -z "$RESEND_API_KEY" ] || [ -z "$ALERT_EMAIL" ]; then
        log "WARN alert suppressed (RESEND_API_KEY/ALERT_EMAIL unset): $subject"
        return 0
    fi
    curl -s -o /dev/null -X POST "https://api.resend.com/emails" \
        -H "Authorization: Bearer ${RESEND_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"from\":\"${ALERT_FROM}\",\"to\":[\"${ALERT_EMAIL}\"],\"subject\":\"${subject}\",\"text\":\"${body}\"}" \
        || true
}

failures=()

check_url() {
    local name="$1" url="$2"
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo "000")
    if [ "$code" != "200" ]; then
        failures+=("$name: HTTP $code ($url)")
    fi
}

check_url "family.agent-ia.mx" "$APP_URL"
check_url "api-family.agent-ia.mx/health" "$API_URL"

for c in "${CONTAINERS_WITH_HEALTHCHECK[@]}"; do
    status=$(podman inspect "$c" --format '{{.State.Health.Status}}' 2>/dev/null || echo "missing")
    if [ "$status" != "healthy" ]; then
        failures+=("$c: podman health=$status")
    fi
done

if ! podman ps --format '{{.Names}}' 2>/dev/null | grep -q '^family_onprem_tunnel$'; then
    failures+=("family_onprem_tunnel: not running")
fi

if [ "${#failures[@]}" -eq 0 ]; then
    log "OK  all checks passed"
    if [ -f "$STATE_FILE" ]; then
        down_since=$(cat "$STATE_FILE")
        rm -f "$STATE_FILE"
        send_alert "[RESOLVED] family-task-manager .91 app is back up" \
            "family.agent-ia.mx and api-family.agent-ia.mx health checks are passing again on $(hostname). Was down since: $down_since"
        log "Sent recovery alert (was down since $down_since)"
    fi
    exit 0
fi

detail=$(printf '%s\n' "${failures[@]}")
log "FAIL: $detail"

if [ ! -f "$STATE_FILE" ]; then
    date +'%Y-%m-%d %H:%M:%S %Z' > "$STATE_FILE"
    send_alert "[ALERT] family-task-manager .91 app is DOWN" \
        "Health check failed on $(hostname):
$detail

See $LOG_FILE and \`podman ps --filter name=family_onprem\` / \`podman logs family_onprem_frontend\` / \`podman logs family_onprem_tunnel\`.
If a container shows podman health=unhealthy but \`podman exec\` into it errors
'is not running' while \`podman inspect\` still says Running:true, plain
\`podman restart\` will fail (conmon already gone) — use:
  podman stop -t 5 <container> && podman start <container>
This alert fires once per outage; a recovery email follows once checks pass again."
    log "Sent down alert"
else
    log "Down alert already sent (down since $(cat "$STATE_FILE")); not re-alerting"
fi

exit 1
