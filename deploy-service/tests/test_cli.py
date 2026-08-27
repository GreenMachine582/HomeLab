"""Tests for deploy_service.cli -- _resolve_target/_load_repo_secrets
extraction, the check/deploy subcommands' control flow, and argparse wiring.

Everything that would touch real infra (Infisical, SSH, git, docker) is
monkeypatched on the imported modules (cli.config/compose/infisical/topology/
target_mod) rather than exercised for real.
"""
import argparse

import pytest

from deploy_service import cli
from deploy_service.target import Target


def _args(**overrides):
    defaults = dict(repo="test-repo", config="/opt/homelab/services.yml", inventory=None, topology=None,
                     ref=None, dry_run=False)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveTarget:
    def test_device_resolves_via_topology(self, monkeypatch):
        monkeypatch.setattr(cli.topology, "load", lambda path: {"devices": {"rpi-02": {"hostname": "homelab-observe"}}})
        monkeypatch.setattr(cli.topology, "resolve_hostname", lambda device, topo: "homelab-observe")
        monkeypatch.setattr(cli.target_mod, "resolve", lambda node, inv: Target(is_local=False, host="192.168.1.11"))

        tgt = cli._resolve_target(_args(), {"device": "rpi-02"})
        assert tgt.host == "192.168.1.11"

    def test_target_node_used_directly_when_no_device(self, monkeypatch):
        captured = {}

        def _fake_resolve(node, inv):
            captured["node"] = node
            return Target.local()
        monkeypatch.setattr(cli.target_mod, "resolve", _fake_resolve)

        cli._resolve_target(_args(), {"target_node": "homelab-edge"})
        assert captured["node"] == "homelab-edge"

    def test_neither_device_nor_target_node_exits(self):
        with pytest.raises(SystemExit) as exc:
            cli._resolve_target(_args(repo="mystery-repo"), {})
        assert "mystery-repo" in str(exc.value)
        assert "no device or target_node" in str(exc.value)


class TestLoadRepoSecrets:
    def test_reads_repo_owned_secrets_yml(self, monkeypatch):
        monkeypatch.setattr(
            cli.compose, "read_file",
            lambda path, target, dry_run=False: "secrets:\n  - path: /prod/authentik/SECRET_KEY\n    env: AUTHENTIK_SECRET_KEY\n",
        )
        secrets, addresses = cli._load_repo_secrets({"path": "/srv/services/authentik-sso"}, "/srv/services/authentik-sso", Target.local())
        assert secrets == [{"path": "/prod/authentik/SECRET_KEY", "env": "AUTHENTIK_SECRET_KEY"}]
        assert addresses == []

    def test_falls_back_to_legacy_services_yml_fields_when_no_secrets_yml(self, monkeypatch):
        monkeypatch.setattr(cli.compose, "read_file", lambda path, target, dry_run=False: None)
        entry = {
            "path": "/srv/services/camunda-platform",
            "secrets": {
                "infisical": [{"path": "/prod/camunda/ADMIN_USER", "env": "CAMUNDA_ADMIN_USER"}],
                "addresses": [],
            },
        }
        secrets, addresses = cli._load_repo_secrets(entry, entry["path"], Target.local())
        assert secrets == [{"path": "/prod/camunda/ADMIN_USER", "env": "CAMUNDA_ADMIN_USER"}]

    def test_repo_with_no_secrets_at_all_returns_empty(self, monkeypatch):
        # Not every repo needs secrets -- an absent secrets.yml and no legacy
        # fallback block is a valid, unremarkable state, not an error.
        monkeypatch.setattr(cli.compose, "read_file", lambda path, target, dry_run=False: None)
        secrets, addresses = cli._load_repo_secrets({"path": "/srv/services/x"}, "/srv/services/x", Target.local())
        assert secrets == []
        assert addresses == []


def _patch_infra(monkeypatch, missing=None, secret_values=None):
    """Stub every infra-touching call cli._cmd_check/_cmd_deploy make."""
    monkeypatch.setattr(cli.target_mod, "resolve", lambda node, inv: Target.local())
    monkeypatch.setattr(cli.compose, "read_file", lambda *a, **k: None)
    monkeypatch.setattr(cli.infisical, "check_missing", lambda specs: missing or [])
    monkeypatch.setattr(cli.infisical, "format_remediation", lambda missing: [f"  fix {m['env']}" for m in missing])
    monkeypatch.setattr(cli.infisical, "fetch", lambda specs: secret_values or {})
    monkeypatch.setattr(cli.infisical, "fetch_optional", lambda path: None)
    monkeypatch.setattr(cli.compose, "clone_or_pull", lambda *a, **k: None)
    monkeypatch.setattr(cli.compose, "run_conventional_hook", lambda *a, **k: None)
    monkeypatch.setattr(cli.compose, "deploy", lambda *a, **k: None)
    monkeypatch.setattr(cli.compose, "deploy_image", lambda *a, **k: None)


class TestCmdCheck:
    def test_all_present_succeeds(self, monkeypatch, capsys):
        _patch_infra(monkeypatch, missing=[])
        monkeypatch.setattr(cli.config, "load", lambda path, repo: {"path": "/srv/services/x", "target_node": "homelab-edge"})

        cli._cmd_check(_args(repo="homelab-edge-services"))  # must not raise
        assert "present in Infisical" in capsys.readouterr().out

    def test_missing_secrets_exits_1_with_remediation(self, monkeypatch, capsys):
        missing = [{"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD"}]
        _patch_infra(monkeypatch, missing=missing)
        monkeypatch.setattr(cli.config, "load", lambda path, repo: {"path": "/srv/services/x", "target_node": "homelab-edge"})

        with pytest.raises(SystemExit) as exc:
            cli._cmd_check(_args(repo="homelab-edge-services"))
        assert exc.value.code == 1
        assert "PIHOLE_WEB_PASSWORD" in capsys.readouterr().out

    def test_never_calls_fetch_or_clone(self, monkeypatch):
        # check must stay read-only: no secret values pulled, nothing cloned.
        _patch_infra(monkeypatch, missing=[])
        monkeypatch.setattr(cli.config, "load", lambda path, repo: {"path": "/srv/services/x", "target_node": "homelab-edge"})

        def _fail(*a, **k):
            raise AssertionError("check must never fetch secret values or clone the repo")
        monkeypatch.setattr(cli.infisical, "fetch", _fail)
        monkeypatch.setattr(cli.compose, "clone_or_pull", _fail)

        cli._cmd_check(_args(repo="homelab-edge-services"))


class TestCmdDeploy:
    def _entry(self, **overrides):
        entry = {
            "repo": "github.com/GreenMachine582/homelab-edge-services",
            "path": "/srv/services/homelab-edge-services",
            "target_node": "homelab-edge",
            "deployment": {"type": "compose"},
            "deploy": {"compose_files": ["docker-compose.yml"]},
        }
        entry.update(overrides)
        return entry

    def test_missing_secrets_exits_1(self, monkeypatch):
        missing = [{"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD"}]
        _patch_infra(monkeypatch, missing=missing)
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry())

        with pytest.raises(SystemExit) as exc:
            cli._cmd_deploy(_args(repo="homelab-edge-services"))
        assert exc.value.code == 1

    def test_unsupported_deployment_type_exits(self, monkeypatch):
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry(deployment={"type": "kubernetes"}))
        with pytest.raises(SystemExit) as exc:
            cli._cmd_deploy(_args(repo="homelab-edge-services"))
        assert "Unsupported deployment type" in str(exc.value)

    def test_image_type_without_image_field_exits(self, monkeypatch):
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry(deployment={"type": "image"}))
        with pytest.raises(SystemExit) as exc:
            cli._cmd_deploy(_args(repo="bottlebot"))
        assert "deployment.image" in str(exc.value)

    def test_successful_deploy_reaches_completion_message(self, monkeypatch, capsys):
        _patch_infra(monkeypatch, missing=[])
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry())

        cli._cmd_deploy(_args(repo="homelab-edge-services"))
        assert "deployed successfully" in capsys.readouterr().out

    def test_dry_run_never_prints_success_message(self, monkeypatch, capsys):
        _patch_infra(monkeypatch, missing=[])
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry())

        cli._cmd_deploy(_args(repo="homelab-edge-services", dry_run=True))
        out = capsys.readouterr().out
        assert "Dry run complete" in out
        assert "deployed successfully" not in out

    def test_address_resolution_does_not_raise_nameerror(self, monkeypatch):
        """Regression guard: extracting _resolve_target out of _cmd_deploy
        (this session, for the `check` subcommand) left `topology_path`
        referenced but undefined in the address_specs branch below --
        NameError on any repo (like the real homelab-edge-services) that
        declares `addresses:` in its secrets.yml. Must never resurface."""
        _patch_infra(monkeypatch, missing=[])
        monkeypatch.setattr(cli.config, "load", lambda path, repo: self._entry())
        monkeypatch.setattr(cli.config, "load_all", lambda path: {
            "homelab-edge-services": self._entry(),
            "homelab-observe-services": {"device": "rpi-02"},
        })
        monkeypatch.setattr(
            cli.compose, "read_file",
            lambda path, target, dry_run=False: "addresses:\n  - homelab-observe-services\n",
        )
        monkeypatch.setattr(cli.topology, "load", lambda path: {"devices": {"rpi-02": {"hostname": "homelab-observe"}}})
        monkeypatch.setattr(cli.topology, "resolve_hostname", lambda device, topo: topo["devices"][device]["hostname"])
        # addr_env_name is left real -- it's pure and already covered in test_topology.py

        cli._cmd_deploy(_args(repo="homelab-edge-services"))  # must not raise NameError


class TestMain:
    def test_no_command_is_a_required_subparsers_usage_error(self, monkeypatch):
        # subparsers are declared required=True, so argparse itself rejects
        # this during parse_args() -- main()'s own `else` dispatch branch is
        # unreachable as a result, but this confirms the CLI still fails
        # loudly (not silently) when invoked with no subcommand.
        monkeypatch.setattr("sys.argv", ["deploy-service"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2

    def test_deploy_help_exits_0(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["deploy-service", "deploy", "--help"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0

    def test_check_help_exits_0(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["deploy-service", "check", "--help"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0

    def test_deploy_requires_repo_positional(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["deploy-service", "deploy"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2  # argparse's own usage-error exit code

    def test_check_dispatches_to_cmd_check(self, monkeypatch):
        called = {}
        monkeypatch.setattr(cli, "_cmd_check", lambda args: called.setdefault("repo", args.repo))
        monkeypatch.setattr("sys.argv", ["deploy-service", "check", "homelab-edge-services"])

        cli.main()
        assert called["repo"] == "homelab-edge-services"

    def test_deploy_dispatches_to_cmd_deploy_and_notifies_on_success(self, monkeypatch):
        monkeypatch.setattr(cli, "_cmd_deploy", lambda args: None)
        notified = {}
        monkeypatch.setattr(cli, "_notify", lambda repo, success, detail=None: notified.setdefault("args", (repo, success)))
        monkeypatch.setattr("sys.argv", ["deploy-service", "deploy", "homelab-edge-services"])

        cli.main()
        assert notified["args"] == ("homelab-edge-services", True)

    def test_deploy_dry_run_skips_notification(self, monkeypatch):
        monkeypatch.setattr(cli, "_cmd_deploy", lambda args: None)
        def _fail(*a, **k):
            raise AssertionError("must not notify on a --dry-run invocation")
        monkeypatch.setattr(cli, "_notify", _fail)
        monkeypatch.setattr("sys.argv", ["deploy-service", "deploy", "homelab-edge-services", "--dry-run"])

        cli.main()
