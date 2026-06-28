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
# Runs as root (deploy user sudo rule). git pull is delegated to homelab, who
# owns the repo and holds /home/homelab/.ssh/github.

set -euo pipefail

REPO="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"

case $# in
  0) PLAYBOOK_STEM=deploy_edge; LIMIT=homelab-edge ;;
  1) echo "error: provide both PLAYBOOK_STEM and LIMIT, or neither" >&2; exit 1 ;;
  *) PLAYBOOK_STEM=$1; LIMIT=$2; shift 2 ;;
esac

runuser -u homelab -- git -C "$REPO" pull --ff-only

exec ansible-playbook "$REPO/playbooks/${PLAYBOOK_STEM}.yml" --limit "$LIMIT" "$@"
