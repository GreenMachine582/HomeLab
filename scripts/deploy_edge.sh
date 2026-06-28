#!/bin/bash
# scripts/deploy_edge.sh
#
# Wrapper called by the deploy user via sudo to trigger a Phase 2 deploy:
#   sudo /opt/homelab/scripts/deploy_edge.sh [extra ansible-playbook flags]
#
# Pulls the latest repo BEFORE Ansible loads the playbook, so structural
# changes to deploy_edge.yml (new roles, changed secrets mechanism, etc.) take
# effect on the very first run after a push — not the second. Without this,
# Ansible loads the play file into memory at startup and the in-play git pull
# only benefits the NEXT invocation.
#
# Runs as root (via the deploy user's sudo rule). The git pull is delegated to
# the homelab user, who owns the repo and holds /home/homelab/.ssh/github.
# ansible-playbook inherits root context but connects to homelab-edge via SSH
# as the homelab user (inventories/prod.yml ansible_user), so elevated context
# here has no effect on what Ansible can do on the target.
#
# Any extra args are forwarded to ansible-playbook, e.g.:
#   sudo /opt/homelab/scripts/deploy_edge.sh --tags alloy
#   sudo /opt/homelab/scripts/deploy_edge.sh --check

set -euo pipefail

REPO="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"

runuser -u homelab -- git -C "$REPO" pull --ff-only

exec ansible-playbook "$REPO/playbooks/deploy_edge.yml" --limit homelab-edge "$@"
