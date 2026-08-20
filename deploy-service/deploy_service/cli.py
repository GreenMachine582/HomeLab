"""deploy-service — metadata-driven service deployer.

Usage:
  deploy-service deploy <repo> [--config PATH] [--inventory PATH] [--topology PATH] [--dry-run]
"""
import argparse
import sys
from pathlib import Path

from . import config, compose, infisical, topology
from . import target as target_mod

_DEFAULT_CONFIG = "/opt/homelab/services.yml"


def _cmd_deploy(args: argparse.Namespace) -> None:
    print(f"[deploy-service] Deploying '{args.repo}' (config: {args.config})")

    entry = config.load(args.config, args.repo)

    repo_url = entry["repo"]
    path = entry["path"]
    deployment = entry.get("deployment", {})
    deploy_cfg = entry.get("deploy", {})
    secrets_cfg = entry.get("secrets", {})

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

    topology_path = (
        Path(args.topology) if args.topology
        else Path(args.config).resolve().parent / "topology.yml"
    )

    device = entry.get("device")
    if device:
        target_node = topology.resolve_hostname(device, topology.load(str(topology_path)))
        print(f"[deploy-service] device '{device}' -> '{target_node}'")
    else:
        target_node = entry.get("target_node")
        if not target_node:
            sys.exit(
                f"[deploy-service] '{args.repo}' has no device or target_node set in {args.config}"
            )

    inventory_path = (
        Path(args.inventory) if args.inventory
        else Path(args.config).resolve().parent / "inventories" / "prod.yml"
    )
    tgt = target_mod.resolve(target_node, inventory_path)
    print(f"[deploy-service] target_node '{target_node}' -> {tgt.label()}")

    compose_files = deploy_cfg.get("compose_files", ["docker-compose.yml"])
    strategy = deploy_cfg.get("strategy", "rolling")

    print(f"[deploy-service] Fetching secrets from Infisical")
    secret_specs = secrets_cfg.get("infisical", [])
    injected_env = infisical.fetch(secret_specs)
    # Consumed here for git auth only — never forwarded into the deployed
    # containers' environment.
    github_token = injected_env.pop("GITHUB_PAT", None)

    address_specs = secrets_cfg.get("addresses", [])
    if address_specs:
        print(f"[deploy-service] Resolving addresses for: {', '.join(address_specs)}")
        all_repos = config.load_all(args.config)
        topo = topology.load(str(topology_path))
        for other_repo in address_specs:
            env_name = topology.addr_env_name(other_repo)
            injected_env[env_name] = topology.hostname_for_repo(other_repo, all_repos, topo)
            print(f"  {other_repo} -> {env_name}={injected_env[env_name]}")

    compose.clone_or_pull(repo_url, path, ref=ref, target=tgt, github_token=github_token, dry_run=args.dry_run)
    compose.run_conventional_hook(path, "predeploy.sh", injected_env, "pre-deploy", target=tgt, dry_run=args.dry_run)
    if dtype == "image":
        compose.deploy_image(
            path, compose_files, injected_env, image=image, tag=image_tag,
            strategy=strategy, target=tgt, dry_run=args.dry_run,
        )
    else:
        compose.deploy(path, compose_files, injected_env, strategy=strategy, target=tgt, dry_run=args.dry_run)
    compose.run_conventional_hook(path, "postdeploy.sh", injected_env, "post-deploy", target=tgt, dry_run=args.dry_run)

    if args.dry_run:
        print(f"[deploy-service] Dry run complete — no changes made")
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

    args = parser.parse_args()

    if args.command == "deploy":
        _cmd_deploy(args)
    else:
        parser.print_help()
        sys.exit(1)
