"""Load and validate services.yml."""
import sys
import yaml


def load(config_path: str, repo_name: str) -> dict:
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"[deploy-service] services.yml not found: {config_path}")
    except yaml.YAMLError as e:
        sys.exit(f"[deploy-service] services.yml parse error: {e}")

    repos = data.get("repos", {})
    if repo_name not in repos:
        available = ", ".join(repos.keys()) or "(none)"
        sys.exit(
            f"[deploy-service] repo '{repo_name}' not found in {config_path}\n"
            f"  Available: {available}"
        )
    return repos[repo_name]
