"""An insertion order on claim runs and queue runs.

Runs started in the same second were ordered by SQLite's rowid, which
PostgreSQL does not have. seq is set from the highest seq so far on every
insert. On SQLite, runs that are already there take their rowid.
"""

from backend import db

VERSION = 5
NAME = "run_order"


def upgrade(conn: db.Connection) -> None:
    """Add seq to runs and queue_runs, numbering any existing runs in order."""
    for table in ("runs", "queue_runs"):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")  # noqa: S608 - fixed names
        if conn.dialect == "sqlite":
            conn.execute(f"UPDATE {table} SET seq = rowid")  # noqa: S608 - fixed names
