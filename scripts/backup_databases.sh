#!/bin/bash
# scripts/backup_databases.sh
# Manual wrapper to trigger database backups via Ansible.
# Normally run via: ansible-playbook -i inventories/prod.yml playbooks/backup.yml
#
# Run from homelab-edge as the homelab user:
#   bash /opt/homelab/scripts/backup_databases.sh
#   bash /opt/homelab/scripts/backup_databases.sh --node svc-01   # single node

set -euo pipefail

REPO_DIR="$(realpath "$(dirname "$0")/..")"
VAULT_PASS_FILE="${REPO_DIR}/.vault_pass"
INVENTORY="${REPO_DIR}/inventories/prod.yml"
PLAYBOOK="${REPO_DIR}/playbooks/backup.yml"
LOG_DIR="${REPO_DIR}/logs"
LOG_FILE="${LOG_DIR}/backup-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "${LOG_DIR}"

exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "${LOG_FILE}") 2>&1

echo "=== Database backup started: $(date) ==="

if [[ ! -f "${VAULT_PASS_FILE}" ]]; then
  echo "[ERROR] Vault password file not found: ${VAULT_PASS_FILE}"
  exit 1
fi

LIMIT_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node)
      LIMIT_ARG="--limit homelab-${2}"
      shift 2
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      exit 1
      ;;
  esac
done

ansible-playbook \
  -i "${INVENTORY}" \
  "${PLAYBOOK}" \
  --vault-password-file "${VAULT_PASS_FILE}" \
  ${LIMIT_ARG}

echo "=== Database backup finished: $(date) ==="
echo "Log: ${LOG_FILE}"