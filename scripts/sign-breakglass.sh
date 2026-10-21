#!/usr/bin/env bash
# scripts/sign-breakglass.sh
#
# Signs a one-off public key so it can log in to the nodes as "admin" for a
# limited time, for when Tailscale is unavailable (docs/K8S_SITE.md).
#
# On the site PC (over RDP):  ssh-keygen -t ed25519 -f breakglass
# Paste breakglass.pub here:  scripts/sign-breakglass.sh [validity, default +1h]
# Copy the printed certificate back to the site PC as breakglass-cert.pub, then:
#   ssh -i breakglass -p <ssh_port> admin@<node LAN IP>
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
ca_key="$repo_root/.ssh/homelab-user-ca"
validity="${1:-+1h}"

[[ -f "$ca_key" ]] || { echo "No CA at $ca_key; run: ansible-playbook playbooks/controller.yml --tags ssh_ca" >&2; exit 1; }

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "Paste the public key (one line), then press Enter:"
read -r pubkey
[[ "$pubkey" == ssh-* ]] || { echo "That doesn't look like an OpenSSH public key." >&2; exit 1; }
printf '%s\n' "$pubkey" > "$workdir/breakglass.pub"

ssh-keygen -s "$ca_key" -I "breakglass-$(date +%Y%m%d-%H%M)" -n admin -V "$validity" "$workdir/breakglass.pub" >&2

echo
echo "Certificate (save on the site PC as breakglass-cert.pub, next to the private key):"
cat "$workdir/breakglass-cert.pub"
ssh-keygen -L -f "$workdir/breakglass-cert.pub" | grep -E 'Valid|Principals' -A1 >&2
