"""Versioned changes to the database schema, applied in order on startup.

Each migration is a module with a VERSION, a NAME and an upgrade(conn). The
runner records what it applied in schema_migrations, so running it again
changes nothing. All pending migrations run in one transaction: if one fails,
none of them is recorded.
"""

import sqlite3
from types import ModuleType

from backend import clock
from backend.migrations import (
    m0001_baseline,
    m0002_tenancy,
    m0003_auth,
    m0004_tenant_settings,
)
from backend.migrations.schema import SchemaMismatch

__all__ = ["MIGRATIONS", "SchemaMismatch", "applied", "apply", "head"]

MIGRATIONS: list[ModuleType] = [
    m0001_baseline,
    m0002_tenancy,
    m0003_auth,
    m0004_tenant_settings,
]


def applied(conn: sqlite3.Connection) -> list[int]:
    """Return the versions already applied, in order."""
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    return [r[0] for r in rows.fetchall()]


def head() -> int:
    """Return the latest version this code knows."""
    return MIGRATIONS[-1].VERSION


def apply(conn: sqlite3.Connection) -> list[int]:
    """Apply every pending migration and return the versions applied now."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)"
        )
        done = applied(conn)
        newer = [v for v in done if v > head()]
        if newer:
            raise SchemaMismatch(
                [
                    f"it has migration {v}, newer than this code's {head()}"
                    for v in newer
                ]
            )
        now = []
        for migration in MIGRATIONS:
            if migration.VERSION in done:
                continue
            migration.upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at)"
                " VALUES (?, ?, ?)",
                (migration.VERSION, migration.NAME, clock.stamp()),
            )
            now.append(migration.VERSION)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return now
