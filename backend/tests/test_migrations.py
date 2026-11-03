import sqlite3

import pytest

from backend import db, migrations, seed
from backend.migrations import m0002_tenancy
from backend.migrations.schema import expected, tables

ALL = [m.VERSION for m in migrations.MIGRATIONS]


def legacy(path, script: str = db.SCHEMA) -> None:
    """Make a database the way the harness did, before migrations existed."""
    conn = sqlite3.connect(path)
    conn.executescript(script)
    conn.execute(
        "INSERT INTO claims (claim_id, policy_id, customer_id, data, state,"
        " state_since) VALUES ('CLM-0001', 'POL-0001', 'CUS-0001', '{}',"
        " 'waiting', '2026-11-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def empty(tmp_path, monkeypatch):
    """Point DB_PATH at a database file that does not exist yet."""
    path = tmp_path / "fresh.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return path


def recorded(path) -> list[int] | None:
    """Return the versions recorded, or None if there is no record at all."""
    conn = sqlite3.connect(path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        if "schema_migrations" not in names:
            return None
        return [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    finally:
        conn.close()


def test_a_fresh_database_reaches_the_head_version():
    with db.connect() as conn:
        assert migrations.applied(conn) == ALL
        assert ALL[-1] == migrations.head() == 4
        found = tables(conn)
    baseline = expected(db.SCHEMA)
    for table, columns in baseline.items():
        assert set(columns) <= set(found[table]), table
    for table in m0002_tenancy.TABLES:
        assert found[table]["tenant_id"][:2] == ("TEXT", 1), table
    assert {"tenants", "users", "sessions", "service_tokens"} <= set(found)


def test_applying_again_changes_nothing():
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        assert migrations.apply(conn) == []
        assert migrations.applied(conn) == ALL
    seed.seed()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == before


def test_a_complete_harness_database_is_adopted_with_its_data(empty):
    legacy(empty)
    seed.seed()
    assert recorded(empty) == ALL
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT claim_id, tenant_id FROM claims WHERE tenant_id = 'T-UNDERCOVER'"
        ).fetchall()
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert [tuple(r) for r in rows] == [("CLM-0001", "T-UNDERCOVER")]
    assert users == 11


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            (
                "sections TEXT NOT NULL, run_id TEXT NOT NULL",
                "run_id TEXT NOT NULL",
            ),
            "column decisions.sections is missing",
        ),
        (
            ("failed_attempts INTEGER NOT NULL DEFAULT 0", "failed_attempts TEXT"),
            "column claims.failed_attempts is TEXT NULL, expected INTEGER NOT NULL"
            " DEFAULT 0",
        ),
        (
            (
                "CREATE TABLE IF NOT EXISTS voice_turns",
                "CREATE TABLE IF NOT EXISTS old",
            ),
            "table voice_turns is missing",
        ),
        (
            ("model TEXT NOT NULL);", "model TEXT NOT NULL, extra TEXT);"),
            "column runs.extra is not expected",
        ),
    ],
)
def test_an_incompatible_database_is_refused_and_left_alone(empty, change, problem):
    old, new = change
    script = db.SCHEMA.replace(old, new, 1)
    assert script != db.SCHEMA
    legacy(empty, script)
    with pytest.raises(migrations.SchemaMismatch) as refused:
        seed.seed()
    assert problem in refused.value.problems
    assert "--reset" in str(refused.value)
    assert recorded(empty) is None


def test_an_unexpected_table_is_refused(empty):
    legacy(empty, db.SCHEMA + "CREATE TABLE stray (id INTEGER);")
    with pytest.raises(migrations.SchemaMismatch) as refused:
        seed.seed()
    assert refused.value.problems == ["table stray is not expected"]
    assert recorded(empty) is None


def test_a_database_from_newer_code_is_refused(empty):
    seed.seed()
    conn = sqlite3.connect(empty)
    conn.execute(
        "INSERT INTO schema_migrations VALUES (?, 'future', '2027-01-01T00:00:00')",
        (migrations.head() + 1,),
    )
    conn.commit()
    conn.close()
    with pytest.raises(migrations.SchemaMismatch, match="newer than this code"):
        seed.seed()


def test_reset_rebuilds_a_refused_database(empty):
    legacy(empty, db.SCHEMA.replace("model TEXT NOT NULL);", "model TEXT);", 1))
    with pytest.raises(migrations.SchemaMismatch):
        seed.seed()
    seed.seed(reset=True)
    assert recorded(empty) == ALL
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM claims WHERE tenant_id = 'T-UNDERCOVER'"
            ).fetchone()[0]
            == 35
        )
