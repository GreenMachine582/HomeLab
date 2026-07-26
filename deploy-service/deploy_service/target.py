"""Resolve a services.yml target_node to local-vs-remote connection info.

Local/remote is determined by comparing target_node against this machine's
own hostname -- reliable here because playbooks/bootstrap_edge.yml and
playbooks/bootstrap_node.yml both set the OS hostname to exactly the
inventory/services.yml node name during bootstrap (ansible.builtin.hostname).

Remote connection details (port/user/key) are resolved by shelling out to
`ansible-inventory --host <target_node>`. The host/IP itself is resolved
live from Infisical instead, for the same reason playbooks/resolve_node_ips.yml
does the same: inventories/group_vars/all/overrides.yml's static IP is a
documented fallback only and can drift from the real DHCP-assigned address.
"""
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import infisical

_EDGE_HOSTNAME = "homelab-edge"

# ansible-inventory doesn't template Jinja2 in host vars, so resolve
# single-level references (e.g. "{{ ssh_port }}") ourselves.
_SIMPLE_VAR_REF = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")


def _deref(value, hostvars: dict, var_name: str, target_node: str):
    if not isinstance(value, str):
        return value
    match = _SIMPLE_VAR_REF.match(value)
    if not match:
        return value
    referenced = match.group(1)
    if referenced not in hostvars:
        sys.exit(
            f"[deploy-service] '{var_name}' for '{target_node}' is an unresolved "
            f"template referencing undefined var '{referenced}': {value!r}"
        )
    return hostvars[referenced]


_TAILSCALE_UNSET = "EDIT_BEFORE_USE"
_PROBE_TIMEOUT = 5


def _reachable(host: str, port: int) -> bool:
    """TCP-only reachability check, same technique (and intent) as
    bootstrap_node.yml/bootstrap_edge.yml's own probe plays' wait_for tasks --
    not an auth check, just "is anything listening"."""
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def _live_ip(target_node: str, port: int) -> str:
    """Same suffix convention as resolve_node_ips.yml / bootstrap_node.yml's probe.
    Prefers Tailscale (stable, unaffected by LAN DHCP drift) when an operator has
    registered it and it's actually reachable; falls back to the LAN IP otherwise
    (unregistered, or the tailnet connection itself is down/timing out)."""
    suffix = target_node.removeprefix("homelab-").replace("-", "_").upper()
    tailscale_ip = infisical.fetch_optional(f"prod/network/TAILSCALE_IP_{suffix}")
    if tailscale_ip and tailscale_ip != _TAILSCALE_UNSET and _reachable(tailscale_ip, port):
        return tailscale_ip
    result = infisical.fetch([{"path": f"prod/network/IP_{suffix}", "env": "_ip"}])
    return result["_ip"]


@dataclass
class Target:
    is_local: bool
    host: str | None = None
    port: int = 22
    user: str = "homelab"
    key_file: str | None = None

    @classmethod
    def local(cls) -> "Target":
        return cls(is_local=True)

    def label(self) -> str:
        return "local" if self.is_local else f"{self.user}@{self.host}:{self.port}"


def resolve(target_node: str, inventory_path: Path) -> Target:
    """Return connection info for target_node, local or remote."""
    if target_node == socket.gethostname():
        return Target.local()

    if not inventory_path.exists():
        sys.exit(
            f"[deploy-service] Cannot resolve remote target_node '{target_node}': "
            f"inventory file not found: {inventory_path}"
        )

    try:
        result = subprocess.run(
            ["ansible-inventory", "-i", str(inventory_path), "--host", target_node],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(
            "[deploy-service] 'ansible-inventory' not found on PATH -- required to "
            f"resolve remote target_node '{target_node}'. Is Ansible installed on "
            "this control node?"
        )

    if result.returncode != 0:
        sys.exit(
            f"[deploy-service] ansible-inventory failed to resolve '{target_node}' "
            f"from {inventory_path}:\n{result.stderr.strip()}"
        )

    try:
        hostvars = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"[deploy-service] ansible-inventory returned invalid JSON for '{target_node}': {e}")

    host = _deref(hostvars.get("ansible_host"), hostvars, "ansible_host", target_node)
    if not host:
        sys.exit(
            f"[deploy-service] '{target_node}' has no ansible_host in {inventory_path} "
            "-- is it a valid host in the inventory?"
        )

    port = _deref(hostvars.get("ansible_port", 22), hostvars, "ansible_port", target_node)

    if target_node != _EDGE_HOSTNAME:
        host = _live_ip(target_node, int(port))

    key_file = hostvars.get("ansible_ssh_private_key_file")
    if key_file:
        key_file = str(Path(key_file).expanduser())

    return Target(
        is_local=False,
        host=host,
        port=int(port),
        user=hostvars.get("ansible_user", "homelab"),
        key_file=key_file,
    )
