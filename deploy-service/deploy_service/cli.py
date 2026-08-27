"""deploy-service — metadata-driven service deployer.

Usage:
  deploy-service deploy <repo> [--config PATH] [--inventory PATH] [--topology PATH] [--dry-run]
  deploy-service check <repo> [--config PATH] [--inventory PATH] [--topology PATH]
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import config, compose, infisical, topology
from . import target as target_mod

_DEFAULT_CONFIG = "/opt/homelab/services.yml"

# Same value as the Ansible side's notify_ntfy_url (inventories/group_vars/all/main.yml).
_NTFY_URL = "http://homelab-observe:8085/homelab"
_DISCORD_WEBHOOK_PATH = "/prod/discord/ALERTS_WEBHOOK"


def _notify(repo: str, success: bool, detail: str | None = None) -> None:
    """Best-effort ntfy (Discord fallback) ping on deploy completion.

    Never raises -- a notification failure must never mask or replace the
    real deploy outcome the caller is already handling (re-raising right
    after calling this).
    """
    try:
        status = "SUCCESS" if success else "FAILED"
        emoji = "✅" if success else "🚨"
        msg = f"deploy-service deploy {repo}: {status}"
        if detail and not success:
            msg += f" ({detail})"

        req = urllib.request.Request(
            _NTFY_URL,
            data=msg.encode(),
            headers={
                "Title": f"Deploy {status}: {repo}",
                "Priority": "default" if success else "high",
                "Tags": "white_check_mark" if success else "rotating_light",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            return
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass  # ntfy unreachable -- fall through to Discord

        webhook = infisical.fetch_optional(_DISCORD_WEBHOOK_PATH)
        if not webhook:
            return
        body = json.dumps({"content": f"{emoji} [Deploy] {msg}"}).encode()
        req = urllib.request.Request(
            webhook, data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except BaseException:
        pass


def _resolve_target(args: argparse.Namespace, entry: dict) -> target_mod.Target:
    """Resolve a repo's services.yml entry (device: or target_node:) to
    connection info -- shared by deploy and check, neither of which should
    duplicate this device/topology/inventory resolution logic."""
    topology_path = (
        Path(args.topology) if args.topology
        else Path(args.config).resolve().parent / "topology.yml"
    )

    target_node: str
    device = entry.get("device")
    if device:
        target_node = topology.resolve_hostname(device, topology.load(str(topology_path)))
        print(f"[deploy-service] device '{device}' -> '{target_node}'")
    else:
        maybe_target_node = entry.get("target_node")
        if not maybe_target_node:
            sys.exit(
                f"[deploy-service] '{args.repo}' has no device or target_node set in {args.config}"
            )
        target_node = maybe_target_node

    inventory_path = (
        Path(args.inventory) if args.inventory
        else Path(args.config).resolve().parent / "inventories" / "prod.yml"
    )
    tgt = target_mod.resolve(target_node, inventory_path)
    print(f"[deploy-service] target_node '{target_node}' -> {tgt.label()}")
    return tgt


def _load_repo_secrets(
    entry: dict, path: str, tgt: target_mod.Target, dry_run: bool = False,
) -> tuple[list[dict], list[str]]:
    """Read a repo's own secrets.yml from its checkout (local or remote --
    see compose.read_file), falling back to services.yml's own (legacy)
    secrets.infisical/addresses fields for repos not yet migrated to the
    per-repo convention. Shared by deploy and check."""
    secrets_cfg = entry.get("secrets", {})
    secrets_file = compose.read_file(f"{path}/secrets.yml", target=tgt, dry_run=dry_run)
    secret_specs, address_specs = config.parse_repo_secrets(secrets_file)
    if not secret_specs and not address_specs:
        secret_specs = secrets_cfg.get("infisical", [])
        address_specs = secrets_cfg.get("addresses", [])
    return secret_specs, address_specs


def _cmd_check(args: argparse.Namespace) -> None:
    """Validate a repo's declared secrets exist in Infisical -- no clone, no
    secret values fetched, no deploy. Read-only pre-flight, standalone."""
    entry = config.load(args.config, args.repo)
    path = entry["path"]

    tgt = _resolve_target(args, entry)
    secret_specs, _address_specs = _load_repo_secrets(entry, path, tgt)

    print("[deploy-service] Checking declared secrets exist in Infisical")
    missing = infisical.check_missing(secret_specs)
    if missing:
        print(f"[deploy-service] {len(missing)} secret(s) missing:")
        for line in infisical.format_remediation(missing):
            print(f"  {line}")
        sys.exit(1)

    print(f"[deploy-service] '{args.repo}': all {len(secret_specs)} declared secret(s) present in Infisical")


def _cmd_deploy(args: argparse.Namespace) -> None:
    print(f"[deploy-service] Deploying '{args.repo}' (config: {args.config})")

    entry = config.load(args.config, args.repo)

    repo_url = entry["repo"]
    path = entry["path"]
    deployment = entry.get("deployment", {})
    deploy_cfg = entry.get("deploy", {})

    dtype = deployment.get("type")
    if dtype not in ("compose", "image"):
        sys.exit(
            f"[deploy-service] Unsupported deployment type '{dtype}' "
            f"for '{args.repo}'. Only 'compose' and 'image' are implemented."
        )

    image = None
    if dtype == "image":
        image = deployment.get("image")
        if not image:
            sys.exit(
                f"[deploy-service] '{args.repo}' has deployment.type: image but no "
                f"deployment.image set in {args.config}"
            )

    # --ref overrides the git checkout ref for type: compose, or the image tag
    # to pull for type: image — it means "the version to deploy" in either case.
    ref = args.ref if (args.ref and dtype == "compose") else entry.get("ref", "main")
    image_tag = args.ref if (args.ref and dtype == "image") else "latest"

    tgt = _resolve_target(args, entry)

    compose_files = deploy_cfg.get("compose_files", ["docker-compose.yml"])
    strategy = deploy_cfg.get("strategy", "rolling")

    # Fixed, deploy-service-level secret -- authenticates the clone itself,
    # before any repo's own secrets.yml can be read from its checkout.
    github_token = infisical.fetch_optional(infisical.GITHUB_PAT_PATH)

    compose.clone_or_pull(repo_url, path, ref=ref, target=tgt, github_token=github_token, dry_run=args.dry_run)

    # A repo declares its own required secrets in secrets.yml at its root
    # (discovered by convention, same as predeploy.sh/postdeploy.sh) —
    # falls back to services.yml's secrets.infisical/addresses fields for
    # repos not yet migrated to that convention.
    secret_specs, address_specs = _load_repo_secrets(entry, path, tgt, dry_run=args.dry_run)

    print("[deploy-service] Checking declared secrets exist in Infisical")
    missing = infisical.check_missing(secret_specs)
    if missing:
        print(f"[deploy-service] {len(missing)} secret(s) missing — add them in Infisical, then re-run deploy:")
        for line in infisical.format_remediation(missing):
            print(f"  {line}")
        sys.exit(1)

    print("[deploy-service] Fetching secrets from Infisical")
    injected_env = infisical.fetch(secret_specs)

    if address_specs:
        print(f"[deploy-service] Resolving addresses for: {', '.join(address_specs)}")
        all_repos = config.load_all(args.config)
        topology_path = (
            Path(args.topology) if args.topology
            else Path(args.config).resolve().parent / "topology.yml"
        )
        topo = topology.load(str(topology_path))
        for other_repo in address_specs:
            env_name = topology.addr_env_name(other_repo)
            injected_env[env_name] = topology.hostname_for_repo(other_repo, all_repos, topo)
            print(f"  {other_repo} -> {env_name}={injected_env[env_name]}")

    compose.run_conventional_hook(path, "predeploy.sh", injected_env, "pre-deploy", target=tgt, dry_run=args.dry_run)
    if dtype == "image":
        assert image is not None  # validated above when dtype == "image" was first checked
        compose.deploy_image(
            path, compose_files, injected_env, image=image, tag=image_tag,
            strategy=strategy, target=tgt, dry_run=args.dry_run,
        )
    else:
        compose.deploy(path, compose_files, injected_env, strategy=strategy, target=tgt, dry_run=args.dry_run)
    compose.run_conventional_hook(path, "postdeploy.sh", injected_env, "post-deploy", target=tgt, dry_run=args.dry_run)

    if args.dry_run:
        print("[deploy-service] Dry run complete — no changes made")
    else:
        print(f"[deploy-service] '{args.repo}' deployed successfully")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="deploy-service",
        description="Metadata-driven service deployer for the HomeLab bootstrap repo",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    deploy_p = sub.add_parser("deploy", help="Deploy a service repo")
    deploy_p.add_argument("repo", help="Repo name as listed in services.yml")
    deploy_p.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        metavar="PATH",
        help=f"Path to services.yml (default: {_DEFAULT_CONFIG})",
    )
    deploy_p.add_argument(
        "--inventory",
        default=None,
        metavar="PATH",
        help="Path to the Ansible inventory used to resolve remote target_nodes "
        "(default: <services.yml's dir>/inventories/prod.yml)",
    )
    deploy_p.add_argument(
        "--topology",
        default=None,
        metavar="PATH",
        help="Path to topology.yml, used to resolve a repo's device: field to a "
        "hostname (default: <services.yml's dir>/topology.yml). Ignored for "
        "repos still using target_node: directly.",
    )
    deploy_p.add_argument(
        "--ref",
        default=None,
        metavar="REF",
        help="Version to deploy: overrides the git checkout ref for "
        "deployment.type: compose, or the image tag to pull for "
        "deployment.type: image (default: latest)",
    )
    deploy_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without executing them",
    )

    check_p = sub.add_parser(
        "check", help="Validate a repo's declared secrets exist in Infisical, without deploying"
    )
    check_p.add_argument("repo", help="Repo name as listed in services.yml")
    check_p.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        metavar="PATH",
        help=f"Path to services.yml (default: {_DEFAULT_CONFIG})",
    )
    check_p.add_argument(
        "--inventory",
        default=None,
        metavar="PATH",
        help="Path to the Ansible inventory used to resolve remote target_nodes "
        "(default: <services.yml's dir>/inventories/prod.yml)",
    )
    check_p.add_argument(
        "--topology",
        default=None,
        metavar="PATH",
        help="Path to topology.yml, used to resolve a repo's device: field to a "
        "hostname (default: <services.yml's dir>/topology.yml). Ignored for "
        "repos still using target_node: directly.",
    )

    args = parser.parse_args()

    if args.command == "deploy":
        try:
            _cmd_deploy(args)
        except SystemExit as e:
            if not args.dry_run:
                _notify(args.repo, success=(e.code in (None, 0)), detail=str(e.code))
            raise
        except Exception as e:
            if not args.dry_run:
                _notify(args.repo, success=False, detail=str(e))
            raise
        else:
            if not args.dry_run:
                _notify(args.repo, success=True)
    elif args.command == "check":
        _cmd_check(args)
    else:
        parser.print_help()
        sys.exit(1)
