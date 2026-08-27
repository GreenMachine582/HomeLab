"""Tests for deploy_service.infisical -- Infisical secret lookup.

_fetch_secret's path-parsing gets the heaviest coverage here: it's the
single place a naming-convention drift (e.g. a stray `/production/` segment
where every consumer actually expects `/prod/`) would silently misroute a
lookup instead of failing loudly.
"""
import json
import subprocess
import urllib.error
import urllib.parse
from types import SimpleNamespace

import pytest
import yaml

from deploy_service import infisical


class TestHttp:
    def test_returns_parsed_json_on_success(self, monkeypatch):
        class _FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *exc_info):
                return False
            def read(self):
                return json.dumps({"ok": True}).encode()

        monkeypatch.setattr(infisical.urllib.request, "urlopen", lambda req, timeout=10: _FakeResponse())
        assert infisical._http("GET", "http://x/y") == {"ok": True}

    def test_404_when_not_required_returns_none(self, monkeypatch):
        def _raise(req, timeout=10):
            raise urllib.error.HTTPError("http://x/y", 404, "not found", {}, None)
        monkeypatch.setattr(infisical.urllib.request, "urlopen", _raise)
        assert infisical._http("GET", "http://x/y", required=False) is None

    def test_non_404_http_error_exits(self, monkeypatch):
        import io
        def _raise(req, timeout=10):
            raise urllib.error.HTTPError("http://x/y", 500, "server error", {}, io.BytesIO(b"boom"))
        monkeypatch.setattr(infisical.urllib.request, "urlopen", _raise)
        with pytest.raises(SystemExit) as exc:
            infisical._http("GET", "http://x/y")
        assert "500" in str(exc.value)
        assert "boom" in str(exc.value)

    def test_url_error_exits(self, monkeypatch):
        def _raise(req, timeout=10):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr(infisical.urllib.request, "urlopen", _raise)
        with pytest.raises(SystemExit) as exc:
            infisical._http("GET", "http://x/y")
        assert "Cannot reach Infisical" in str(exc.value)


class TestFetchSecretPathParsing:
    def _http_recorder(self, monkeypatch, secret_value="the-value"):
        calls = []

        def _fake_http(method, url, body=None, token=None, required=True):
            calls.append({"method": method, "url": url, "token": token, "required": required})
            return {"secret": {"secretValue": secret_value}}

        monkeypatch.setattr(infisical, "_http", _fake_http)
        return calls

    def _query_params(self, url: str) -> dict:
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}

    def test_simple_path_splits_env_folder_key(self, monkeypatch):
        calls = self._http_recorder(monkeypatch)
        infisical._fetch_secret("tok", "/prod/camunda/DB_PASSWORD", "proj-1")

        assert len(calls) == 1
        assert calls[0]["url"].split("?")[0].endswith("/v3/secrets/raw/DB_PASSWORD")
        params = self._query_params(calls[0]["url"])
        assert params == {"workspaceId": "proj-1", "environment": "prod", "secretPath": "/camunda"}

    def test_multi_segment_folder_joined_correctly(self, monkeypatch):
        calls = self._http_recorder(monkeypatch)
        infisical._fetch_secret("tok", "/prod/discord/webhooks/CRITICAL", "proj-1")

        params = self._query_params(calls[0]["url"])
        assert params["secretPath"] == "/discord/webhooks"
        assert params["environment"] == "prod"

    def test_environment_segment_is_whatever_the_path_says(self, monkeypatch):
        # infisical_seed_environment is "prod" everywhere in this repo today,
        # but _fetch_secret itself must not hardcode that -- it should
        # faithfully reflect whatever the caller's path says, so a caller
        # that's out of sync (e.g. still saying /production/) fails loudly
        # against the real API instead of being silently rewritten here.
        calls = self._http_recorder(monkeypatch)
        infisical._fetch_secret("tok", "/production/camunda/DB_PASSWORD", "proj-1")
        assert self._query_params(calls[0]["url"])["environment"] == "production"

    def test_too_few_parts_exits(self):
        with pytest.raises(SystemExit) as exc:
            infisical._fetch_secret("tok", "/prod/ONLY_TWO_PARTS", "proj-1")
        assert "Invalid secret path" in str(exc.value)

    def test_missing_required_value_exits(self, monkeypatch):
        monkeypatch.setattr(infisical, "_http", lambda *a, **k: {"secret": {}})
        with pytest.raises(SystemExit) as exc:
            infisical._fetch_secret("tok", "/prod/camunda/DB_PASSWORD", "proj-1", required=True)
        assert "Secret not found or empty" in str(exc.value)

    def test_missing_optional_value_returns_none(self, monkeypatch):
        monkeypatch.setattr(infisical, "_http", lambda *a, **k: None)
        assert infisical._fetch_secret("tok", "/prod/camunda/DB_PASSWORD", "proj-1", required=False) is None


class TestCheckMissing:
    def test_empty_specs_short_circuits(self, monkeypatch):
        def _fail(*a, **k):
            raise AssertionError("should not load runtime creds for an empty spec list")
        monkeypatch.setattr(infisical, "_load_runtime_creds", _fail)
        assert infisical.check_missing([]) == []

    def test_returns_only_the_missing_ones(self, monkeypatch):
        monkeypatch.setattr(infisical, "_load_runtime_creds", lambda: ("id", "secret", "proj-1"))
        monkeypatch.setattr(infisical, "_login", lambda cid, csec: "tok")

        present = {"path": "/prod/cloudflare/TUNNEL_TOKEN", "env": "TUNNEL_TOKEN"}
        missing = {"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD"}

        def _fake_fetch(token, path, project_id, required=True):
            return "some-value" if path == present["path"] else None

        monkeypatch.setattr(infisical, "_fetch_secret", _fake_fetch)

        result = infisical.check_missing([present, missing])
        assert result == [missing]


class TestFetch:
    def test_empty_specs_returns_empty_dict(self, monkeypatch):
        def _fail(*a, **k):
            raise AssertionError("should not load runtime creds for an empty spec list")
        monkeypatch.setattr(infisical, "_load_runtime_creds", _fail)
        assert infisical.fetch([]) == {}

    def test_builds_env_var_mapping(self, monkeypatch):
        monkeypatch.setattr(infisical, "_load_runtime_creds", lambda: ("id", "secret", "proj-1"))
        monkeypatch.setattr(infisical, "_login", lambda cid, csec: "tok")
        monkeypatch.setattr(infisical, "_fetch_secret", lambda token, path, project_id, required=True: f"value-for-{path}")

        specs = [
            {"path": "/prod/cloudflare/TUNNEL_TOKEN", "env": "TUNNEL_TOKEN"},
            {"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD"},
        ]
        result = infisical.fetch(specs)
        assert result == {
            "TUNNEL_TOKEN": "value-for-/prod/cloudflare/TUNNEL_TOKEN",
            "PIHOLE_WEB_PASSWORD": "value-for-/prod/pihole/WEB_PASSWORD",
        }


class TestFetchOptional:
    def test_always_calls_fetch_secret_as_not_required(self, monkeypatch):
        monkeypatch.setattr(infisical, "_load_runtime_creds", lambda: ("id", "secret", "proj-1"))
        monkeypatch.setattr(infisical, "_login", lambda cid, csec: "tok")

        captured = {}
        def _fake_fetch(token, path, project_id, required=True):
            captured["required"] = required
            return "the-value"
        monkeypatch.setattr(infisical, "_fetch_secret", _fake_fetch)

        assert infisical.fetch_optional("/prod/discord/ALERTS_WEBHOOK") == "the-value"
        assert captured["required"] is False


class TestLoadRuntimeCreds:
    def test_missing_file_exits_with_hint_for_non_homelab_user(self, monkeypatch, tmp_path):
        monkeypatch.setattr(infisical, "_RUNTIME_AUTH_PATH", tmp_path / "missing.yml")
        monkeypatch.setattr(infisical.getpass, "getuser", lambda: "Chad")

        with pytest.raises(SystemExit) as exc:
            infisical._load_runtime_creds()
        msg = str(exc.value)
        assert "Runtime credentials not found" in msg
        assert "sudo su - homelab" in msg

    def test_missing_file_omits_hint_for_homelab_user(self, monkeypatch, tmp_path):
        monkeypatch.setattr(infisical, "_RUNTIME_AUTH_PATH", tmp_path / "missing.yml")
        monkeypatch.setattr(infisical.getpass, "getuser", lambda: "homelab")

        with pytest.raises(SystemExit) as exc:
            infisical._load_runtime_creds()
        assert "sudo su - homelab" not in str(exc.value)

    def test_missing_client_fields_exits(self, monkeypatch, tmp_path):
        path = tmp_path / "auth.yml"
        path.write_text(yaml.dump({"infisical_runtime_project_id": "proj-1"}))
        monkeypatch.setattr(infisical, "_RUNTIME_AUTH_PATH", path)

        with pytest.raises(SystemExit) as exc:
            infisical._load_runtime_creds()
        assert "Missing client_id or client_secret" in str(exc.value)

    def test_missing_project_id_exits(self, monkeypatch, tmp_path):
        path = tmp_path / "auth.yml"
        path.write_text(yaml.dump({
            "infisical_runtime_client_id": "cid",
            "infisical_runtime_client_secret": "csec",
        }))
        monkeypatch.setattr(infisical, "_RUNTIME_AUTH_PATH", path)

        with pytest.raises(SystemExit) as exc:
            infisical._load_runtime_creds()
        assert "re-run Phase 1 bootstrap" in str(exc.value)

    def test_complete_file_returns_tuple(self, monkeypatch, tmp_path):
        path = tmp_path / "auth.yml"
        path.write_text(yaml.dump({
            "infisical_runtime_client_id": "cid",
            "infisical_runtime_client_secret": "csec",
            "infisical_runtime_project_id": "proj-1",
        }))
        monkeypatch.setattr(infisical, "_RUNTIME_AUTH_PATH", path)

        assert infisical._load_runtime_creds() == ("cid", "csec", "proj-1")


class TestLogin:
    def test_returns_access_token(self, monkeypatch):
        monkeypatch.setattr(infisical, "_http", lambda *a, **k: {"accessToken": "tok-123"})
        assert infisical._login("cid", "csec") == "tok-123"

    def test_missing_token_exits(self, monkeypatch):
        monkeypatch.setattr(infisical, "_http", lambda *a, **k: {})
        with pytest.raises(SystemExit) as exc:
            infisical._login("cid", "csec")
        assert "no accessToken" in str(exc.value)


class TestResolveUiBaseUrl:
    def test_uses_live_tailscale_dns_name(self, monkeypatch):
        monkeypatch.setattr(
            infisical.subprocess, "run",
            lambda *a, **k: SimpleNamespace(stdout=json.dumps({"Self": {"DNSName": "homelab-edge.tailnet.ts.net."}})),
        )
        assert infisical._resolve_ui_base_url(8443) == "https://homelab-edge.tailnet.ts.net:8443"

    def test_falls_back_when_tailscale_unreachable(self, monkeypatch):
        def _raise(*a, **k):
            raise subprocess.SubprocessError("tailscale not running")
        monkeypatch.setattr(infisical.subprocess, "run", _raise)
        assert infisical._resolve_ui_base_url(8443) == "https://homelab-edge.<tailnet>.ts.net:8443"


class TestFormatRemediation:
    def test_groups_by_env_and_folder_with_generate_annotations(self, monkeypatch):
        monkeypatch.setattr(infisical, "_resolve_ui_base_url", lambda: "https://homelab-edge.tailnet.ts.net:8443")
        monkeypatch.setattr(infisical, "_load_runtime_creds", lambda: ("id", "secret", "proj-1"))

        missing = [
            {"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD", "generate": True},
            {"path": "/prod/cloudflare/TUNNEL_TOKEN", "env": "TUNNEL_TOKEN"},
        ]
        lines = infisical.format_remediation(missing)
        text = "\n".join(lines)

        assert "https://homelab-edge.tailnet.ts.net:8443" in text
        assert "WEB_PASSWORD" in text and "(generate a random value)" in text
        assert 'infisical secrets set WEB_PASSWORD="$(openssl rand -hex 16)" --path="/pihole" --env=prod --projectId proj-1' in text
        assert 'infisical secrets set TUNNEL_TOKEN="<FILL_ME_IN>" --path="/cloudflare" --env=prod --projectId proj-1' in text

    def test_never_prints_a_real_secret_value(self, monkeypatch):
        # generate:true entries must never have a concrete value embedded --
        # only the shell substitution that computes one at paste-time.
        monkeypatch.setattr(infisical, "_resolve_ui_base_url", lambda: "https://homelab-edge.tailnet.ts.net:8443")
        monkeypatch.setattr(infisical, "_load_runtime_creds", lambda: ("id", "secret", "proj-1"))

        lines = infisical.format_remediation([{"path": "/prod/pihole/WEB_PASSWORD", "env": "PIHOLE_WEB_PASSWORD", "generate": True}])
        assert not any("secretValue" in line for line in lines)
