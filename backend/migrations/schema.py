"""Comparing a database's schema with the one a migration expects."""

import sqlite3

Columns = dict[str, tuple[str, int, str | None, int]]

# Tables the runner or SQLite itself owns, left out of every comparison.
OWN_TABLES = ("schema_migrations",)


class SchemaMismatch(Exception):
    """The database's schema is not one this code can safely adopt or upgrade."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(
            "The database schema is not what this version expects: "
            + "; ".join(problems)
            + ". Rebuild it with `uv run -m backend.seed --reset`."
        )
        self.problems = problems


def tables(conn: sqlite3.Connection) -> dict[str, Columns]:
    """Return each table's columns as name -> (type, not null, default, pk)."""
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if r[0] not in OWN_TABLES
    ]
    return {
        name: {
            c[1]: (c[2].upper(), c[3], c[4], c[5])
            for c in conn.execute(f"PRAGMA table_info({name})").fetchall()  # noqa: S608 - names from sqlite_master
        }
        for name in names
    }


def expected(script: str) -> dict[str, Columns]:
    """Return the tables a schema script creates, built in a scratch database."""
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.executescript(script)
        return tables(scratch)
    finally:
        scratch.close()


def differences(actual: dict[str, Columns], want: dict[str, Columns]) -> list[str]:
    """List every way the actual tables differ from the wanted ones."""
    problems = [f"table {t} is missing" for t in want if t not in actual]
    problems += [f"table {t} is not expected" for t in actual if t not in want]
    for table, columns in want.items():
        found = actual.get(table)
        if found is None:
            continue
        for column, shape in columns.items():
            if column not in found:
                problems.append(f"column {table}.{column} is missing")
            elif found[column] != shape:
                problems.append(
                    f"column {table}.{column} is {describe(found[column])},"
                    f" expected {describe(shape)}"
                )
        problems += [
            f"column {table}.{c} is not expected" for c in found if c not in columns
        ]
    return problems


def describe(shape: tuple[str, int, str | None, int]) -> str:
    """Describe a column's type, nullability, default and key for an error."""
    kind, not_null, default, pk = shape
    parts = [kind or "untyped", "NOT NULL" if not_null else "NULL"]
    if default is not None:
        parts.append(f"DEFAULT {default}")
    if pk:
        parts.append("PRIMARY KEY")
    return " ".join(parts)
