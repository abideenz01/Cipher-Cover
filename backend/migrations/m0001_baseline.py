"""The schema as the agent harness left it.

On an empty database this creates every table. On a database made before
migrations existed, it checks that every table and column is exactly what the
harness made and only then records itself as applied. Anything missing,
extra or different is refused, never accepted silently.
"""

from backend import db
from backend.migrations.schema import SchemaMismatch, differences, expected, tables

VERSION = 1
NAME = "baseline"


def upgrade(conn: db.Connection) -> None:
    """Create the harness schema, or adopt an existing one that matches it."""
    actual = tables(conn)
    if not actual:
        for statement in db.SCHEMA.split(";"):
            if statement.strip():
                conn.execute(db.ddl(statement, conn.dialect))
        return
    if conn.dialect == "postgresql":
        raise SchemaMismatch([f"tables {', '.join(actual)} exist with no migrations"])
    problems = differences(actual, expected(db.SCHEMA))
    if problems:
        raise SchemaMismatch(problems)
