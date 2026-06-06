#!/bin/bash
# scripts/test_connectivity.sh
# Verifies Tailscale mesh connectivity and LAN reachability for all homelab nodes.
# Run from homelab-edge as any user with network access.
#
#   bash /opt/homelab/scripts/test_connectivity.sh

set -euo pipefail

PASS=0
FAIL=0

green() { printf '\e[32m%s\e[0m\n' "$1"; }
red()   { printf '\e[31m%s\e[0m\n' "$1"; }
bold()  { printf '\e[1m%s\e[0m\n' "$1"; }

check() {
  local label="$1"
  local cmd="$2"
  if eval "${cmd}" &>/dev/null; then
    green "  [PASS] ${label}"
    PASS=$(( PASS + 1 ))
  else
    red   "  [FAIL] ${label}"
    FAIL=$(( FAIL + 1 ))
  fi
}

# ── LAN reachability ──────────────────────────────────────────────────────────
bold "=== LAN ping ==="
check "homelab-edge    (192.168.1.10)" "ping -c1 -W2 192.168.1.10"
check "homelab-observe (192.168.1.11)" "ping -c1 -W2 192.168.1.11"
check "homelab-svc-01  (192.168.1.20)" "ping -c1 -W2 192.168.1.20"
check "homelab-svc-02  (192.168.1.21)" "ping -c1 -W2 192.168.1.21"

# ── Tailscale status ──────────────────────────────────────────────────────────
bold "=== Tailscale ==="
check "tailscaled running"    "systemctl is-active --quiet tailscaled"
check "tailscale connected"   "tailscale status --json | grep -q '\"BackendState\":\"Running\"'"

# Tailscale IP reachability (100.x.x.x — fill from tailscale status output)
TAILSCALE_PEERS=$(tailscale status --peers=true 2>/dev/null | awk 'NR>1 {print $1}' || true)
if [[ -n "${TAILSCALE_PEERS}" ]]; then
  bold "=== Tailscale peer ping ==="
  while IFS= read -r ip; do
    check "Tailscale peer ${ip}" "ping -c1 -W2 ${ip}"
  done <<< "${TAILSCALE_PEERS}"
else
  red "  [WARN] No Tailscale peers found — is tailscale up?"
fi

# ── SSH reachability ──────────────────────────────────────────────────────────
bold "=== SSH (port 22) ==="
check "SSH homelab-observe" "nc -z -w3 192.168.1.11 22"
check "SSH homelab-svc-01"  "nc -z -w3 192.168.1.20 22"
check "SSH homelab-svc-02"  "nc -z -w3 192.168.1.21 22"

# ── Service endpoint checks ───────────────────────────────────────────────────
bold "=== Service endpoints ==="
check "Grafana        (192.168.1.11:3000)" "curl -sf --max-time 5 http://192.168.1.11:3000/api/health"
check "Prometheus     (192.168.1.11:9090)" "curl -sf --max-time 5 http://192.168.1.11:9090/-/healthy"
check "Alertmanager   (192.168.1.11:9093)" "curl -sf --max-time 5 http://192.168.1.11:9093/-/healthy"
check "Loki           (192.168.1.11:3100)" "curl -sf --max-time 5 http://192.168.1.11:3100/ready"
check "Uptime Kuma    (192.168.1.11:3001)" "curl -sf --max-time 5 http://192.168.1.11:3001"
check "Portainer      (192.168.1.11:9000)" "curl -sf --max-time 5 http://192.168.1.11:9000"
check "Camunda        (192.168.1.20:8080)" "curl -sf --max-time 5 http://192.168.1.20:8080"
check "n8n            (192.168.1.20:5678)" "curl -sf --max-time 5 http://192.168.1.20:5678/healthz"
check "GreenTechHub   (192.168.1.21:8000)" "curl -sf --max-time 5 http://192.168.1.21:8000/health"

# ── Pi-hole DNS ───────────────────────────────────────────────────────────────
bold "=== Pi-hole DNS ==="
check "DNS: grafana.homelab.local"      "dig +short +time=3 grafana.homelab.local @192.168.1.10 | grep -q 192.168.1.11"
check "DNS: camunda.homelab.local"      "dig +short +time=3 camunda.homelab.local @192.168.1.10 | grep -q 192.168.1.20"
check "DNS: greentechhub.homelab.local" "dig +short +time=3 greentechhub.homelab.local @192.168.1.10 | grep -q 192.168.1.21"

# ── Cloudflare Tunnel ─────────────────────────────────────────────────────────
bold "=== Cloudflare Tunnel ==="
check "cloudflared container running" "docker inspect --format='{{.State.Running}}' cloudflared 2>/dev/null | grep -q true"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
bold "=== Results ==="
green "  Passed: ${PASS}"
[[ ${FAIL} -gt 0 ]] && red "  Failed: ${FAIL}" || green "  Failed: ${FAIL}"
echo ""
[[ ${FAIL} -eq 0 ]]   # exit 0 on full pass, 1 if any failures