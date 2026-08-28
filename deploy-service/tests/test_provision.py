"""Tests for deploy_service.provision -- requires: provisioning.

Real database drivers (psycopg, redis) are never installed for this test
suite -- provision_postgres/provision_redis do a lazy `import psycopg` /
`import redis` specifically so tests can pre-populate sys.modules with a
fake module and never need the real package installed.
"""
import sys

import pytest

from deploy_service import provision


class TestSanitizeName:
    def test_hyphens_become_underscores(self):
        assert provision.sanitize_name("n8n-automation") == "n8n_automation"

    def test_lowercases(self):
        assert provision.sanitize_name("GreenTechHub") == "greentechhub"

    def test_strips_leading_trailing_underscores(self):
        assert provision.sanitize_name("-weird-name-") == "weird_name"

    def test_collapses_runs_of_non_identifier_chars(self):
        assert provision.sanitize_name("foo!!bar") == "foo_bar"

    def test_all_symbols_raises(self):
        with pytest.raises(ValueError, match="empty identifier"):
            provision.sanitize_name("---")


class TestRequiresSecretSpecs:
    def test_postgres_only(self):
        specs = provision.requires_secret_specs("n8n-automation", {"postgres": {"database": "n8n"}})
        assert specs == [{
            "path": "/prod/data/n8n-automation/DB_PASSWORD",
            "env": "PG_PASSWORD",
            "provisioned": True,
        }]

    def test_redis_only(self):
        specs = provision.requires_secret_specs("bottlebot", {"redis": {}})
        assert specs == [{
            "path": "/prod/data/bottlebot/REDIS_PASSWORD",
            "env": "REDIS_PASSWORD",
            "provisioned": True,
        }]

    def test_both(self):
        specs = provision.requires_secret_specs("authentik-sso", {"postgres": {}, "redis": {}})
        paths = {s["path"] for s in specs}
        assert paths == {
            "/prod/data/authentik-sso/DB_PASSWORD",
            "/prod/data/authentik-sso/REDIS_PASSWORD",
        }

    def test_neither_returns_empty(self):
        assert provision.requires_secret_specs("some-repo", {}) == []


class _FakeCursor:
    def __init__(self, existing_roles: set, existing_dbs: set):
        self.existing_roles = existing_roles
        self.existing_dbs = existing_dbs
        self.executed: list[tuple] = []
        self._last_query_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.startswith("SELECT 1 FROM pg_roles"):
            self._last_query_result = (1,) if params[0] in self.existing_roles else None
        elif query.startswith("SELECT 1 FROM pg_database"):
            self._last_query_result = (1,) if params[0] in self.existing_dbs else None
        else:
            self._last_query_result = None

    def fetchone(self):
        return self._last_query_result


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class TestProvisionPostgres:
    def _install_fake_psycopg(self, monkeypatch, cursor: _FakeCursor, captured_connect: dict):
        fake_conn = _FakeConnection(cursor)

        def _fake_connect(**kwargs):
            captured_connect.update(kwargs)
            return fake_conn

        fake_module = type(sys)("psycopg")
        fake_module.connect = _fake_connect
        monkeypatch.setitem(sys.modules, "psycopg", fake_module)
        return fake_conn

    def test_creates_role_and_database_when_absent(self, monkeypatch):
        cursor = _FakeCursor(existing_roles=set(), existing_dbs=set())
        captured_connect: dict = {}
        conn = self._install_fake_psycopg(monkeypatch, cursor, captured_connect)

        password = provision.provision_postgres("10.0.0.5", "admin", "adminpw", "n8n", "n8n_automation")

        assert isinstance(password, str) and len(password) > 10
        queries = [q for q, _ in cursor.executed]
        assert any(q.startswith('CREATE ROLE "n8n_automation"') for q in queries)
        assert any(q.startswith('CREATE DATABASE "n8n" OWNER "n8n_automation"') for q in queries)
        assert not any(q.startswith("ALTER ROLE") for q in queries)
        assert conn.closed is True
        assert captured_connect["host"] == "10.0.0.5"
        assert captured_connect["port"] == provision.POSTGRES_PORT
        assert captured_connect["user"] == "admin"
        assert captured_connect["autocommit"] is True

    def test_resets_password_and_reasserts_ownership_when_already_exists(self, monkeypatch):
        cursor = _FakeCursor(existing_roles={"n8n_automation"}, existing_dbs={"n8n"})
        self._install_fake_psycopg(monkeypatch, cursor, {})

        provision.provision_postgres("10.0.0.5", "admin", "adminpw", "n8n", "n8n_automation")

        queries = [q for q, _ in cursor.executed]
        assert any(q.startswith('ALTER ROLE "n8n_automation" WITH LOGIN PASSWORD') for q in queries)
        assert any(q.startswith('ALTER DATABASE "n8n" OWNER TO "n8n_automation"') for q in queries)
        assert not any(q.startswith("CREATE ROLE") for q in queries)
        assert not any(q.startswith("CREATE DATABASE") for q in queries)

    def test_password_differs_between_calls(self, monkeypatch):
        cursor1 = _FakeCursor(existing_roles=set(), existing_dbs=set())
        self._install_fake_psycopg(monkeypatch, cursor1, {})
        p1 = provision.provision_postgres("h", "u", "p", "db1", "role1")

        cursor2 = _FakeCursor(existing_roles=set(), existing_dbs=set())
        self._install_fake_psycopg(monkeypatch, cursor2, {})
        p2 = provision.provision_postgres("h", "u", "p", "db2", "role2")

        assert p1 != p2


class _FakeRedisClient:
    def __init__(self):
        self.commands: list[tuple] = []
        self.closed = False

    def execute_command(self, *args):
        self.commands.append(args)

    def close(self):
        self.closed = True


class TestProvisionRedis:
    def _install_fake_redis(self, monkeypatch):
        client = _FakeRedisClient()
        fake_module = type(sys)("redis")
        fake_module.Redis = lambda **kwargs: client
        monkeypatch.setitem(sys.modules, "redis", fake_module)
        return client

    def test_sets_acl_user_scoped_to_own_prefix(self, monkeypatch):
        client = self._install_fake_redis(monkeypatch)

        password = provision.provision_redis("10.0.0.5", "adminpw", "n8n_automation")

        assert isinstance(password, str) and len(password) > 10
        assert len(client.commands) == 1
        cmd = client.commands[0]
        assert cmd[:3] == ("ACL", "SETUSER", "n8n_automation")
        assert "on" in cmd
        assert f">{password}" in cmd
        assert "~n8n_automation:*" in cmd
        assert client.closed is True


class TestProvisionMissing:
    def test_ignores_specs_not_implied_by_requires(self, monkeypatch):
        unrelated = {"path": "/prod/n8n/OWNER_EMAIL", "env": "N8N_OWNER_EMAIL"}
        result = provision.provision_missing([unrelated], "n8n-automation", {}, "10.0.0.5")
        assert result == {}

    def test_provisions_postgres_only(self, monkeypatch):
        pg_spec = {"path": "/prod/data/n8n-automation/DB_PASSWORD", "env": "PG_PASSWORD", "provisioned": True}

        fetch_calls = []

        def _fake_fetch(specs):
            fetch_calls.append(specs)
            return {"user": "admin", "password": "adminpw"}
        monkeypatch.setattr("deploy_service.infisical.fetch", _fake_fetch)

        captured = {}

        def _fake_provision_postgres(host, admin_user, admin_password, database, role):
            captured.update(host=host, admin_user=admin_user, admin_password=admin_password,
                             database=database, role=role)
            return "generated-pw"
        monkeypatch.setattr(provision, "provision_postgres", _fake_provision_postgres)

        result = provision.provision_missing(
            [pg_spec], "n8n-automation", {"postgres": {"database": "n8n"}}, "10.0.0.5",
        )

        assert result == {"/prod/data/n8n-automation/DB_PASSWORD": "generated-pw"}
        assert captured == {
            "host": "10.0.0.5", "admin_user": "admin", "admin_password": "adminpw",
            "database": "n8n", "role": "n8n_automation",
        }
        assert fetch_calls[0] == [
            {"path": provision.ADMIN_USER_PATH, "env": "user"},
            {"path": provision.ADMIN_PASSWORD_PATH, "env": "password"},
        ]

    def test_postgres_database_defaults_to_sanitized_repo_name(self, monkeypatch):
        pg_spec = {"path": "/prod/data/bottlebot/DB_PASSWORD", "env": "PG_PASSWORD", "provisioned": True}
        monkeypatch.setattr("deploy_service.infisical.fetch", lambda specs: {"user": "a", "password": "p"})

        captured = {}

        def _fake_provision_postgres(host, admin_user, admin_password, database, role):
            captured["database"] = database
            return "pw"
        monkeypatch.setattr(provision, "provision_postgres", _fake_provision_postgres)

        provision.provision_missing([pg_spec], "bottlebot", {"postgres": {}}, "10.0.0.5")
        assert captured["database"] == "bottlebot"

    def test_provisions_redis_only(self, monkeypatch):
        redis_spec = {"path": "/prod/data/bottlebot/REDIS_PASSWORD", "env": "REDIS_PASSWORD", "provisioned": True}
        monkeypatch.setattr("deploy_service.infisical.fetch", lambda specs: {"password": "redisadminpw"})

        captured = {}

        def _fake_provision_redis(host, admin_password, username):
            captured["call"] = (host, admin_password, username)
            return "pw"
        monkeypatch.setattr(provision, "provision_redis", _fake_provision_redis)

        result = provision.provision_missing([redis_spec], "bottlebot", {"redis": {}}, "10.0.0.5")

        assert result == {"/prod/data/bottlebot/REDIS_PASSWORD": "pw"}
        assert captured["call"] == ("10.0.0.5", "redisadminpw", "bottlebot")