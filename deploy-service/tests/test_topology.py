"""Tests for deploy_service.topology — topology.yml loading and hostname resolution."""
import pytest

from deploy_service import topology


class TestLoad:
    def test_returns_parsed_data(self, write_yaml):
        path = write_yaml("topology.yml", """
            devices:
              rpi-01:
                hostname: homelab-edge
        """)
        data = topology.load(str(path))
        assert data["devices"]["rpi-01"]["hostname"] == "homelab-edge"

    def test_missing_file_exits(self, tmp_path):
        missing = tmp_path / "nope.yml"
        with pytest.raises(SystemExit) as exc:
            topology.load(str(missing))
        assert "not found" in str(exc.value)

    def test_malformed_yaml_exits(self, write_yaml):
        path = write_yaml("topology.yml", "devices: [unterminated")
        with pytest.raises(SystemExit) as exc:
            topology.load(str(path))
        assert "parse error" in str(exc.value)


class TestResolveHostname:
    TOPOLOGY = {
        "devices": {
            "rpi-01": {"hostname": "homelab-edge"},
            "rpi-02": {"hostname": "homelab-observe"},
            "pc-01": {},  # device declared but hostname not set yet
        }
    }

    def test_resolves_known_device(self):
        assert topology.resolve_hostname("rpi-02", self.TOPOLOGY) == "homelab-observe"

    def test_unknown_device_lists_available(self):
        with pytest.raises(SystemExit) as exc:
            topology.resolve_hostname("rpi-99", self.TOPOLOGY)
        assert "rpi-99" in str(exc.value)
        assert "rpi-01" in str(exc.value)

    def test_device_with_no_hostname_exits(self):
        with pytest.raises(SystemExit) as exc:
            topology.resolve_hostname("pc-01", self.TOPOLOGY)
        assert "no hostname" in str(exc.value)


class TestHostnameForRepo:
    TOPOLOGY = {"devices": {"rpi-02": {"hostname": "homelab-observe"}}}
    ALL_REPOS = {
        "homelab-observe-services": {"device": "rpi-02"},
        "camunda-platform": {},  # registered but no device: binding yet
    }

    def test_resolves_via_repos_device_binding(self):
        hostname = topology.hostname_for_repo("homelab-observe-services", self.ALL_REPOS, self.TOPOLOGY)
        assert hostname == "homelab-observe"

    def test_unknown_repo_exits(self):
        with pytest.raises(SystemExit) as exc:
            topology.hostname_for_repo("does-not-exist", self.ALL_REPOS, self.TOPOLOGY)
        assert "does-not-exist" in str(exc.value)

    def test_repo_with_no_device_binding_exits(self):
        with pytest.raises(SystemExit) as exc:
            topology.hostname_for_repo("camunda-platform", self.ALL_REPOS, self.TOPOLOGY)
        assert "no device" in str(exc.value)


class TestAddrEnvName:
    @pytest.mark.parametrize(
        "repo_name, expected",
        [
            ("homelab-observe-services", "ADDR_OBSERVE_SERVICES"),
            ("camunda-platform", "ADDR_CAMUNDA_PLATFORM"),
            ("homelab-edge-services", "ADDR_EDGE_SERVICES"),
            ("n8n-automation", "ADDR_N8N_AUTOMATION"),
        ],
    )
    def test_matches_docstring_examples(self, repo_name, expected):
        assert topology.addr_env_name(repo_name) == expected
