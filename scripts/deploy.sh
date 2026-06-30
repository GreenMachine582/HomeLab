#!/bin/bash
# scripts/deploy.sh [PLAYBOOK_STEM [LIMIT [ansible-flags...]]]
#
# Pulls the latest repo BEFORE Ansible loads the playbook, then execs
# ansible-playbook against the requested play. Defaults to deploy_edge /
# homelab-edge so the common case requires no args.
#
# Usage:
#   sudo scripts/deploy.sh                                          # edge deploy (default)
#   sudo scripts/deploy.sh deploy_observe homelab-observe           # observe deploy
#   sudo scripts/deploy.sh deploy_edge homelab-edge --check         # dry-run
#   sudo scripts/deploy.sh deploy_edge homelab-edge --tags alloy --extra-vars "x=1"
#
# Runs via deploy user sudo rule. Both git pull and ansible-playbook run as
# homelab (via runuser) so they share homelab's known_hosts and SSH keys.

set -euo pipefail

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
exec runuser -u homelab -- env HOME="$HOMELAB_HOME" ansible-playbook "$REPO/playbooks/${PLAYBOOK_STEM}.yml" --limit "$LIMIT" "$@"
