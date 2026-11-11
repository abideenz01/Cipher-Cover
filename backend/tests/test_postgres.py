"""Row-level security on PostgreSQL. Opt-in: these run only with TEST_DATABASE_URL.

    TEST_DATABASE_URL=postgresql://... uv run pytest -m postgres --no-cov

They build the whole schema in undercover_test, never in undercover, and drop
it at the end.
"""

import os
from contextlib import nullcontext

import pytest
from sqlalchemy import exc

from agent import main, tracing
from backend import auth, db, runs, seed
from backend.tests import sessions, tenants

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
    ),
]

ACME_CLAIMS = 10
ALL_CLAIMS = 45


@pytest.fixture(scope="module", autouse=True)
def postgres():
    """Seed the undercover_test schema once for the module, then drop it."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
        patch.setenv("DATABASE_SCHEMA", "undercover_test")
        patch.setenv("DEMO_PASSWORD", sessions.PASSWORD)
        patch.setenv("AGENT_STUB", "1")
        patch.setattr(auth, "SCRYPT_N", 2**4)
        for key in tracing.KEYS:
            patch.delenv(key, raising=False)
        seed.seed(reset=True)
        sessions.install()
        yield
        seed.clear()


@pytest.fixture
def as_tenant():
    """Open connections as a signed-in request of a tenant would."""
    tokens = []

    def enter(tenant_id):
        tokens.append(db.TENANT.set(tenant_id))

    yield enter
    for token in reversed(tokens):
        db.TENANT.reset(token)


def test_another_tenants_records_are_404_over_the_api():
    acme = sessions.client(tenants.USER)
    assert acme.get("/api/claims/CLM-1001").status_code == 404
    listed = acme.get("/api/claims").json()
    assert len(listed) == ACME_CLAIMS
    assert all(c["claim_id"].startswith("CLM-50") for c in listed)


def test_a_query_without_its_tenant_filter_returns_only_the_tenants_rows(as_tenant):
    as_tenant(tenants.ACME)
    with db.connect() as conn:
        claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        others = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE tenant_id <> ?", (tenants.ACME,)
        ).fetchone()[0]
        user = conn.execute("SELECT current_user").fetchone()[0]
    assert claims == ACME_CLAIMS
    assert others == 0
    assert user == db.APP_ROLE


def test_work_with_no_caller_sees_every_tenant():
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == ALL_CLAIMS


def test_tenant_id_has_no_default():
    with db.connect() as conn:
        defaults = conn.execute(
            "SELECT table_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND column_name = 'tenant_id'"
            " AND column_default IS NOT NULL"
        ).fetchall()
    assert defaults == []


def test_an_insert_without_a_tenant_fails(as_tenant):
    as_tenant(tenants.ACME)
    with pytest.raises(exc.DBAPIError), db.connect() as conn:
        conn.execute(
            "INSERT INTO sendbacks (claim_id, handler_id, reason, created_at)"
            " VALUES ('CLM-5001', 'HND-A1', 'x', 'now')"
        )


def test_a_tenant_cannot_write_another_tenants_rows(as_tenant):
    as_tenant(tenants.ACME)
    with pytest.raises(exc.ProgrammingError), db.connect() as conn:
        conn.execute(
            "INSERT INTO sendbacks (claim_id, handler_id, reason, created_at,"
            " tenant_id) VALUES ('CLM-1001', 'HND-01', 'x', 'now', 'T-UNDERCOVER')"
        )
    with db.connect() as conn:
        changed = conn.execute(
            "UPDATE claims SET state = 'decided' WHERE claim_id = 'CLM-1001'"
        ).rowcount
    assert changed == 0


def test_a_whole_claim_run_works_under_the_application_role(monkeypatch):
    client = sessions.client()
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    started = client.post("/api/claims/CLM-1001/runs").json()
    run = client.get(f"/api/runs/{started['run_id']}").json()
    claim = client.get("/api/claims/CLM-1001").json()
    assert run["status"] == "succeeded"
    assert claim["state"] == "decided"


def test_even_the_owner_cannot_insert_without_a_tenant():
    with pytest.raises(exc.IntegrityError), db.connect() as conn:
        conn.execute(
            "INSERT INTO sendbacks (claim_id, handler_id, reason, created_at)"
            " VALUES ('CLM-5001', 'HND-A1', 'x', 'now')"
        )
