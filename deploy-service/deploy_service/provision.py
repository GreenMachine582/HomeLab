"""`requires:` provisioning -- creates per-service Postgres roles/databases
and Redis ACL users on the shared data tier (`homelab-data-services`), the
first time a repo declaring a `requires:` block in services.yml is deployed.

Design constraint (docs/repo_split_brief.md §6.2, CLAUDE.md "Important
Constraints" in the HomeLab repo): every Infisical identity deploy-service
holds is read-only -- no persisted write-capable identity. So this module
never writes to Infisical itself. On first provision it connects directly
to the data tier's Postgres/Redis (as the ADMIN user/password, which
deploy-service already reads read-only from Infisical) and creates the
role/database/ACL user with a freshly generated password -- a database
operation, not an Infisical one -- then hands that value back to the
caller (cli.py), which prints a ready-to-run `infisical secrets set`
command (same "abort, fix, re-run" UX as any other missing declared
secret) for a human to persist it. Once that's done, later deploys just
read it back like any normal secret -- no DB connection needed on that path.

Role/database/ACL-username naming is deterministic from the repo name
(sanitize_name), so only the generated passwords round-trip through
Infisical -- there's nothing else to store or look up.
"""
import re
import secrets as secrets_mod

DATA_REPO_NAME = "homelab-data-services"
ADMIN_USER_PATH = "/prod/data/ADMIN_USER"
ADMIN_PASSWORD_PATH = "/prod/data/ADMIN_PASSWORD"
REDIS_ADMIN_PASSWORD_PATH = "/prod/data/REDIS_ADMIN_PASSWORD"

POSTGRES_PORT = 5432
REDIS_PORT = 6379

_NON_IDENTIFIER = re.compile(r"[^a-z0-9_]+")


def sanitize_name(repo_name: str) -> str:
    """repo name -> a safe Postgres role/database name and Redis ACL
    username -- lowercase, everything but [a-z0-9_] collapsed to
    underscores. 'n8n-automation' -> 'n8n_automation'. The result is safe
    to embed directly in SQL identifiers/Redis ACL patterns -- no quote,
    semicolon, or whitespace character can survive this."""
    name = _NON_IDENTIFIER.sub("_", repo_name.lower()).strip("_")
    if not name:
        raise ValueError(f"repo name {repo_name!r} sanitizes to an empty identifier")
    return name


def requires_secret_specs(repo_name: str, requires_cfg: dict) -> list[dict]:
    """The Infisical secret specs this repo's `requires:` block implies --
    same {path, env} shape check_missing/fetch already understand, so the
    existing pipeline handles them with no special-casing there. Only
    passwords round-trip through Infisical -- role/database/username names
    are deterministic from the repo name (sanitize_name) and injected
    directly by the caller, never stored."""
    specs = []
    if "postgres" in requires_cfg:
        specs.append({
            "path": f"/prod/data/{repo_name}/DB_PASSWORD",
            "env": "PG_PASSWORD",
            "provisioned": True,
        })
    if "redis" in requires_cfg:
        specs.append({
            "path": f"/prod/data/{repo_name}/REDIS_PASSWORD",
            "env": "REDIS_PASSWORD",
            "provisioned": True,
        })
    return specs


def generate_password() -> str:
    return secrets_mod.token_urlsafe(24)


def provision_postgres(host: str, admin_user: str, admin_password: str, database: str, role: str) -> str:
    """Idempotently create/reset `role` (LOGIN) and `database` (owned
    solely by that role) on the data tier. Always resets the password, even
    if the role already existed -- this only runs when Infisical has no
    record of a working password for it (first provision, or recovering
    from a lost/rotated secret), so the DB and Infisical must end up
    agreeing on a fresh value either way. role/database are pre-sanitized
    (sanitize_name) to [a-z0-9_]+, so direct interpolation into a quoted
    SQL identifier below carries no injection risk.
    """
    import psycopg  # lazy: only this rare first-provision path needs it

    password = generate_password()
    conn = psycopg.connect(
        host=host, port=POSTGRES_PORT, dbname="postgres",
        user=admin_user, password=admin_password, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone():
                cur.execute(f'ALTER ROLE "{role}" WITH LOGIN PASSWORD %s', (password,))
            else:
                cur.execute(f'CREATE ROLE "{role}" WITH LOGIN PASSWORD %s', (password,))

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cur.fetchone():
                # Pre-existing DB (e.g. re-provisioning after a lost secret)
                # -- reassert ownership so the one-DB-one-owning-role
                # isolation rule (docs/topology_data_brief.md §4) still holds.
                cur.execute(f'ALTER DATABASE "{database}" OWNER TO "{role}"')
            else:
                cur.execute(f'CREATE DATABASE "{database}" OWNER "{role}"')
    finally:
        conn.close()
    return password


def provision_redis(host: str, admin_password: str, username: str) -> str:
    """Idempotently create/reset a Redis ACL user restricted to keys under
    its own username prefix (docs/topology_data_brief.md §4 -- "ACL users
    with key-prefix restrictions"). Always resets the password, same
    reasoning as provision_postgres above. Returns the freshly generated
    password."""
    import redis  # lazy import, same reasoning as psycopg above

    password = generate_password()
    client = redis.Redis(host=host, port=REDIS_PORT, password=admin_password)
    try:
        client.execute_command(
            "ACL", "SETUSER", username, "reset",
            "on", f">{password}",
            f"~{username}:*", "+@all", "-@dangerous",
        )
    finally:
        client.close()
    return password


def provision_missing(missing_specs: list[dict], repo_name: str, requires_cfg: dict, data_host: str) -> dict[str, str]:
    """For each missing spec implied by `requires_cfg`, provision it live
    against the data tier and return {path: value} for the ones handled
    here. Specs not implied by requires_cfg (e.g. the repo's own unrelated
    declared secrets) are left untouched for the caller to handle normally.
    """
    from . import infisical  # local import avoids a cycle with cli.py's own imports

    implied_paths = {s["path"] for s in requires_secret_specs(repo_name, requires_cfg)}
    to_provision = [s for s in missing_specs if s["path"] in implied_paths]
    if not to_provision:
        return {}

    role = sanitize_name(repo_name)
    result: dict[str, str] = {}

    for spec in to_provision:
        if spec["env"] == "PG_PASSWORD":
            admin = infisical.fetch([
                {"path": ADMIN_USER_PATH, "env": "user"},
                {"path": ADMIN_PASSWORD_PATH, "env": "password"},
            ])
            database = (requires_cfg.get("postgres") or {}).get("database") or role
            result[spec["path"]] = provision_postgres(data_host, admin["user"], admin["password"], database, role)
        elif spec["env"] == "REDIS_PASSWORD":
            redis_admin = infisical.fetch([{"path": REDIS_ADMIN_PASSWORD_PATH, "env": "password"}])
            result[spec["path"]] = provision_redis(data_host, redis_admin["password"], role)

    return result