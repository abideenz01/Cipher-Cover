"""Tenancy: a tenants table and a tenant_id on every business table.

This is application-level isolation for development and pilots. It is not the
production guarantee: that needs PostgreSQL row-level security, see
docs/ADR_POSTGRES.md.

SQLite can only add a NOT NULL column with a default, so existing rows, and any
insert that forgets the column, land in the first tenant. Every insert in the
code names tenant_id, and backend/tests/test_tenancy.py checks that a second
tenant's rows keep its own tenant_id.
"""

import json
import sqlite3

VERSION = 2
NAME = "tenancy"
FIRST_TENANT = "T-UNDERCOVER"
TABLES = (
    "customers",
    "policies",
    "handlers",
    "claims",
    "calculations",
    "decisions",
    "payments",
    "signoffs",
    "sendbacks",
    "runs",
    "queue_runs",
    "section_reads",
    "run_events",
    "signoff_requests",
    "voice_turns",
)


def upgrade(conn: sqlite3.Connection) -> None:
    """Add the tenants table, the first tenant and a tenant_id everywhere."""
    conn.execute(
        "CREATE TABLE tenants (tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
        " timezone TEXT NOT NULL, config TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tenants VALUES (?, ?, ?, ?)",
        (
            FIRST_TENANT,
            "UnderCover Travel Insurance",
            "UTC",
            json.dumps({"external_model_medical": False}),
        ),
    )
    for table in TABLES:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL"  # noqa: S608 - fixed names
            f" DEFAULT '{FIRST_TENANT}'"
        )
        conn.execute(f"CREATE INDEX {table}_tenant ON {table} (tenant_id)")
