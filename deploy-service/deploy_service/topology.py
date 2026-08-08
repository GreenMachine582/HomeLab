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


def hostname_for_repo(repo_name: str, all_repos: dict, topology: dict) -> str:
    """Resolve another services.yml repo's bound device to its MagicDNS hostname
    (docs/topology_data_brief.md §3.5) — used to inject ADDR_<REPO> for cross-repo addressing."""
    if repo_name not in all_repos:
        sys.exit(
            f"[deploy-service] addresses: references unknown repo '{repo_name}' "
            f"— not found in services.yml"
        )
    device_key = all_repos[repo_name].get("device")
    if not device_key:
        sys.exit(
            f"[deploy-service] addresses: '{repo_name}' has no device: binding "
            f"in services.yml — cannot resolve its address"
        )
    return resolve_hostname(device_key, topology)


def addr_env_name(repo_name: str) -> str:
    """homelab-observe-services -> ADDR_OBSERVE_SERVICES; camunda-platform -> ADDR_CAMUNDA_PLATFORM"""
    name = repo_name.removeprefix("homelab-")
    return "ADDR_" + name.upper().replace("-", "_")
