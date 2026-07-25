#!/usr/bin/env python3
"""Generate inventories/prod.yml from topology.yml.

topology.yml is the single source of truth for devices (see
docs/topology_data_brief.md §3). This script derives the Ansible inventory
from it rather than hand-editing prod.yml — run it after adding, removing,
or re-tagging a device in topology.yml.

Usage:
  python3 scripts/generate_inventory.py [--topology PATH] [--out PATH]
  python3 scripts/generate_inventory.py --check   # print to stdout, don't write
"""
import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOPOLOGY = REPO_ROOT / "topology.yml"
DEFAULT_OUT = REPO_ROOT / "inventories" / "prod.yml"

# Fixed connection defaults — not topology data, edit here directly if they change.
STATIC_VARS_BLOCK = """  vars:
    ansible_user: homelab
    # ~/.ssh/homelab = /home/homelab/.ssh/homelab on the edge node (copied by Phase 1 bootstrap).
    # Phase 2+ playbooks run from the edge node — this path is always correct.
    ansible_ssh_private_key_file: ~/.ssh/homelab
    ansible_python_interpreter: /usr/bin/python3
    ansible_port: "{{ ssh_port }}"
"""

# Fixed group display order; any host_roles value not listed here is
# appended afterward, alphabetically, so a new role doesn't get lost.
GROUP_ORDER = ["edge", "observe", "svc"]


def ip_var_name(hostname: str) -> str:
    """homelab-svc-01 -> ip_svc_01, homelab-edge -> ip_edge."""
    suffix = hostname.removeprefix("homelab-").replace("-", "_")
    return f"ip_{suffix}"


def load_topology(path: Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"[generate_inventory] topology.yml not found: {path}")
    except yaml.YAMLError as e:
        sys.exit(f"[generate_inventory] topology.yml parse error: {e}")
    return data.get("devices", {})


def build_groups(devices: dict) -> dict[str, list[str]]:
    """role -> [hostnames], hosts appended in topology.yml's own device order."""
    groups: dict[str, list[str]] = {}
    for device in devices.values():
        hostname = device["hostname"]
        for role in device.get("host_roles", []):
            groups.setdefault(role, []).append(hostname)

    ordered = {role: groups[role] for role in GROUP_ORDER if role in groups}
    for role in sorted(groups.keys()):
        if role not in ordered:
            ordered[role] = groups[role]
    return ordered


def render(groups: dict[str, list[str]]) -> str:
    lines = [
        "---",
        "# prod.yml",
        "# Production inventory — used from homelab-edge for all Phase 2+ deployments.",
        "# The homelab user (passwordless sudo) is used for all automation.",
        "#",
        "# GENERATED from topology.yml by scripts/generate_inventory.py — do not hand-edit.",
        "# To add, remove, or re-tag a node: edit topology.yml, then re-run that script.",
        "",
        "all:",
        *STATIC_VARS_BLOCK.rstrip("\n").split("\n"),
        "",
        "  children:",
        "    homelab:",
        "      children:",
    ]
    for role, hostnames in groups.items():
        lines.append(f"        {role}:")
        lines.append("          hosts:")
        for hostname in hostnames:
            lines.append(f"            {hostname}:")
            lines.append(f'              ansible_host: "{{{{ {ip_var_name(hostname)} }}}}"')
        lines.append("")
    # CRLF to match the rest of this repo's checked-out line endings
    # (core.autocrlf=true); single trailing newline, no blank line at EOF.
    return "\r\n".join(lines).rstrip("\r\n") + "\r\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY, help="Path to topology.yml")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Path to write the generated inventory")
    parser.add_argument("--check", action="store_true", help="Print to stdout instead of writing --out")
    args = parser.parse_args()

    devices = load_topology(args.topology)
    groups = build_groups(devices)
    output = render(groups)

    if args.check:
        sys.stdout.buffer.write(output.encode("utf-8"))
    else:
        # newline="" disables Python's universal-newline translation on write —
        # the string above already has explicit \r\n, so this avoids it
        # becoming \r\r\n on platforms where os.linesep is \r\n.
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            f.write(output)
        print(f"[generate_inventory] Wrote {args.out}")


if __name__ == "__main__":
    main()
