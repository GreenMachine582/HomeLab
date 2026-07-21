"""Git clone/pull and docker compose operations, local or remote (over SSH)."""
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .target import Target


def _mask(cmd: list[str], secret: str | None) -> str:
    display = " ".join(cmd)
    if secret:
        display = display.replace(secret, "***")
    return display


def _run(cmd: list[str], cwd: str | None = None, env: dict | None = None,
         secret: str | None = None, dry_run: bool = False) -> None:
    display = _mask(cmd, secret)
    if dry_run:
        print(f"  [dry-run] {display}")
        return
    print(f"  $ {display}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        sys.exit(f"[deploy-service] Command failed (exit {result.returncode}): {display}")


def _ssh_base_cmd(target: Target) -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", str(target.port)]
    if target.key_file:
        cmd += ["-i", target.key_file]
    cmd.append(f"{target.user}@{target.host}")
    return cmd


def _remote_path_exists(target: Target, path: str) -> bool:
    cmd = _ssh_base_cmd(target) + [f"test -d {shlex.quote(path)}"]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def _run_remote(
    target: Target,
    cmd: list[str],
    cwd: str | None = None,
    injected_env: dict[str, str] | None = None,
    secret: str | None = None,
    dry_run: bool = False,
) -> None:
    display = _mask(cmd, secret)
    label = target.label()
    if dry_run:
        print(f"  [dry-run] ssh {label} -- {display}")
        return

    script_lines = ["set -e"]
    if cwd:
        script_lines.append(f"cd {shlex.quote(cwd)}")
    for key, value in (injected_env or {}).items():
        script_lines.append(f"export {key}={shlex.quote(value)}")
    script_lines.append(" ".join(shlex.quote(c) for c in cmd))
    script = "\n".join(script_lines) + "\n"

    print(f"  $ ssh {label} -- {display}")
    ssh_cmd = _ssh_base_cmd(target) + ["bash", "-s"]
    result = subprocess.run(ssh_cmd, input=script.encode())
    if result.returncode != 0:
        sys.exit(f"[deploy-service] Remote command failed on {label} (exit {result.returncode}): {display}")


def _run_on(
    target: Target,
    cmd: list[str],
    cwd: str | None = None,
    injected_env: dict[str, str] | None = None,
    secret: str | None = None,
    dry_run: bool = False,
) -> None:
    if target.is_local:
        env = {**os.environ, **injected_env} if injected_env else None
        _run(cmd, cwd=cwd, env=env, secret=secret, dry_run=dry_run)
    else:
        _run_remote(target, cmd, cwd=cwd, injected_env=injected_env, secret=secret, dry_run=dry_run)


def clone_or_pull(
    repo: str,
    path: str,
    ref: str = "master",
    target: Target | None = None,
    github_token: str | None = None,
    dry_run: bool = False,
) -> None:
    """Clone the service repo if absent, otherwise pull latest.

    github_token (if set) authenticates the clone/pull for private repos —
    embedded in the remote URL only for the duration of the clone/pull, then
    the remote is immediately rewritten back to the bare (token-free) URL so
    the token never sits at rest in .git/config.
    """
    target = target or Target.local()
    bare_url = f"https://{repo}.git"
    auth_url = f"https://x-access-token:{github_token}@{repo}.git" if github_token else bare_url
    git_dir_path = f"{path}/.git" if not target.is_local else str(Path(path) / ".git")

    if target.is_local:
        exists = Path(git_dir_path).exists()
    elif dry_run:
        # No SSH connection attempts under --dry-run — remote state can't be
        # probed without connecting, so assume "already cloned" and show the
        # pull-path plan (a deliberate, documented simplification).
        print(f"  [dry-run] remote state of {path} on {target.label()} unknown without connecting — showing pull plan")
        exists = True
    else:
        exists = _remote_path_exists(target, git_dir_path)

    where = "" if target.is_local else f" (on {target.label()})"
    if exists:
        print(f"[deploy-service] Pulling {repo} → {path}{where}")
        # pre_hook scripts (e.g. envsubst) can mutate tracked config files in
        # place — reset to a clean state first so `pull --ff-only` never
        # conflicts with last deploy's leftover local modifications.
        _run_on(target, ["git", "-C", path, "reset", "--hard"], dry_run=dry_run)
        if github_token:
            _run_on(target, ["git", "-C", path, "remote", "set-url", "origin", auth_url],
                    secret=github_token, dry_run=dry_run)
        _run_on(target, ["git", "-C", path, "fetch", "--tags"], secret=github_token, dry_run=dry_run)
        _run_on(target, ["git", "-C", path, "checkout", ref], dry_run=dry_run)
        _run_on(target, ["git", "-C", path, "pull", "--ff-only"], secret=github_token, dry_run=dry_run)
        if github_token:
            _run_on(target, ["git", "-C", path, "remote", "set-url", "origin", bare_url], dry_run=dry_run)
    else:
        print(f"[deploy-service] Cloning {bare_url} → {path}{where}")
        if target.is_local:
            if not dry_run:
                Path(path).mkdir(parents=True, exist_ok=True)
        else:
            _run_on(target, ["mkdir", "-p", path], dry_run=dry_run)
        _run_on(target, ["git", "clone", auth_url, path], secret=github_token, dry_run=dry_run)
        if github_token:
            _run_on(target, ["git", "-C", path, "remote", "set-url", "origin", bare_url], dry_run=dry_run)
        _run_on(target, ["git", "-C", path, "checkout", ref], dry_run=dry_run)


def run_hooks(
    path: str,
    scripts: list[str],
    injected_env: dict[str, str],
    label: str,
    target: Target | None = None,
    dry_run: bool = False,
) -> None:
    """Run pre/post-deploy hook scripts from the repo checkout, in order.

    Invoked via `bash` rather than executed directly so a missing +x bit on
    the script (e.g. after a fresh git clone) doesn't fail the deploy.
    """
    if not scripts:
        return

    target = target or Target.local()
    for script in scripts:
        print(f"[deploy-service] Running {label} hook: {script}")
        _run_on(target, ["bash", script], cwd=path, injected_env=injected_env, dry_run=dry_run)


def _check_rolling(strategy: str) -> None:
    if strategy != "rolling":
        sys.exit(f"[deploy-service] Unknown deploy strategy '{strategy}'. Only 'rolling' is supported.")


def _up(
    path: str,
    compose_files: list[str],
    injected_env: dict[str, str],
    target: Target | None = None,
    dry_run: bool = False,
) -> None:
    target = target or Target.local()
    file_args: list[str] = []
    for cf in compose_files:
        file_args += ["-f", cf]

    print("[deploy-service] Applying stack (up -d --remove-orphans)")
    _run_on(
        target,
        ["docker", "compose"] + file_args + ["up", "-d", "--remove-orphans"],
        cwd=path,
        injected_env=injected_env,
        dry_run=dry_run,
    )


def deploy(
    path: str,
    compose_files: list[str],
    injected_env: dict[str, str],
    strategy: str = "rolling",
    target: Target | None = None,
    dry_run: bool = False,
) -> None:
    """Run docker compose pull + up for the service stack.

    strategy='rolling' enforces `up -d --remove-orphans` only — never `down`.
    Secrets are passed as environment variables; nothing is written to disk.
    """
    _check_rolling(strategy)

    target = target or Target.local()
    file_args: list[str] = []
    for cf in compose_files:
        file_args += ["-f", cf]

    print(f"[deploy-service] Pulling images ({', '.join(compose_files)})")
    _run_on(target, ["docker", "compose"] + file_args + ["pull"], cwd=path, injected_env=injected_env, dry_run=dry_run)

    _up(path, compose_files, injected_env, target=target, dry_run=dry_run)


def pull_image(
    image: str,
    tag: str,
    target: Target | None = None,
    dry_run: bool = False,
) -> None:
    """Explicitly pull a single image:tag — used by deployment.type: image
    so a specific tag can be pulled independent of whatever's pinned in the
    service's docker-compose.yml (unlike `docker compose pull`, which pulls
    whatever the compose file/env already specifies)."""
    target = target or Target.local()
    ref = f"{image}:{tag}"
    print(f"[deploy-service] Pulling image ({ref})")
    _run_on(target, ["docker", "pull", ref], injected_env=None, dry_run=dry_run)


def deploy_image(
    path: str,
    compose_files: list[str],
    injected_env: dict[str, str],
    image: str,
    tag: str,
    strategy: str = "rolling",
    target: Target | None = None,
    dry_run: bool = False,
) -> None:
    """Pull the named image:tag explicitly, then docker compose up -d for the
    service stack — the deployment.type: image counterpart to deploy()."""
    _check_rolling(strategy)
    target = target or Target.local()
    pull_image(image, tag, target=target, dry_run=dry_run)
    _up(path, compose_files, injected_env, target=target, dry_run=dry_run)
