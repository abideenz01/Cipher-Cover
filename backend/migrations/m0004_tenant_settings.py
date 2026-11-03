"""Per-tenant settings and a sign-in throttle that survives a restart.

tenant_reference holds a tenant's own copy of a reference document, such as
its company settings. A tenant without one uses the shared reference table.
login_failures records failed sign-ins, so the throttle is kept in the
database rather than in one process's memory.
"""

import sqlite3

VERSION = 4
NAME = "tenant_settings"

SCHEMA = """
CREATE TABLE tenant_reference (
    tenant_id TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, name));
CREATE TABLE login_failures (
    id INTEGER PRIMARY KEY, key TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX login_failures_key ON login_failures (key, created_at);
"""


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the tenant settings and sign-in failure tables."""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
