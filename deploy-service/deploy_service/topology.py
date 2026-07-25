"""Load topology.yml and resolve device keys to hostnames."""
import sys
import yaml


def load(topology_path: str) -> dict:
    try:
        with open(topology_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"[deploy-service] topology.yml not found: {topology_path}")
    except yaml.YAMLError as e:
        sys.exit(f"[deploy-service] topology.yml parse error: {e}")
    return data


def resolve_hostname(device_key: str, topology: dict) -> str:
    devices = topology.get("devices", {})
    if device_key not in devices:
        available = ", ".join(devices.keys()) or "(none)"
        sys.exit(
            f"[deploy-service] device '{device_key}' not found in topology.yml\n"
            f"  Available: {available}"
        )
    hostname = devices[device_key].get("hostname")
    if not hostname:
        sys.exit(f"[deploy-service] device '{device_key}' has no hostname set in topology.yml")
    return hostname
