"""Resolve a services.yml target_node to local-vs-remote connection info.

Local/remote is determined by comparing target_node against this machine's
own hostname -- reliable here because playbooks/bootstrap_edge.yml and
playbooks/bootstrap_node.yml both set the OS hostname to exactly the
inventory/services.yml node name during bootstrap (ansible.builtin.hostname).

Remote connection details (host/port/user/key) are resolved by shelling out
to `ansible-inventory --host <target_node>`, so they always match whatever
Ansible itself would use -- never duplicated into services.yml or a new
config file.
"""
import json
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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

    host = hostvars.get("ansible_host")
    if not host:
        sys.exit(
            f"[deploy-service] '{target_node}' has no ansible_host in {inventory_path} "
            "-- is it a valid host in the inventory?"
        )

    key_file = hostvars.get("ansible_ssh_private_key_file")
    if key_file:
        key_file = str(Path(key_file).expanduser())

    return Target(
        is_local=False,
        host=host,
        port=int(hostvars.get("ansible_port", 22)),
        user=hostvars.get("ansible_user", "homelab"),
        key_file=key_file,
    )
