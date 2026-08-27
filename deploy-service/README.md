# deploy-service

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![pytest](https://img.shields.io/badge/tested_with-pytest-0A9EDC?logo=pytest&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-homelab-4A90D9)

Metadata-driven service deployer for the HomeLab bootstrap repo. Reads
[`services.yml`](../services.yml), clones/pulls each registered repo,
validates and injects its secrets from Infisical, runs its deploy hooks, and
brings the stack up via Docker Compose (or pulls+runs a bare image, for
`deployment.type: image` repos).

Runs **only on `homelab-edge`** — Ansible invokes it rather than
reimplementing its logic (see `deploy_edge.yml`/`deploy_svc.yml`). Reaches
other nodes over SSH via Tailscale. Full design rationale is in
[`docs/repo_split_brief.md`](../docs/repo_split_brief.md) §6.3.

---

## 🚀 Commands

```
deploy-service deploy <repo> [--config PATH] [--inventory PATH] [--topology PATH] [--ref REF] [--dry-run]
deploy-service check <repo> [--config PATH] [--inventory PATH] [--topology PATH]
```

| Command | What it does |
|---|---|
| `deploy` | Clones/pulls the repo, validates its declared secrets exist in Infisical (aborting with `infisical secrets set` remediation if not), fetches and injects them, runs `scripts/predeploy.sh` if present, deploys via `docker compose` (or pulls an image), then runs `scripts/postdeploy.sh` if present. `--dry-run` prints the planned actions without executing them. |
| `check` | The same secrets-validation step `deploy` runs as a pre-flight — on its own. No clone, no secret values fetched, no deploy. Safe to run anytime, including from a repo's own CI, to catch a missing/misconfigured `secrets.yml` before it becomes a failed deploy. |

`--config` defaults to `/opt/homelab/services.yml`; `--inventory`/`--topology` default to `inventories/prod.yml`/`topology.yml` next to it.

---

## 🧪 Development

```bash
pip install -e ".[dev]"

pytest              # 116 tests, no live infra required -- SSH/git/Infisical/
                     # Tailscale calls are all monkeypatched
ruff check .
mypy .
```

The test suite lives in [`tests/`](./tests) — one file per `deploy_service`
module (`config`, `topology`, `target`, `compose`, `infisical`, `cli`), plus
`conftest.py` for shared fixtures. It includes a regression-guard case for
the exact `topology_path` bug that motivated writing it in the first place —
see `tests/test_cli.py::TestCmdDeploy::test_address_resolution_does_not_raise_nameerror`.

---

## 🗂️ Repository structure

```
deploy-service/
├── pyproject.toml
├── deploy_service/
│   ├── cli.py            # argparse entry point, deploy/check subcommands
│   ├── config.py         # services.yml / secrets.yml loading
│   ├── compose.py        # git clone/pull, docker compose, hooks -- local or remote (SSH)
│   ├── target.py         # local-vs-remote connection resolution
│   ├── topology.py       # topology.yml loading, device: -> hostname resolution
│   └── infisical.py      # Infisical secret lookup (Universal Auth)
└── tests/
    ├── conftest.py
    └── test_*.py
```
