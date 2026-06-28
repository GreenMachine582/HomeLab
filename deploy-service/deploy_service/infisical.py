"""Infisical Universal Auth secret lookup.

Replicates roles/infisical/tasks/lookup.yml in Python.
Uses stdlib urllib only — no third-party HTTP library needed.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

_API_BASE = "http://127.0.0.1:8222/api"
_RUNTIME_AUTH_PATH = Path.home() / ".infisical_runtime_auth.yml"


def _http(method: str, url: str, body: dict | None = None, token: str | None = None) -> Any:
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        sys.exit(f"[deploy-service] Infisical API error {e.code} {method} {url}: {body_text}")
    except urllib.error.URLError as e:
        sys.exit(f"[deploy-service] Cannot reach Infisical at {url}: {e.reason}")


def _load_runtime_creds() -> tuple[str, str, str]:
    path = _RUNTIME_AUTH_PATH
    if not path.exists():
        sys.exit(
            f"[deploy-service] Runtime credentials not found: {path}\n"
            "  Phase 1 bootstrap must run before deploy-service can look up secrets."
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


def _fetch_secret(token: str, secret_path: str, project_id: str) -> str:
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
    result = _http("GET", f"{_API_BASE}/v3/secrets/raw/{key}?{qs}", token=token)
    value = result.get("secret", {}).get("secretValue")
    if value is None:
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
