"""Tests for deploy_service.target — local/remote target resolution."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy_service import target as target_mod
from deploy_service.target import Target


class TestTargetDataclass:
    def test_local_factory(self):
        t = Target.local()
        assert t.is_local is True
        assert t.host is None
        assert t.label() == "local"

    def test_remote_label(self):
        t = Target(is_local=False, host="10.0.0.5", port=2222, user="homelab")
        assert t.label() == "homelab@10.0.0.5:2222"


class TestDeref:
    HOSTVARS = {"ssh_port": 2222, "ansible_host": "10.0.0.5"}

    def test_non_string_passthrough(self):
        assert target_mod._deref(22, self.HOSTVARS, "ansible_port", "homelab-edge") == 22

    def test_non_template_string_passthrough(self):
        assert target_mod._deref("10.0.0.5", self.HOSTVARS, "ansible_host", "homelab-edge") == "10.0.0.5"

    def test_resolves_simple_template_ref(self):
        assert target_mod._deref("{{ ssh_port }}", self.HOSTVARS, "ansible_port", "homelab-edge") == 2222

    def test_undefined_ref_exits(self):
        with pytest.raises(SystemExit) as exc:
            target_mod._deref("{{ nonexistent }}", self.HOSTVARS, "ansible_port", "homelab-observe")
        msg = str(exc.value)
        assert "ansible_port" in msg
        assert "homelab-observe" in msg
        assert "nonexistent" in msg


class _FakeSocket:
    """Minimal context manager stand-in for socket.create_connection's return
    value -- SimpleNamespace can't be used here since `with` looks up
    __enter__/__exit__ on the type, not instance attributes."""
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestReachable:
    def test_true_when_connection_succeeds(self, monkeypatch):
        monkeypatch.setattr(
            target_mod.socket, "create_connection",
            lambda addr, timeout: _FakeSocket(),
        )
        assert target_mod._reachable("10.0.0.5", 22) is True

    def test_false_on_oserror(self, monkeypatch):
        def _raise(addr, timeout):
            raise OSError("connection refused")
        monkeypatch.setattr(target_mod.socket, "create_connection", _raise)
        assert target_mod._reachable("10.0.0.5", 22) is False


class TestLiveIp:
    def test_prefers_reachable_tailscale_ip(self, monkeypatch):
        monkeypatch.setattr(target_mod.infisical, "fetch_optional", lambda path: "100.64.0.5")
        monkeypatch.setattr(target_mod, "_reachable", lambda host, port: True)
        fetch_calls = []
        monkeypatch.setattr(target_mod.infisical, "fetch", lambda specs: fetch_calls.append(specs) or {"_ip": "SHOULD_NOT_BE_USED"})

        assert target_mod._live_ip("homelab-observe", 22) == "100.64.0.5"
        assert fetch_calls == []  # LAN fallback never consulted

    def test_falls_back_when_tailscale_ip_unset_placeholder(self, monkeypatch):
        monkeypatch.setattr(target_mod.infisical, "fetch_optional", lambda path: target_mod._TAILSCALE_UNSET)
        monkeypatch.setattr(target_mod, "_reachable", lambda host, port: True)
        monkeypatch.setattr(target_mod.infisical, "fetch", lambda specs: {"_ip": "192.168.1.11"})

        assert target_mod._live_ip("homelab-observe", 22) == "192.168.1.11"

    def test_falls_back_when_tailscale_ip_unreachable(self, monkeypatch):
        monkeypatch.setattr(target_mod.infisical, "fetch_optional", lambda path: "100.64.0.5")
        monkeypatch.setattr(target_mod, "_reachable", lambda host, port: False)
        monkeypatch.setattr(target_mod.infisical, "fetch", lambda specs: {"_ip": "192.168.1.11"})

        assert target_mod._live_ip("homelab-observe", 22) == "192.168.1.11"

    def test_falls_back_when_tailscale_ip_not_registered(self, monkeypatch):
        monkeypatch.setattr(target_mod.infisical, "fetch_optional", lambda path: None)
        monkeypatch.setattr(target_mod.infisical, "fetch", lambda specs: {"_ip": "192.168.1.11"})

        assert target_mod._live_ip("homelab-observe", 22) == "192.168.1.11"


def _mock_run_success(hostvars: dict):
    def _run(cmd, capture_output, text):
        return SimpleNamespace(returncode=0, stdout=json.dumps(hostvars), stderr="")
    return _run


class TestResolve:
    def test_local_short_circuits_before_touching_inventory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "homelab-edge")
        missing_inventory = tmp_path / "does-not-exist" / "prod.yml"

        tgt = target_mod.resolve("homelab-edge", missing_inventory)
        assert tgt.is_local is True

    def test_missing_inventory_file_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        missing_inventory = tmp_path / "prod.yml"

        with pytest.raises(SystemExit) as exc:
            target_mod.resolve("homelab-observe", missing_inventory)
        assert "inventory file not found" in str(exc.value)

    def test_ansible_inventory_not_on_path_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")

        def _raise(*a, **k):
            raise FileNotFoundError()
        monkeypatch.setattr(target_mod.subprocess, "run", _raise)

        with pytest.raises(SystemExit) as exc:
            target_mod.resolve("homelab-observe", inventory)
        assert "ansible-inventory" in str(exc.value)

    def test_ansible_inventory_nonzero_exit_includes_stderr(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")

        monkeypatch.setattr(
            target_mod.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="host not found"),
        )

        with pytest.raises(SystemExit) as exc:
            target_mod.resolve("homelab-observe", inventory)
        assert "host not found" in str(exc.value)

    def test_invalid_json_stdout_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")

        monkeypatch.setattr(
            target_mod.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
        )

        with pytest.raises(SystemExit) as exc:
            target_mod.resolve("homelab-observe", inventory)
        assert "invalid JSON" in str(exc.value)

    def test_missing_ansible_host_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(target_mod.subprocess, "run", _mock_run_success({}))

        with pytest.raises(SystemExit) as exc:
            target_mod.resolve("homelab-observe", inventory)
        assert "no ansible_host" in str(exc.value)

    def test_edge_hostname_skips_live_ip_resolution(self, monkeypatch, tmp_path):
        # homelab-edge is the one node whose IP is never resolved live via
        # Infisical -- it must stay static (Phase 1 bootstraps it before
        # Infisical exists).
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(
            target_mod.subprocess, "run",
            _mock_run_success({"ansible_host": "192.168.1.10", "ansible_port": 22}),
        )

        def _fail_if_called(*a, **k):
            raise AssertionError("_live_ip should not be called for the edge hostname")
        monkeypatch.setattr(target_mod, "_live_ip", _fail_if_called)

        tgt = target_mod.resolve("homelab-edge", inventory)
        assert tgt.host == "192.168.1.10"
        assert tgt.is_local is False

    def test_non_edge_hostname_resolves_via_live_ip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(
            target_mod.subprocess, "run",
            _mock_run_success({"ansible_host": "192.168.1.11", "ansible_port": 22}),
        )
        monkeypatch.setattr(target_mod, "_live_ip", lambda target_node, port: "100.64.0.11")

        tgt = target_mod.resolve("homelab-observe", inventory)
        assert tgt.host == "100.64.0.11"

    def test_ansible_port_template_ref_is_dereferenced(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(
            target_mod.subprocess, "run",
            _mock_run_success({
                "ansible_host": "192.168.1.10",
                "ansible_port": "{{ ssh_port }}",
                "ssh_port": 2255,
            }),
        )

        tgt = target_mod.resolve("homelab-edge", inventory)
        assert tgt.port == 2255

    def test_ssh_key_file_is_expanded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(
            target_mod.subprocess, "run",
            _mock_run_success({
                "ansible_host": "192.168.1.10",
                "ansible_port": 22,
                "ansible_ssh_private_key_file": "~/.ssh/id_ed25519",
            }),
        )

        tgt = target_mod.resolve("homelab-edge", inventory)
        assert tgt.key_file == str(Path("~/.ssh/id_ed25519").expanduser())

    def test_ansible_user_defaults_to_homelab(self, monkeypatch, tmp_path):
        monkeypatch.setattr(target_mod.socket, "gethostname", lambda: "some-other-host")
        inventory = tmp_path / "prod.yml"
        inventory.write_text("placeholder\n")
        monkeypatch.setattr(
            target_mod.subprocess, "run",
            _mock_run_success({"ansible_host": "192.168.1.10", "ansible_port": 22}),
        )

        tgt = target_mod.resolve("homelab-edge", inventory)
        assert tgt.user == "homelab"
