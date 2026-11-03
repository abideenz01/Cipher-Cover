"""Signed-in clients and agent tokens for the tests.

conftest.py gives each seeded user a session with a known token, so a test
client can act as anyone without signing in.
"""

from typing import Any

from fastapi.testclient import TestClient

from backend import auth, db, runs
from backend.main import app

TENANT = "T-UNDERCOVER"
PASSWORD = "a-demo-password-for-tests"  # noqa: S105 - test-only demo password
FOREVER = "2100-01-01T00:00:00+00:00"

# The demo sign-ins: one per handler, then the admin and the auditor.
SENIOR = "USR-01"
TRAINEE = "USR-04"
SIU = "USR-05"
ADMIN = "USR-ADMIN"
AUDITOR = "USR-AUDIT"


def token(user_id: str) -> str:
    """Return the test session token of a user."""
    return f"cs_test_{user_id}"


def headers(user_id: str = SENIOR) -> dict[str, str]:
    """Return headers that sign a request in as a user."""
    return {"Authorization": f"Bearer {token(user_id)}"}


def client(user_id: str = SENIOR) -> TestClient:
    """Return a client signed in as a user, by default a senior handler."""
    return TestClient(app, headers=headers(user_id))


def install() -> None:
    """Give every user a session that lasts for the whole test."""
    with db.connect() as conn:
        users = conn.execute("SELECT user_id, tenant_id FROM users").fetchall()
        conn.executemany(
            "INSERT OR IGNORE INTO sessions (token_hash, user_id, tenant_id, csrf_hash,"
            " created_at, last_seen, expires_at, revoked_at)"
            " VALUES (?, ?, ?, '', ?, ?, ?, '')",
            [
                (
                    auth.digest(token(u["user_id"])),
                    u["user_id"],
                    u["tenant_id"],
                    FOREVER,
                    FOREVER,
                    FOREVER,
                )
                for u in users
            ],
        )


def bearer(value: str) -> dict[str, str]:
    """Return headers that send a token."""
    return {"Authorization": f"Bearer {value}"}


def claim_agent(run_id: str) -> dict[str, str]:
    """Return headers for the claim agent working a claim run."""
    with db.connect() as conn:
        return bearer(runs.claim_token(conn, run_id))


def queue_agent(run_id: str) -> dict[str, str]:
    """Return headers for the queue agent working a queue run."""
    with db.connect() as conn:
        tenant_id = runs.tenant_of(conn, run_id)
        return bearer(auth.issue(conn, tenant_id, "queue", 3600, run_id=run_id))


def voice_agent(user_id: str = SENIOR) -> str:
    """Return a voice token acting for a user."""
    with db.connect() as conn:
        tenant_id = conn.execute(
            "SELECT tenant_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()["tenant_id"]
        return auth.issue(conn, tenant_id, "voice", 3600, user_id=user_id)


def anyone() -> TestClient:
    """Return a client that is not signed in."""
    return TestClient(app)


def detail(response: Any) -> str:
    """Return a refusal's message."""
    return response.json()["detail"]
