#!/usr/bin/env bash
# Boot-time safety net for the Cloudflare tunnel on on-prem .91 (rootless podman, user jc).
#
# Incident 2026-11-15: after an unclean reboot the stack came up, but cloudflared started
# before the host resolver was usable, failed its edge SRV lookup
# ("lookup _v2-origintunneld._tcp.argotunnel.com ... no such host") and exited 0. The
# systemd unit only runs `compose up -d` once, so nothing retried it: both public
# hostnames returned 530 until a human ran `podman start family_onprem_tunnel`.
#
# This script is run by family-task-manager.service (ExecStartPost). It waits for the
# tunnel to report healthy and, if the container is stopped, starts it again. It never
# fails the unit: a stack that is up without the tunnel is still better than a stack
# systemd marked failed, and scripts/check-app-health-onprem.sh keeps alerting.
#
# Env: TUNNEL_CONTAINER (default family_onprem_tunnel), TUNNEL_WAIT_SECS (default 600),
#      TUNNEL_POLL_SECS (default 10).
set -uo pipefail

CONTAINER="${TUNNEL_CONTAINER:-family_onprem_tunnel}"
WAIT_SECS="${TUNNEL_WAIT_SECS:-600}"
POLL_SECS="${TUNNEL_POLL_SECS:-10}"

log() { echo "ensure-tunnel: $*"; }

deadline=$(( $(date +%s) + WAIT_SECS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    state="$(podman inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo missing)"
    case "$state" in
        running)
            # `starting` is normal for the first ~20 s (healthcheck start_period).
            health="$(podman inspect "$CONTAINER" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"
            if [ "$health" = "healthy" ] || [ -z "$health" ]; then
                log "$CONTAINER healthy"
                exit 0
            fi
            ;;
        exited|stopped|created)
            log "$CONTAINER is $state, starting it"
            podman start "$CONTAINER" >/dev/null 2>&1 || log "start failed, will retry"
            ;;
        missing)
            # Compose has not created it yet (or it was removed); nothing to start.
            ;;
    esac
    sleep "$POLL_SECS"
done

log "gave up after ${WAIT_SECS}s; $CONTAINER is not healthy (check-app-health-onprem.sh will alert)"
exit 0
