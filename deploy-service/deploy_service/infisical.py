"""Infisical Universal Auth secret lookup.

Replicates roles/infisical/tasks/lookup.yml in Python.
Uses stdlib urllib only — no third-party HTTP library needed.
"""
import getpass
import json
import secrets as _secrets_mod
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

_API_BASE = "http://127.0.0.1:8222/api"
_RUNTIME_AUTH_PATH = Path.home() / ".infisical_runtime_auth.yml"

# Fixed, deploy-service-level secret (not declared per-repo) -- needed to
# authenticate the git clone itself, before any repo's own secrets.yml can
# even be read from its checkout.
GITHUB_PAT_PATH = "/prod/deploy/GITHUB_PAT"


def _http(method: str, url: str, body: dict | None = None, token: str | None = None,
          required: bool = True) -> Any:
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if not required and e.code == 404:
            return None
        body_text = e.read().decode(errors="replace")
        sys.exit(f"[deploy-service] Infisical API error {e.code} {method} {url}: {body_text}")
    except urllib.error.URLError as e:
        sys.exit(f"[deploy-service] Cannot reach Infisical at {url}: {e.reason}")


def _load_runtime_creds() -> tuple[str, str, str]:
    path = _RUNTIME_AUTH_PATH
    if not path.exists():
        current_user = getpass.getuser()
        hint = (
            f" — you're running as '{current_user}'; deploy-service must run as 'homelab' "
            "(sudo su - homelab)"
            if current_user != "homelab"
            else ""
        )
        sys.exit(
            f"[deploy-service] Runtime credentials not found: {path}{hint}\n"
            "  If you are the 'homelab' user, Phase 1 bootstrap must run first."
        )
    with open(path) as f:
        creds = yaml.safe_load(f)
    client_id = creds.get("infisical_runtime_client_id")
    client_secret = creds.get("infisical_runtime_client_secret")
    project_id = creds.get("infisical_runtime_project_id")
    if not client_id or not client_secret:
        sys.exit(f"[deploy-service] Missing client_id or client_secret in {path}")
    if not project_id:
        sys.exit(f"[deploy-service] Missing infisical_runtime_project_id in {path} — re-run Phase 1 bootstrap")
    return client_id, client_secret, project_id


def _login(client_id: str, client_secret: str) -> str:
    result = _http(
        "POST",
        f"{_API_BASE}/v1/auth/universal-auth/login",
        body={"clientId": client_id, "clientSecret": client_secret},
    )
    token = result.get("accessToken")
    if not token:
        sys.exit("[deploy-service] Infisical login succeeded but returned no accessToken")
    return token


def _fetch_secret(token: str, secret_path: str, project_id: str, required: bool = True) -> str | None:
    """secret_path is e.g. '/production/cloudflare/TUNNEL_TOKEN'."""
    parts = secret_path.strip("/").split("/")
    if len(parts) < 3:
        sys.exit(f"[deploy-service] Invalid secret path '{secret_path}' — expected /env/folder/KEY")
    # parts: [environment, *folder_parts, key]
    key = parts[-1]
    folder = "/" + "/".join(parts[1:-1])
    env = parts[0]

    qs = urllib.parse.urlencode({
        "workspaceId": project_id,
        "environment": env,
        "secretPath": folder,
    })
    result = _http("GET", f"{_API_BASE}/v3/secrets/raw/{key}?{qs}", token=token, required=required)
    value = result.get("secret", {}).get("secretValue") if result else None
    if value is None and required:
        sys.exit(f"[deploy-service] Secret not found or empty: {secret_path}")
    return value


def fetch(secret_specs: list[dict]) -> dict[str, str]:
    """Return {env_var_name: secret_value} for all specs."""
    if not secret_specs:
        return {}

    client_id, client_secret, project_id = _load_runtime_creds()
    token = _login(client_id, client_secret)

    env_vars: dict[str, str] = {}
    for spec in secret_specs:
        path = spec["path"]
        env_name = spec["env"]
        print(f"  fetching {path} → {env_name}")
        env_vars[env_name] = _fetch_secret(token, path, project_id)
    return env_vars


def fetch_optional(secret_path: str) -> str | None:
    """Like fetch(), but for a single secret that may not exist yet -- returns
    None instead of exiting. For callers with a fallback (e.g. Tailscale IPs
    that aren't registered until an operator sets them)."""
    client_id, client_secret, project_id = _load_runtime_creds()
    token = _login(client_id, client_secret)
    return _fetch_secret(token, secret_path, project_id, required=False)


def check_missing(secret_specs: list[dict]) -> list[dict]:
    """Return the subset of secret_specs not currently present in Infisical
    (missing or empty), without exiting on the first miss. Used for a
    pre-flight report before a deploy tries to inject secrets that don't
    exist yet -- uses the same read-only runtime identity as fetch(), no
    write access needed just to check.
    """
    if not secret_specs:
        return []

    client_id, client_secret, project_id = _load_runtime_creds()
    token = _login(client_id, client_secret)

    missing = []
    for spec in secret_specs:
        value = _fetch_secret(token, spec["path"], project_id, required=False)
        if not value:
            missing.append(spec)
    return missing


def format_remediation(missing_specs: list[dict]) -> list[str]:
    """Turn missing secret specs into ready-to-paste `infisical secrets set`
    commands. Entries with generate: true get a fresh random value inline
    (nothing external to source it from); everything else gets a
    <FILL_ME_IN> placeholder -- can't guess a Discord webhook or license key.
    """
    lines = []
    for spec in missing_specs:
        env, *folder_parts, key = spec["path"].strip("/").split("/")
        folder = "/" + "/".join(folder_parts)
        value = _secrets_mod.token_hex(16) if spec.get("generate") else "<FILL_ME_IN>"
        lines.append(f'infisical secrets set {key}="{value}" --path="{folder}" --env={env}')
    return lines
