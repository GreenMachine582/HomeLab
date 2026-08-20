"""Load and validate services.yml."""
import sys
import yaml


def load_all(config_path: str) -> dict:
    """Return the full repos: dict — used to resolve cross-repo `addresses:` references."""
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"[deploy-service] services.yml not found: {config_path}")
    except yaml.YAMLError as e:
        sys.exit(f"[deploy-service] services.yml parse error: {e}")
    return data.get("repos", {})


def load(config_path: str, repo_name: str) -> dict:
    repos = load_all(config_path)
    if repo_name not in repos:
        available = ", ".join(repos.keys()) or "(none)"
        sys.exit(
            f"[deploy-service] repo '{repo_name}' not found in {config_path}\n"
            f"  Available: {available}"
        )
    return repos[repo_name]


def parse_repo_secrets(content: str | None) -> tuple[list[dict], list[str]]:
    """Parse a repo's own secrets.yml content into (secret_specs, addresses).
    Returns ([], []) if the file doesn't exist (content is None) -- callers
    fall back to services.yml's secrets.infisical/addresses fields for repos
    not yet migrated to the convention.
    """
    if content is None:
        return [], []
    data = yaml.safe_load(content) or {}
    return data.get("secrets", []), data.get("addresses", [])
