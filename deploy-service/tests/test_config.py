"""Tests for deploy_service.config — services.yml loading and secrets.yml parsing."""
import pytest

from deploy_service import config


class TestLoadAll:
    def test_returns_repos_dict(self, write_yaml):
        path = write_yaml("services.yml", """
            repos:
              homelab-edge-services:
                repo: github.com/GreenMachine582/homelab-edge-services
                path: /srv/services/homelab-edge-services
        """)
        repos = config.load_all(str(path))
        assert set(repos) == {"homelab-edge-services"}
        assert repos["homelab-edge-services"]["path"] == "/srv/services/homelab-edge-services"

    def test_missing_repos_key_returns_empty_dict(self, write_yaml):
        path = write_yaml("services.yml", "project: homelab\n")
        assert config.load_all(str(path)) == {}

    def test_missing_file_exits(self, tmp_path):
        missing = tmp_path / "nope.yml"
        with pytest.raises(SystemExit) as exc:
            config.load_all(str(missing))
        assert "not found" in str(exc.value)
        assert str(missing) in str(exc.value)

    def test_malformed_yaml_exits(self, write_yaml):
        path = write_yaml("services.yml", "repos: [this is: not, valid: yaml")
        with pytest.raises(SystemExit) as exc:
            config.load_all(str(path))
        assert "parse error" in str(exc.value)


class TestLoad:
    def test_returns_named_entry(self, write_yaml):
        path = write_yaml("services.yml", """
            repos:
              authentik-sso:
                repo: github.com/GreenMachine582/authentik-sso
                path: /srv/services/authentik-sso
              homelab-edge-services:
                repo: github.com/GreenMachine582/homelab-edge-services
                path: /srv/services/homelab-edge-services
        """)
        entry = config.load(str(path), "authentik-sso")
        assert entry["repo"] == "github.com/GreenMachine582/authentik-sso"

    def test_unknown_repo_lists_available(self, write_yaml):
        path = write_yaml("services.yml", """
            repos:
              authentik-sso:
                repo: github.com/GreenMachine582/authentik-sso
        """)
        with pytest.raises(SystemExit) as exc:
            config.load(str(path), "does-not-exist")
        assert "does-not-exist" in str(exc.value)
        assert "authentik-sso" in str(exc.value)

    def test_unknown_repo_with_no_repos_shows_none(self, write_yaml):
        path = write_yaml("services.yml", "repos: {}\n")
        with pytest.raises(SystemExit) as exc:
            config.load(str(path), "anything")
        assert "(none)" in str(exc.value)


class TestParseRepoSecrets:
    def test_none_content_returns_empty(self):
        assert config.parse_repo_secrets(None) == ([], [])

    def test_empty_string_content_returns_empty(self):
        # A secrets.yml that exists but is blank -- real edge case: a repo
        # that genuinely has no secrets shouldn't crash the parser.
        assert config.parse_repo_secrets("") == ([], [])

    def test_secrets_and_addresses_parsed(self):
        content = """
            secrets:
              - path: /prod/cloudflare/TUNNEL_TOKEN
                env: TUNNEL_TOKEN
              - path: /prod/pihole/WEB_PASSWORD
                env: PIHOLE_WEB_PASSWORD
                generate: true
            addresses:
              - homelab-observe-services
              - camunda-platform
        """
        secrets, addresses = config.parse_repo_secrets(content)
        assert secrets == [
            {"path": "/prod/cloudflare/TUNNEL_TOKEN", "env": "TUNNEL_TOKEN"},
            {"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD", "generate": True},
        ]
        assert addresses == ["homelab-observe-services", "camunda-platform"]

    def test_secrets_only_no_addresses_key(self):
        content = "secrets:\n  - path: /prod/authentik/SECRET_KEY\n    env: AUTHENTIK_SECRET_KEY\n"
        secrets, addresses = config.parse_repo_secrets(content)
        assert len(secrets) == 1
        assert addresses == []

    def test_addresses_only_no_secrets_key(self):
        content = "addresses:\n  - homelab-observe-services\n"
        secrets, addresses = config.parse_repo_secrets(content)
        assert secrets == []
        assert addresses == ["homelab-observe-services"]
