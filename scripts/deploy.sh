#!/bin/bash
# scripts/deploy.sh [PLAYBOOK_STEM [LIMIT [ansible-flags...]]]
#
# Pulls the latest repo BEFORE Ansible loads the playbook, then runs
# ansible-playbook against the requested play and reports its real
# success/failure status to ntfy (Discord fallback). Defaults to deploy_edge /
# homelab-edge so the common case requires no args.
#
# Usage:
#   sudo scripts/deploy.sh                                          # edge deploy (default)
#   sudo scripts/deploy.sh deploy_svc homelab-svc-01                # svc deploy
#   sudo scripts/deploy.sh deploy_edge homelab-edge --check         # dry-run
#   sudo scripts/deploy.sh deploy_edge homelab-edge --tags alloy --extra-vars "x=1"
#
# Runs via deploy user sudo rule. Both git pull and ansible-playbook run as
# homelab (via runuser) so they share homelab's known_hosts and SSH keys.

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  sudo scripts/deploy.sh                                          # edge deploy (default)
  sudo scripts/deploy.sh deploy_svc homelab-svc-01                # svc deploy
  sudo scripts/deploy.sh deploy_edge homelab-edge --check         # dry-run
  sudo scripts/deploy.sh deploy_edge homelab-edge --tags alloy --extra-vars "x=1"

Runs via deploy user sudo rule. Both git pull and ansible-playbook run as
homelab (via runuser) so they share homelab's known_hosts and SSH keys.
EOF
  exit 0
fi

REPO="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"

case $# in
  0) PLAYBOOK_STEM=deploy_edge; LIMIT=homelab-edge ;;
  1) echo "error: provide both PLAYBOOK_STEM and LIMIT, or neither" >&2; exit 1 ;;
  *) PLAYBOOK_STEM=$1; LIMIT=$2; shift 2 ;;
esac

HOMELAB_HOME="$(getent passwd homelab | cut -d: -f6)"
HOME="$HOMELAB_HOME" GIT_SSH_COMMAND="ssh -i ${HOMELAB_HOME}/.ssh/github -o BatchMode=yes" \
  runuser -u homelab -- git -C "$REPO" pull --ff-only
cd "$REPO"

set +e
runuser -u homelab -- env HOME="$HOMELAB_HOME" ansible-playbook "$REPO/playbooks/${PLAYBOOK_STEM}.yml" --limit "$LIMIT" "$@"
rc=$?
set -e

# Report real success/failure status -- unlike the playbook's own internal
# "last step" notify task, this sees the actual exit code, so it's the only
# place in the deploy_edge/deploy_svc flow that can report a real failure.
if [ "$rc" -eq 0 ]; then
  STATUS=SUCCESS; TAGS=white_check_mark; PRIORITY=default; EMOJI="✅"
else
  STATUS=FAILED; TAGS=rotating_light; PRIORITY=high; EMOJI="🚨"
fi
MSG="deploy.sh ${PLAYBOOK_STEM} --limit ${LIMIT}: ${STATUS} (exit ${rc})"

if ! curl -sf --max-time 10 \
    -H "Title: Deploy ${STATUS}: ${PLAYBOOK_STEM}" -H "Priority: ${PRIORITY}" -H "Tags: ${TAGS}" \
    -d "$MSG" "http://homelab-observe:8085/homelab" > /dev/null; then
  # ntfy unreachable -- fall back to Discord, fetching the webhook via the
  # same read-only Infisical runtime identity deploy-service already uses
  # (deploy_service.infisical.fetch_optional), rather than reimplementing
  # Universal Auth login a third time in raw bash.
  DISCORD_WEBHOOK="$(runuser -u homelab -- /opt/deploy-service-venv/bin/python3 -c \
    "from deploy_service import infisical; print(infisical.fetch_optional('/prod/discord/ALERTS_WEBHOOK') or '')" \
    2>/dev/null || true)"
  if [ -n "$DISCORD_WEBHOOK" ]; then
    curl -sf --max-time 10 -H "Content-Type: application/json" \
      --data-raw "{\"content\": \"$EMOJI [Deploy] $MSG\"}" \
      "$DISCORD_WEBHOOK" > /dev/null || true
  fi
fi

exit "$rc"
