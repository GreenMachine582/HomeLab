"""deploy-service — metadata-driven service deployer.

Usage:
  deploy-service deploy <repo> [--config PATH] [--dry-run]
"""
import argparse
import sys

from . import config, compose, infisical

_DEFAULT_CONFIG = "/opt/homelab/services.yml"


def _cmd_deploy(args: argparse.Namespace) -> None:
    print(f"[deploy-service] Deploying '{args.repo}' (config: {args.config})")

    entry = config.load(args.config, args.repo)

    repo_url = entry["repo"]
    ref = entry.get("ref", "main")
    path = entry["path"]
    deployment = entry.get("deployment", {})
    deploy_cfg = entry.get("deploy", {})
    secrets_cfg = entry.get("secrets", {})

    if deployment.get("type") != "compose":
        sys.exit(
            f"[deploy-service] Unsupported deployment type '{deployment.get('type')}' "
            f"for '{args.repo}'. Only 'compose' is implemented."
        )

    compose_files = deploy_cfg.get("compose_files", ["docker-compose.yml"])
    strategy = deploy_cfg.get("strategy", "rolling")

    print(f"[deploy-service] Fetching secrets from Infisical")
    secret_specs = secrets_cfg.get("infisical", [])
    injected_env = infisical.fetch(secret_specs)

    compose.clone_or_pull(repo_url, path, ref=ref, dry_run=args.dry_run)
    compose.deploy(path, compose_files, injected_env, strategy=strategy, dry_run=args.dry_run)

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
