"""Row-level security on PostgreSQL, so a query that forgets its tenant filter
still returns only the caller's rows. Nothing changes on SQLite.

The application role, undercover_app, owns nothing and cannot bypass RLS. The
owner (the role the migrations run as) becomes a member so it can take the
role for a transaction, which db.connect() does for every signed-in request,
together with the request's tenant in app.tenant_id. Every tenant table gets
a policy that reads and writes only that tenant's rows, and tenant_id loses
its default, so an insert that forgets the tenant fails.

The tenant filters in the code stay: RLS is the second layer, not the only one.
See docs/ADR_POSTGRES.md.
"""

from backend import db
from backend.migrations import m0002_tenancy

VERSION = 6
NAME = "rls"

TENANT_TABLES = (
    *m0002_tenancy.TABLES,
    "tenants",
    "tenant_reference",
    "users",
    "sessions",
    "service_tokens",
    "security_events",
)
POLICY = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade(conn: db.Connection) -> None:
    """Create the application role, grant it the tables, and turn on RLS."""
    if conn.dialect != "postgresql":
        return
    schema, role = db.schema(), db.APP_ROLE
    conn.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname ="  # noqa: S608 - a fixed role name
        f" '{role}') THEN CREATE ROLE {role} NOLOGIN NOBYPASSRLS; END IF; END $$"
    )
    conn.execute(f"GRANT {role} TO current_user")
    conn.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
    grants = (
        ("SELECT, INSERT, UPDATE, DELETE", "TABLES"),
        ("USAGE, SELECT", "SEQUENCES"),
    )
    for privileges, kind in grants:
        conn.execute(f"GRANT {privileges} ON ALL {kind} IN SCHEMA {schema} TO {role}")
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}"
            f" GRANT {privileges} ON {kind} TO {role}"
        )
    for table in TENANT_TABLES:
        if table != "tenants":
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN tenant_id DROP DEFAULT")
        protect(conn, table, POLICY)
    # A role belongs to the tenant of its user.
    protect(
        conn,
        "user_roles",
        "EXISTS (SELECT 1 FROM users WHERE users.user_id = user_roles.user_id)",
    )


def protect(conn: db.Connection, table: str, rule: str) -> None:
    """Turn on and force RLS on a table, with one policy for reads and writes."""
    conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    conn.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})"
    )
