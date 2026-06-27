"""Git clone/pull and docker compose operations."""
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None, env: dict | None = None, dry_run: bool = False) -> None:
    display = " ".join(cmd)
    if dry_run:
        print(f"  [dry-run] {display}")
        return
    print(f"  $ {display}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        sys.exit(f"[deploy-service] Command failed (exit {result.returncode}): {display}")


def clone_or_pull(repo: str, path: str, ref: str = "main", dry_run: bool = False) -> None:
    """Clone the service repo if absent, otherwise pull latest."""
    repo_url = f"https://{repo}.git"
    git_dir = Path(path) / ".git"

    if git_dir.exists():
        print(f"[deploy-service] Pulling {repo} → {path}")
        _run(["git", "-C", path, "fetch", "--tags"], dry_run=dry_run)
        _run(["git", "-C", path, "checkout", ref], dry_run=dry_run)
        _run(["git", "-C", path, "pull", "--ff-only"], dry_run=dry_run)
    else:
        print(f"[deploy-service] Cloning {repo_url} → {path}")
        if not dry_run:
            Path(path).mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", repo_url, path], dry_run=dry_run)
        _run(["git", "-C", path, "checkout", ref], dry_run=dry_run)


def deploy(
    path: str,
    compose_files: list[str],
    injected_env: dict[str, str],
    strategy: str = "rolling",
    dry_run: bool = False,
) -> None:
    """Run docker compose pull + up for the service stack.

    strategy='rolling' enforces `up -d --remove-orphans` only — never `down`.
    Secrets are passed as environment variables; nothing is written to disk.
    """
    if strategy != "rolling":
        sys.exit(f"[deploy-service] Unknown deploy strategy '{strategy}'. Only 'rolling' is supported.")

    file_args: list[str] = []
    for cf in compose_files:
        file_args += ["-f", cf]

    env = {**os.environ, **injected_env}

    print(f"[deploy-service] Pulling images ({', '.join(compose_files)})")
    _run(["docker", "compose"] + file_args + ["pull"], cwd=path, env=env, dry_run=dry_run)

    print("[deploy-service] Applying stack (up -d --remove-orphans)")
    _run(
        ["docker", "compose"] + file_args + ["up", "-d", "--remove-orphans"],
        cwd=path,
        env=env,
        dry_run=dry_run,
    )
